"""F002 M2 — 离线 LLM 分析模块（spec v1）。

两阶段架构：
  Phase 1 全量分析（默认）：LogParser → LogPointMatcher → 全量 LLM → AnalysisReport
  Phase 2 深入分析（按需）：选 line + M1 get_call_context + Phase 1 报告 → 强模型 LLM
                            → DeepAnalysisRecord → 回写 M1 llm_hypothesis
"""
