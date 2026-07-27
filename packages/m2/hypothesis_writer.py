"""F002 M2 — hypothesis_writer（spec §十 + AC-9）。

Phase 2 DeepAnalysisRecord → M1 LogPoint.llm_hypothesis 回写入口。

回写流程（spec §十）：
  Phase 2 deep_analyze 完成 →
    hypothesis_writer.write_back(repo_id, deep_record) →
    M1 RepoLogGraphService.update_log_point_hypothesis(log_point_ids, hypothesis)

字段映射规则（DeepAnalysisRecord → LLMHypothesis）：
  root_cause_hypothesis → summary        # 根因假设作为摘要
  fix_suggestion        → suggested_check  # 修复建议作为检查建议
  model_name            → model_name     # 直传
  prompt_hash           → prompt_hash    # 直传
  generated_at          → generated_at   # 直传
  possible_causes       → []             # DeepAnalysisRecord 没有等价字段，留空
  error_kind            → ERROR_KIND_UNKNOWN  # DeepAnalysisRecord 无等价字段，留默认

回写规则：
  - log_point_ids 为空（无 LogPoint 匹配）→ 不调用 M1，返回 0
  - 调用 M1 update_log_point_hypothesis，由 M1 内部过滤 confirmed 状态
  - 覆盖式写入（Phase 2 iteration 累积，后一次覆盖前一次）
  - M1 抛异常 → 传播（不能静默吞，否则 Phase 2 报告写完了但 M1 没回写）
"""
from __future__ import annotations

from dataclasses import dataclass

from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.enums import ERROR_KIND_UNKNOWN
from packages.contracts.log_point import LLMHypothesis


@dataclass(frozen=True)
class WriteBackResult:
    """回写结果摘要。"""
    updated_count: int                # M1 实际更新行数
    written_log_point_ids: list[str]  # 调用方传入的 log_point_ids 原集
    skipped_log_point_ids: list[str]  # fallback 到空（M1 内部过滤不暴露细节）


class HypothesisWriter:
    """Phase 2 假设回写器（spec §十 + AC-9）。

    依赖 M1 RepoLogGraphService.update_log_point_hypothesis（F002 实施时同步加）。
    通过依赖注入 M1 service（不直接 import），避免 M2 ↔ M1 循环依赖。
    """

    WRITER_IDENTITY = "m2-phase2-deep-analyzer"

    def __init__(self, m1_service: "M1ServiceProtocol") -> None:
        self._m1 = m1_service

    def write_back(self, repo_id: str, record: DeepAnalysisRecord) -> WriteBackResult:
        """将 DeepAnalysisRecord 回写 M1 LogPoint.llm_hypothesis。

        Args:
            repo_id: 关联代码仓 id（spec §三 AnalysisReport.repo_id）
            record: Phase 2 深入分析记录

        Returns:
            WriteBackResult（updated_count=0 时表示无 LogPoint 匹配或全部 candidate 状态）
        """
        # 无 LogPoint 匹配（log_message_template 哈希未命中 M1 索引）→ fallback 跳过回写
        if not record.log_point_ids:
            return WriteBackResult(
                updated_count=0,
                written_log_point_ids=[],
                skipped_log_point_ids=[],
            )

        # 字段映射：DeepAnalysisRecord → LLMHypothesis
        hypothesis = LLMHypothesis(
            summary=record.root_cause_hypothesis,
            possible_causes=[],  # DeepAnalysisRecord 没有等价字段，留空
            error_kind=ERROR_KIND_UNKNOWN,  # DeepAnalysisRecord 无等价字段，留默认
            suggested_check=record.fix_suggestion,
            model_name=record.model_name,
            prompt_hash=record.prompt_hash,
            generated_at=record.generated_at,
        )

        # 调用 M1 update_log_point_hypothesis（M1 内部过滤 confirmed 状态）
        # 异常向上传播：Phase 2 报告已写完，但 M1 回写失败必须可见
        n_updated = self._m1.update_log_point_hypothesis(
            log_point_ids=record.log_point_ids,
            hypothesis=hypothesis,
            writer=self.WRITER_IDENTITY,
        )

        return WriteBackResult(
            updated_count=n_updated,
            written_log_point_ids=record.log_point_ids,
            skipped_log_point_ids=[],  # M1 内部过滤，不暴露细节
        )


# 协议类型（仅用于类型提示，避免运行时 M2 ↔ M1 循环 import）
from typing import Protocol  # noqa: E402


class M1ServiceProtocol(Protocol):
    """M1 RepoLogGraphService 的最小协议（仅暴露 M2 需要的方法）。"""
    def update_log_point_hypothesis(
        self,
        log_point_ids: list[str],
        hypothesis: LLMHypothesis,
        writer: str,
    ) -> int: ...
