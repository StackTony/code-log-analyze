"""F002 M2 — DeepAnalysisRecord 数据契约（spec §三）。

Phase 2 深入分析记录 — M2 按需输出，含根因假设 + 修复建议 + 关联证据。
迭代性：parent_record_id 链 + iteration 递增（累积上下文）。
"""
from __future__ import annotations

import dataclasses
from datetime import datetime

from packages.contracts.analysis_report import TokenUsage
from packages.contracts.log_point import CallContext, CaseRef


@dataclasses.dataclass(frozen=True)
class DeepAnalysisRecord:
    """Phase 2 深入分析记录（M2 spec §三）。

    持久化到 deep_analysis 表（P0 持久化铁律：TTL=0 默认持久化）。
    回写 M1 LogPoint.llm_hypothesis 字段（M1 spec §三 L145 预留位）。
    """
    id: str                                 # UUID
    report_id: str                          # 关联 Phase 1 报告
    line_ids: list[str]                     # 选定的日志条目
    log_point_ids: list[str]                # 关联 M1 LogPoint（通过 template 匹配）
    # 上下文引用
    call_contexts: list[CallContext]        # M1 get_call_context 结果快照
    # LLM 输出
    root_cause_hypothesis: str             # 根因假设
    fix_suggestion: str | None             # 修复建议（M4 改进模块的输入）
    related_evidence: list[CaseRef]        # 历史案例引用
    # 元数据
    model_name: str                         # phase2_model
    prompt_hash: str
    iteration: int                          # 第几次深入分析（1, 2, 3...）
    parent_record_id: str | None           # 前次深入分析 ID（累积上下文链）
    generated_at: datetime
    token_usage: TokenUsage
