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
