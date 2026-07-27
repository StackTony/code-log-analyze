"""F002 M2 — hypothesis_writer 测试（spec §十 + AC-9）。

验证 Phase 2 DeepAnalysisRecord → M1 LogPoint.llm_hypothesis 回写路径。

回写语义（spec §十）：
  Phase 2 deep_analyze 完成 →
    hypothesis_writer.write_back(repo_id, log_point_ids, deep_record) →
    M1 RepoLogGraphService.update_log_point_hypothesis(log_point_ids, hypothesis)

回写策略：
  - 从 DeepAnalysisRecord 构造 LLMHypothesis（root_cause_hypothesis → summary）
  - log_point_ids 为空时不调用 M1（无 LogPoint 匹配 → fallback 跳过回写）
  - 只回写 confirmed 状态的 LogPoint（M1 update_log_point_hypothesis 内部已过滤）
  - 覆盖式写入（Phase 2 iteration 累积，后一次覆盖前一次，spec §三 L40）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from packages.contracts.analysis_report import TokenUsage
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.m2.hypothesis_writer import HypothesisWriter, WriteBackResult


def _make_deep_record(
    log_point_ids: list[str] | None = None,
    root_cause: str = "db pool exhausted",
    fix_suggestion: str | None = "increase pool size",
    iteration: int = 1,
    parent_record_id: str | None = None,
) -> DeepAnalysisRecord:
    return DeepAnalysisRecord(
        id="da-1",
        report_id="rpt-1",
        line_ids=["line-1"],
        log_point_ids=log_point_ids or [],
        call_contexts=[],
        root_cause_hypothesis=root_cause,
        fix_suggestion=fix_suggestion,
        related_evidence=[],
        model_name="claude-opus-4",
        prompt_hash="sha256:abc",
        iteration=iteration,
        parent_record_id=parent_record_id,
        generated_at=datetime(2026, 7, 27, 0, 0, 0),
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_cost_usd=0.02),
    )


class TestHypothesisWriterWriteBack:
    """write_back 单元行为（mock M1 service）。"""

    def test_write_back_returns_zero_when_log_point_ids_empty(self) -> None:
        """log_point_ids 为空（无匹配 LogPoint）→ 不调用 M1，返回 0。"""
        m1_service = MagicMock()
        m1_service.update_log_point_hypothesis.return_value = 0
        writer = HypothesisWriter(m1_service=m1_service)

        record = _make_deep_record(log_point_ids=[])
        result = writer.write_back(repo_id="repo-1", record=record)

        assert result.updated_count == 0
        assert result.written_log_point_ids == []
        m1_service.update_log_point_hypothesis.assert_not_called()

    def test_write_back_calls_m1_with_constructed_hypothesis(self) -> None:
        """log_point_ids 非空 → 调用 M1 update_log_point_hypothesis，传入 LLMHypothesis。"""
        m1_service = MagicMock()
        m1_service.update_log_point_hypothesis.return_value = 2
        writer = HypothesisWriter(m1_service=m1_service)

        record = _make_deep_record(
            log_point_ids=["lp-1", "lp-2"],
            root_cause="connection timeout due to pool exhaustion",
            fix_suggestion="increase pool size to 20",
        )
        result = writer.write_back(repo_id="repo-1", record=record)

        assert result.updated_count == 2
        assert result.written_log_point_ids == ["lp-1", "lp-2"]
        m1_service.update_log_point_hypothesis.assert_called_once()
        call_args = m1_service.update_log_point_hypothesis.call_args
        assert call_args.kwargs["log_point_ids"] == ["lp-1", "lp-2"]
        assert call_args.kwargs["writer"] == "m2-phase2-deep-analyzer"

        # 验证构造的 LLMHypothesis 字段映射
        hyp = call_args.kwargs["hypothesis"]
        assert hyp.summary == "connection timeout due to pool exhaustion"
        assert hyp.model_name == "claude-opus-4"
        assert hyp.prompt_hash == "sha256:abc"
        assert hyp.generated_at == record.generated_at

    def test_write_back_handles_m1_partial_update(self) -> None:
        """M1 只更新了部分 id（candidate 状态被跳过）→ updated_count 反映实际数量。"""
        m1_service = MagicMock()
        m1_service.update_log_point_hypothesis.return_value = 1  # 只 1 个 confirmed
        writer = HypothesisWriter(m1_service=m1_service)

        record = _make_deep_record(log_point_ids=["lp-1-confirmed", "lp-2-candidate"])
        result = writer.write_back(repo_id="repo-1", record=record)

        assert result.updated_count == 1
        # 写入端不知道哪个被跳过了，只记 log_point_ids 原集
        assert result.written_log_point_ids == ["lp-1-confirmed", "lp-2-candidate"]

    def test_write_back_propagates_m1_error(self) -> None:
        """M1 抛异常 → 传播给调用方（不能静默吞，否则 Phase 2 报告写完了但 M1 没回写）。"""
        m1_service = MagicMock()
        m1_service.update_log_point_hypothesis.side_effect = RuntimeError("db locked")
        writer = HypothesisWriter(m1_service=m1_service)

        record = _make_deep_record(log_point_ids=["lp-1"])
        with pytest.raises(RuntimeError, match="db locked"):
            writer.write_back(repo_id="repo-1", record=record)

    def test_write_back_with_iteration_context(self) -> None:
        """iteration > 1 时，仍按当前 DeepAnalysisRecord 内容覆盖回写。"""
        m1_service = MagicMock()
        m1_service.update_log_point_hypothesis.return_value = 1
        writer = HypothesisWriter(m1_service=m1_service)

        record = _make_deep_record(
            log_point_ids=["lp-1"],
            root_cause="iteration 2 refines: actual root cause is X",
            iteration=2,
            parent_record_id="da-0",
        )
        result = writer.write_back(repo_id="repo-1", record=record)

        assert result.updated_count == 1
        call_kwargs = m1_service.update_log_point_hypothesis.call_args.kwargs
        assert call_kwargs["hypothesis"].summary.startswith("iteration 2 refines")


class TestHypothesisWriterConstructsHypothesis:
    """DeepAnalysisRecord → LLMHypothesis 字段映射规则。"""

    def test_hypothesis_summary_from_root_cause(self) -> None:
        """LLMHypothesis.summary = DeepAnalysisRecord.root_cause_hypothesis。"""
        m1_service = MagicMock()
        m1_service.update_log_point_hypothesis.return_value = 1
        writer = HypothesisWriter(m1_service=m1_service)

        record = _make_deep_record(
            log_point_ids=["lp-1"],
            root_cause="my custom root cause text",
        )
        writer.write_back(repo_id="repo-1", record=record)

        hyp = m1_service.update_log_point_hypothesis.call_args.kwargs["hypothesis"]
        assert hyp.summary == "my custom root cause text"

    def test_hypothesis_fix_suggestion_passed_through(self) -> None:
        """DeepAnalysisRecord.fix_suggestion → LLMHypothesis.suggested_check。"""
        m1_service = MagicMock()
        m1_service.update_log_point_hypothesis.return_value = 1
        writer = HypothesisWriter(m1_service=m1_service)

        record = _make_deep_record(
            log_point_ids=["lp-1"],
            fix_suggestion="check pg connection pool config",
        )
        writer.write_back(repo_id="repo-1", record=record)

        hyp = m1_service.update_log_point_hypothesis.call_args.kwargs["hypothesis"]
        assert hyp.suggested_check == "check pg connection pool config"

    def test_hypothesis_fix_suggestion_none_passthrough(self) -> None:
        """fix_suggestion 为 None → suggested_check=None。"""
        m1_service = MagicMock()
        m1_service.update_log_point_hypothesis.return_value = 1
        writer = HypothesisWriter(m1_service=m1_service)

        record = _make_deep_record(
            log_point_ids=["lp-1"],
            fix_suggestion=None,
        )
        writer.write_back(repo_id="repo-1", record=record)

        hyp = m1_service.update_log_point_hypothesis.call_args.kwargs["hypothesis"]
        assert hyp.suggested_check is None
