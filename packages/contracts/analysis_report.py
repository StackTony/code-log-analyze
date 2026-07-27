"""F002 M2 — AnalysisReport 数据契约（spec §三）。

Phase 1 全量分析报告 — M2 主输出，含三类信息：
  1. 系统行为总结（system_summary）
  2. 异常定位（anomaly_localization）
  3. 错误关联（error_correlation）
"""
from __future__ import annotations

import dataclasses
from datetime import datetime


@dataclasses.dataclass(frozen=True)
class TokenUsage:
    """LLM 调用 token 用量 + 成本（M2 复用，spec §三）。"""
    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: float


@dataclasses.dataclass(frozen=True)
class Anomaly:
    """异常定位条目（M2 spec §三）。"""
    line_ids: list[str]                     # 关联日志条目
    severity: str                           # info|warn|error|critical（SEVERITY_*）
    module: str | None                      # 模块/服务名
    summary: str                            # 一句话异常描述
    evidence_snippets: list[str]            # 日志原文片段


@dataclasses.dataclass(frozen=True)
class ErrorChain:
    """错误关联链（M2 spec §三）。"""
    chain_id: str
    line_ids_ordered: list[str]             # 按时间顺序的错误条目
    relation: str                           # causal|correlation|propagation（RELATION_*）
    summary: str                            # 链路描述
    confidence_score: float                 # 0.0-1.0


@dataclasses.dataclass(frozen=True)
class AnalysisReport:
    """Phase 1 全量分析报告 — M2 主输出（spec §三）。

    持久化到 analysis_report 表（P0 持久化铁律：TTL=0 默认持久化）。
    """
    id: str                                 # UUID
    repo_id: str | None                     # 关联代码仓（日志无 repo 时为 None）
    log_source: str                         # 日志来源标识（文件名/M3 流标识）
    log_line_count: int                     # 分析的日志条目数
    window_start: datetime | None          # 时间窗起点（按日志内时间戳）
    window_end: datetime | None
    model_name: str                         # phase1_model
    prompt_hash: str                        # prompt 版本追溯
    # 三类核心信息
    system_summary: str                     # 系统行为总结
    anomaly_localization: list[Anomaly]    # 异常定位
    error_correlation: list[ErrorChain]    # 错误关联
    # 元数据
    generated_at: datetime
    duration_seconds: float
    token_usage: TokenUsage
    ingestion_status: str                   # draft|archived（STATUS_*）
