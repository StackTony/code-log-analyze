"""F002 M2 — LogParser（spec §二 + §五）。

日志文本 → LogEntry 列表。支持至少 3 种格式：Python logging 默认 / JSON structured / syslog 风格（AC-1）。

模板提取算法（用于 M1 LogPoint 匹配）：
  原文 `"User 12345 logged in"` → 模板 `"User {var_0} logged in"` + variables `{"var_0": "12345"}`

本文件 v1 起步：实现 Python logging 默认格式的解析骨架，其他格式 F002 实施阶段补。
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from packages.contracts.log_entry import LogEntry


# Python logging 默认格式示例：
#   2026-07-27 08:30:00,123 INFO [module] User 12345 logged in
#   2026-07-27T08:30:00,123 INFO module: User 12345 logged in
_PYTHON_LOGGING_PATTERN = re.compile(
    r"""^
    (?P<timestamp>\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+
    (?P<level>INFO|WARN|WARNING|ERROR|DEBUG|CRITICAL)\s*
    (?:\[(?P<module>[^\]]+)\]\s*|(?P<module2>\w+):\s*)?
    (?P<message>.*)
    """,
    re.VERBOSE,
)


def _normalize_level(level: str) -> str:
    """归一化日志级别（WARNING → WARN 等）。"""
    mapping = {"WARNING": "WARN", "CRITICAL": "CRITICAL"}
    return mapping.get(level, level)


def _extract_template(message: str) -> tuple[str, dict[str, str]]:
    """从消息原文提取模板 + 变量。

    简化算法：把数字、UUID、长 hex 串替换为 {var_N} 占位符。
    F002 实施阶段扩展为更智能的模板提取（如复用 M1 tree-sitter 解析）。

    >>> _extract_template("User 12345 logged in from 192.168.1.1")
    ('User {var_0} logged in from {var_1}', {'var_0': '12345', 'var_1': '192.168.1.1'})
    """
    variables: dict[str, str] = {}
    var_counter = 0

    # 匹配 UUID / IPv4 / 数字 / 长 hex 串
    pattern = re.compile(
        r"""(
            [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}  # UUID
            | \d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}                          # IPv4
            | \d+                                                          # 数字
            | 0x[0-9a-f]+                                                   # hex
        )""",
        re.VERBOSE | re.IGNORECASE,
    )

    def _replace(m: re.Match[str]) -> str:
        nonlocal var_counter
        key = f"var_{var_counter}"
        variables[key] = m.group(1)
        var_counter += 1
        return f"{{{key}}}"

    template = pattern.sub(_replace, message)
    return template, variables


def parse_line(raw_text: str, source_file: str | None = None, source_line: int | None = None) -> LogEntry:
    """解析单行日志为 LogEntry（Python logging 默认格式，v1 起步）。

    无法识别格式时仍返回 LogEntry，但 timestamp/level/template 为 None。
    """
    match = _PYTHON_LOGGING_PATTERN.match(raw_text)
    if match is None:
        # 未识别格式 — 全文作为 raw_text，其他字段 None
        return LogEntry(
            line_id=str(uuid.uuid4()),
            raw_text=raw_text,
            timestamp=None,
            level=None,
            log_message_template=None,
            variables={},
            source_file=source_file,
            source_line=source_line,
        )

    timestamp_str = match.group("timestamp").replace("T", " ").replace(",", ".")
    try:
        timestamp = datetime.fromisoformat(timestamp_str)
    except ValueError:
        timestamp = None

    level = _normalize_level(match.group("level"))
    module = match.group("module") or match.group("module2")
    message = match.group("message").strip()
    template, variables = _extract_template(message)

    return LogEntry(
        line_id=str(uuid.uuid4()),
        raw_text=raw_text,
        timestamp=timestamp,
        level=level,
        log_message_template=template,
        variables=variables,
        source_file=source_file or module,
        source_line=source_line,
    )


class LogParser:
    """日志文本解析器（spec §二 Phase 1 step 1）。

    将原始日志文本（多行字符串）解析为 LogEntry 列表，提取
    timestamp/level/log_message_template/variables 供后续 Phase 1 LLM 分析
    和 LogPoint 匹配使用。
    """

    def parse(self, log_text: str, source_file: str | None = None) -> list[LogEntry]:
        """解析多行日志文本 → LogEntry 列表。

        Args:
            log_text: 多行日志文本（\\n 分隔）
            source_file: 日志来源文件名（可选）

        Returns:
            list[LogEntry]，每行一个；空行跳过
        """
        entries: list[LogEntry] = []
        for line_num, raw_line in enumerate(log_text.splitlines(), start=1):
            stripped = raw_line.rstrip()
            if not stripped:
                continue
            entries.append(parse_line(stripped, source_file=source_file, source_line=line_num))
        return entries
