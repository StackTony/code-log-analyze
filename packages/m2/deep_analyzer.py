"""F002 M2 — DeepAnalyzer（spec §三 + AC-7/8/10/11）。

Phase 2 深入分析：
  选定日志条目 + M1 LogPoint + M1 CallContext + Phase 1 报告摘要 →
  强模型 LLM → DeepAnalysisRecord → 回写 M1 LogPoint.llm_hypothesis

设计要点：
  - AC-7: 上下文组装含 4 部分（entry 原文 + LogPoint + CallContext + Phase 1 摘要）
  - AC-8: 输出 DeepAnalysisRecord 含 root_cause_hypothesis + fix_suggestion + related_evidence
  - AC-10: 迭代性 — parent_record 链累积上下文（iteration 递增）
  - AC-11: max_iterations（默认 5）触发时抛 IterationLimitExceeded + 提示归档重启
  - AC-5: 脱敏（复用 M1 LogSanitizer）
  - AC-6: 缓存（key 含 phase2 + report_id + line_ids + model_name + iteration）

LLM 调用 schema（Phase 2）：
  Input: 装配后的 prompt（4 部分上下文）
  Output: JSON 含 root_cause_hypothesis / fix_suggestion / related_evidence / token_usage
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from packages.contracts.analysis_report import AnalysisReport, TokenUsage
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.enums import RELATION_CAUSAL
from packages.contracts.log_entry import LogEntry
from packages.contracts.log_point import CallContext, CaseRef, LogPoint
from packages.m1.log_sanitizer import LogSanitizer, generate_prompt_hash
from packages.m1.llm_hypothesis_generator import LLMClient, RedisCache


class IterationLimitExceeded(Exception):
    """AC-11: 累积迭代达上限，拒绝新调用。

    spec AC-11 措辞：提示用户归档 Phase 1 报告后重启 Phase 2 流程。
    """

    def __init__(self, current: int, limit: int, report_id: str) -> None:
        self.current = current
        self.limit = limit
        self.report_id = report_id
        super().__init__(
            f"phase2 iteration limit reached: current={current} >= limit={limit} "
            f"for report_id={report_id}; "
            f"archive report {report_id} and start a fresh phase2 analysis to reset iteration chain"
        )


@dataclass(frozen=True)
class Phase2Config:
    """Phase 2 LLM 调用配置。"""
    model_name: str               # 强模型（spec AC-17）
    max_iterations: int = 5       # AC-11 累积上限
    cache_ttl_seconds: int = 86400


class DeepAnalyzer:
    """Phase 2 深入分析器（spec §三 + AC-7/8/10/11）。"""

    PHASE_TAG = "phase2"

    def __init__(
        self,
        llm_client: LLMClient,
        cache: RedisCache,
        sanitizer: LogSanitizer,
        config: Phase2Config,
    ) -> None:
        self._llm = llm_client
        self._cache = cache
        self._sanitizer = sanitizer
        self._config = config

    # ---- AC-7: 上下文组装 ----

    def _assemble_prompt(
        self,
        entries: list[LogEntry],
        log_points: list[LogPoint],
        call_contexts: list[CallContext],
        phase1_report: AnalysisReport,
        parent_record: DeepAnalysisRecord | None = None,
    ) -> str:
        """AC-7: 装配 4 部分上下文 + 可选的 iteration 链。"""
        parts: list[str] = []

        # 1. 选定日志原文
        parts.append("# Selected log entries (Phase 2 deep analysis target)")
        for i, e in enumerate(entries):
            parts.append(f"  [{i}] line_id={e.line_id} level={e.level} raw={e.raw_text}")
            if e.log_message_template:
                parts.append(f"      template={e.log_message_template}")

        # 2. M1 LogPoint（代码仓 AST 提取）
        parts.append("\n# M1 LogPoints (repo AST extraction)")
        if log_points:
            for lp in log_points:
                parts.append(
                    f"  - id={lp.id} file={lp.file_path} func={lp.function_signature} "
                    f"line={lp.line_start} lang={lp.language} template={lp.log_message_template}"
                )
        else:
            parts.append("  (no LogPoint matched - fallback analysis without repo context)")

        # 3. M1 CallContext
        parts.append("\n# M1 CallContext (call graph around log point)")
        for cc in call_contexts:
            parts.append(f"  - function={cc.function_signature}")
            parts.append(f"    callers={cc.callers}")
            parts.append(f"    callees={cc.callees}")
            parts.append(f"    community={cc.enclosing_community}")

        # 4. Phase 1 报告摘要
        parts.append("\n# Phase 1 analysis report summary")
        parts.append(f"  system_summary: {phase1_report.system_summary}")
        if phase1_report.anomaly_localization:
            parts.append("  anomalies:")
            for a in phase1_report.anomaly_localization:
                parts.append(
                    f"    - lines={a.line_ids} severity={a.severity} "
                    f"module={a.module} summary={a.summary}"
                )
        if phase1_report.error_correlation:
            parts.append("  error_chains:")
            for ec in phase1_report.error_correlation:
                parts.append(
                    f"    - chain={ec.chain_id} lines={ec.line_ids_ordered} "
                    f"relation={ec.relation} confidence={ec.confidence_score}"
                )

        # AC-10: 迭代链（parent_record 上下文）
        if parent_record is not None:
            parts.append("\n# Previous phase2 iteration context (cumulative)")
            parts.append(
                f"  parent iteration={parent_record.iteration} "
                f"id={parent_record.id}"
            )
            parts.append(
                f"  parent root_cause_hypothesis: {parent_record.root_cause_hypothesis}"
            )
            if parent_record.fix_suggestion:
                parts.append(f"  parent fix_suggestion: {parent_record.fix_suggestion}")

        # 输出要求
        parts.append("\n# Required JSON output schema")
        parts.append("  root_cause_hypothesis: str (one paragraph)")
        parts.append("  fix_suggestion: str | null")
        parts.append(
            "  related_evidence: list of {case_id, repo_id, file_path, "
            "function_signature, log_template, resolved_at (ISO), "
            "resolution_summary, resolution_diff_url}"
        )
        parts.append(
            "  token_usage: {prompt_tokens, completion_tokens, total_cost_usd}"
        )

        return "\n".join(parts)

    # ---- AC-6: 缓存 ----

    def _cache_key(
        self, report_id: str, entries: list[LogEntry], iteration: int,
    ) -> str:
        """AC-6: cache key 含 phase2 + report_id + line_ids + model_name + iteration。

        iteration 区分不同次的深入分析（避免 iteration 2 命中 iteration 1 的缓存，
        导致累积上下文失效）。
        """
        line_ids = sorted(e.line_id for e in entries)
        h = hashlib.sha256("|".join(line_ids).encode("utf-8")).hexdigest()[:32]
        return (
            f"m2:{self.PHASE_TAG}:report={report_id}:iter={iteration}:"
            f"model={self._config.model_name}:{h}"
        )

    def _sanitize(self, text: str) -> str:
        """AC-5: 调 LLM 前脱敏。"""
        sanitized, _hits = self._sanitizer.sanitize(text)
        return sanitized

    # ---- AC-8 + AC-10 + AC-11: 主流程 ----

    async def analyze(
        self,
        report_id: str,
        entries: list[LogEntry],
        log_points: list[LogPoint],
        call_contexts: list[CallContext],
        phase1_report: AnalysisReport,
        parent_record: DeepAnalysisRecord | None = None,
    ) -> DeepAnalysisRecord:
        """生成 Phase 2 深入分析记录。

        Args:
            report_id: 关联 Phase 1 报告 id
            entries: 选定的日志条目（用户在 Phase 1 报告中点选）
            log_points: 关联 M1 LogPoint（通过 LogPointMatcher 匹配，可为空 fallback）
            call_contexts: M1 get_call_context 结果（每选 line 一个）
            phase1_report: Phase 1 报告（提供摘要上下文）
            parent_record: 前次深入分析（iteration > 1 时必填）

        Returns:
            DeepAnalysisRecord（持久化 + 回写 M1 由调用方负责）

        Raises:
            IterationLimitExceeded: AC-11 累积达上限
        """
        # AC-11: iteration 计算与上限检查
        next_iteration = (parent_record.iteration + 1) if parent_record else 1
        if next_iteration > self._config.max_iterations:
            raise IterationLimitExceeded(
                current=next_iteration,
                limit=self._config.max_iterations,
                report_id=report_id,
            )

        # AC-6: 缓存命中
        cache_key = self._cache_key(report_id, entries, next_iteration)
        cached = self._cache.get(cache_key)
        if cached is not None:
            payload = json.loads(cached)
        else:
            # AC-7 + AC-10: 上下文装配
            prompt = self._assemble_prompt(
                entries=entries,
                log_points=log_points,
                call_contexts=call_contexts,
                phase1_report=phase1_report,
                parent_record=parent_record,
            )
            # AC-5: 脱敏
            sanitized = self._sanitize(prompt)
            raw = await self._llm.complete(sanitized)
            payload = json.loads(raw)
            self._cache.set(cache_key, raw, ttl_seconds=self._config.cache_ttl_seconds)

        # AC-8: 解析 DeepAnalysisRecord
        evidence = [
            CaseRef(
                case_id=e["case_id"], repo_id=e["repo_id"],
                file_path=e["file_path"], function_signature=e["function_signature"],
                log_template=e["log_template"],
                resolved_at=datetime.fromisoformat(e["resolved_at"]),
                resolution_summary=e["resolution_summary"],
                resolution_diff_url=e.get("resolution_diff_url"),
            )
            for e in payload.get("related_evidence", [])
        ]
        tu = payload.get("token_usage", {})
        token_usage = TokenUsage(
            prompt_tokens=tu.get("prompt_tokens", 0),
            completion_tokens=tu.get("completion_tokens", 0),
            total_cost_usd=tu.get("total_cost_usd", 0.0),
        )

        prompt_hash = generate_prompt_hash(
            self._assemble_prompt(
                entries=entries, log_points=log_points,
                call_contexts=call_contexts, phase1_report=phase1_report,
                parent_record=parent_record,
            )
        )

        return DeepAnalysisRecord(
            id=f"da-{uuid.uuid4().hex[:12]}",
            report_id=report_id,
            line_ids=[e.line_id for e in entries],
            log_point_ids=[lp.id for lp in log_points],
            call_contexts=call_contexts,
            root_cause_hypothesis=payload["root_cause_hypothesis"],
            fix_suggestion=payload.get("fix_suggestion"),
            related_evidence=evidence,
            model_name=self._config.model_name,
            prompt_hash=prompt_hash,
            iteration=next_iteration,
            parent_record_id=parent_record.id if parent_record else None,
            generated_at=datetime.now(UTC),
            token_usage=token_usage,
        )
