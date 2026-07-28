"""F003 M3 — FileTailer 后台 polling task（spec §二 + AC-1）。

v1 用 polling 模式（跨平台优先，OQ-2 决策）。
位置 checkpoint 存内存（source_id → last_pos）+ 文件 size 检测轮转。
生产环境可持久化到 Redis（留 v2）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from packages.m3.event_ingestor import EventIngestor


class FileTailer:
    """M3 file_tail 数据源后台 polling task。"""

    def __init__(
        self,
        source_id: str,
        file_path: str,
        ingestor: EventIngestor,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._source_id = source_id
        self._file_path = file_path
        self._ingestor = ingestor
        self._poll_interval = poll_interval_seconds
        self._last_pos: int = 0
        self._last_size: int = 0
        self._task: asyncio.Task | None = None
        self._stopped = False

    def start(self) -> None:
        """启动 asyncio task（在 FastAPI lifespan 内调用）。"""
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._run_loop())

    def stop(self) -> None:
        """cancel 后台 task（pause_source 时调用）。"""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """主循环：polling + sleep。"""
        while not self._stopped:
            try:
                self._poll_once()
            except Exception:
                # logging 留 v2，v1 静默（避免单次失败拖死 task）
                pass
            await asyncio.sleep(self._poll_interval)

    def _poll_once(self) -> int:
        """单次 polling：读新增行 + 入库。返回 ingested 事件数。"""
        path = Path(self._file_path)
        if not path.exists():
            return 0

        current_size = path.stat().st_size

        # 文件轮转检测：size 变小 → reset
        if current_size < self._last_size:
            self._last_pos = 0
        self._last_size = current_size

        # 读新增部分
        if self._last_pos >= current_size:
            return 0

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(self._last_pos)
            new_content = f.read()
            self._last_pos = f.tell()

        if not new_content:
            return 0

        # 按行 ingest（最后一行可能不完整，留 v2 处理）
        lines = [ln for ln in new_content.splitlines() if ln.strip()]
        for line in lines:
            self._ingestor.ingest(source_id=self._source_id, raw_text=line)
        return len(lines)
