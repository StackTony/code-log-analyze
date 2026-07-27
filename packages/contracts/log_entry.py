"""F002 M2 — LogEntry 数据契约（spec §三）。

解析后的单条日志条目（M2 输入单元）。
"""
from __future__ import annotations

import dataclasses
from datetime import datetime


@dataclasses.dataclass(frozen=True)
class LogEntry:
    """解析后的单条日志条目（M2 输入单元，spec §三）。

    由 LogParser 从原始日志文本解析得到，作为 Phase 1 全量分析的输入单元
    和 Phase 2 深入分析的引用对象。
    """
    line_id: str                            # UUID
    raw_text: str                           # 原始日志行
    timestamp: datetime | None              # 解析出的时间戳
    level: str | None                       # INFO/WARN/ERROR/DEBUG
    log_message_template: str | None        # 解析出的模板（用于匹配 M1 LogPoint）
    variables: dict[str, str]               # 模板变量值
    source_file: str | None                 # 日志来源文件
    source_line: int | None                  # 原文件行号


@dataclasses.dataclass(frozen=True)
class LogSource:
    """日志来源标识（spec §四 LogAnalysisService.analyze_logs 入参）。

    三个字段互斥，按优先级 text > file_path > stream_id：
      - text: 直接传日志文本内容（最常见，HTTP API 上传）
      - file_path: 文件路径（服务端批处理）
      - stream_id: M3 在线扫描流的引用（M3 spec §一预留）
    """
    text: str | None = None
    file_path: str | None = None
    stream_id: str | None = None

    def resolve_text(self) -> str:
        """解析为日志文本内容。

        Returns:
            日志文本字符串

        Raises:
            ValueError: 三字段都为空 / file_path 不存在
            NotImplementedError: stream_id（M3 未实现，F003 实施时补）
        """
        if self.text is not None:
            return self.text
        if self.file_path is not None:
            import pathlib
            p = pathlib.Path(self.file_path)
            if not p.exists():
                raise ValueError(f"log source file not found: {self.file_path}")
            return p.read_text(encoding="utf-8", errors="replace")
        if self.stream_id is not None:
            raise NotImplementedError(
                f"stream_id log source not implemented (M3 family, stream_id={self.stream_id})"
            )
        raise ValueError("LogSource: all of text/file_path/stream_id are None")
