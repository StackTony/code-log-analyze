"""F002 M2 — LogAnalysisService（spec §四 + AC-15 + AC-14）。

5 个 API 方法编排层：
  - analyze_logs: LogParser → LogPointMatcher → ReportGenerator
                  → M2Repository.save + audit_log + metrics
  - deep_analyze: get_call_context + DeepAnalyzer + HypothesisWriter
                 → M2Repository.save + audit_log + metrics
  - get_report: M2Repository.get_analysis_report
  - list_deep_analyses: M2Repository.list_deep_analyses
  - archive_report: M2Repository.archive_report + audit_log

依赖注入：
  - session: SQLAlchemy Session（与 M1 共享）
  - audit: M1 AuditLogger
  - repository: M2Repository（封装三表 CRUD）
  - log_parser: LogParser
  - log_point_matcher: LogPointMatcher（依赖 LogPointIndex 协议）
  - report_generator: ReportGenerator（Phase 1 LLM）
  - deep_analyzer: DeepAnalyzer（Phase 2 LLM）
  - hypothesis_writer: HypothesisWriter（M1 回写入口）
  - m1_service: M1 RepoLogGraphService（get_call_context + update_log_point_hypothesis）
  - metrics: 可选 M2MetricsEmitter（spec §八 + AC-14，None 时不发送指标）
"""
from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from packages.contracts.analysis_report import AnalysisReport
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.enums import (
    ACTION_ARCHIVE_REPORT,
    ACTION_PHASE1_ANALYZE,
    ACTION_PHASE2_DEEP_ANALYZE,
)
from packages.contracts.log_entry import LogEntry, LogSource
from packages.m1.audit_log import AuditLogger
from packages.m1.unit_a_repo_registrar import User
from packages.m2.deep_analyzer import DeepAnalyzer
from packages.m2.hypothesis_writer import HypothesisWriter
from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher
from packages.m2.report_generator import ReportGenerator
from packages.m2.storage.repository import M2Repository

if TYPE_CHECKING:
    from packages.m2.metrics_emitter import M2MetricsEmitter


class LogAnalysisService:
    """M2 离线 LLM 分析服务（spec §四 + AC-15 + AC-14）。"""

    def __init__(
        self,
        session: Session,
        audit: AuditLogger,
        repository: M2Repository,
        log_parser: LogParser,
        log_point_matcher: LogPointMatcher,
        report_generator: ReportGenerator,
        deep_analyzer: DeepAnalyzer,
        hypothesis_writer: HypothesisWriter,
        m1_service: "M1ServiceProtocol",
        metrics: "M2MetricsEmitter | None" = None,
    ) -> None:
        self._session = session
        self._audit = audit
        self._repo = repository
        self._parser = log_parser
        self._matcher = log_point_matcher
        self._gen = report_generator
        self._deep = deep_analyzer
        self._writer = hypothesis_writer
        self._m1 = m1_service
        self._metrics = metrics

    # ---- Phase 1: analyze_logs ----

    async def analyze_logs(
        self,
        log_source: LogSource,
        analyzer: User,
        repo_id: str | None = None,
        window_hours: int | None = None,
    ) -> AnalysisReport:
        """Phase 1 全量分析（spec §四 + AC-3）。

        流程：
          1. LogSource.resolve_text() 拿日志文本
          2. LogParser.parse() 解析为 LogEntry 列表
          3. LogPointMatcher.match() 匹配 M1 LogPoint（如有关联 repo_id）
          4. ReportGenerator.generate() 调 LLM 生成报告
          5. M2Repository.save_analysis_report + save_log_entries 持久化
          6. 写 audit_log action=ACTION_PHASE1_ANALYZE
          7. 写 metrics（AC-14）
        """
        log_text = log_source.resolve_text()
        entries = self._parser.parse(log_text, source_file=log_source.file_path)

        # 匹配 M1 LogPoint（即使 repo_id 为 None，matcher 也会跑，log_point 全 fallback None）
        match_results = self._matcher.match(entries)

        # AC-14: 更新 log_point_match_rate gauge
        if self._metrics is not None and entries:
            matched = sum(1 for r in match_results if r.log_point is not None)
            rate = matched / len(entries)
            self._metrics.set_log_point_match_rate(rate=rate)

        # 生成 Phase 1 报告（duration 计时在 generator 内）
        t0 = time.perf_counter()
        report = await self._gen.generate(
            entries=entries,
            log_source=log_source.file_path or "<text>",
            repo_id=repo_id,
            window_hours_override=window_hours,
        )
        elapsed = time.perf_counter() - t0

        # AC-14: LLM 调用耗时 + 成本累计
        if self._metrics is not None:
            self._metrics.observe_llm_call_duration(phase="phase1", seconds=elapsed)
            self._metrics.inc_llm_cost(usd=report.token_usage.total_cost_usd)
            self._metrics.inc_analysis_report(repo_id=repo_id or "<no-repo>")

        # 持久化 AnalysisReport + LogEntry（AC-16 P0 持久化）
        self._repo.save_analysis_report(report)
        self._repo.save_log_entries(entries, report_id=report.id)

        # AC-15: 写 audit_log
        self._audit.log(
            actor=analyzer.id,
            action=ACTION_PHASE1_ANALYZE,
            target_repo_id=repo_id,
            target_log_point_ids=None,
            extra={
                "report_id": report.id,
                "log_line_count": report.log_line_count,
                "log_source": report.log_source,
            },
        )

        return report

    # ---- Phase 2: deep_analyze ----

    async def deep_analyze(
        self,
        report_id: str,
        line_ids: list[str],
        analyzer: User,
        iteration_context: str | None = None,  # 用户补充上下文（v1 暂未集成到 prompt）
    ) -> DeepAnalysisRecord:
        """Phase 2 深入分析（spec §四 + AC-7/8/9/10/11/15）。

        流程：
          1. 取 Phase 1 报告 + 选定 LogEntry 列表（按 line_ids）
          2. 对每个 LogEntry 取其匹配的 M1 LogPoint（log_point_id）
          3. 对每个 LogPoint 调 M1 get_call_context
          4. 取前次 DeepAnalysisRecord（同 line 的 iteration 最大者）作为 parent
          5. DeepAnalyzer.analyze() 调 LLM 生成 DeepAnalysisRecord
          6. M2Repository.save_deep_analysis 持久化
          7. HypothesisWriter.write_back() 回写 M1 LogPoint.llm_hypothesis
          8. 写 audit_log action=ACTION_PHASE2_DEEP_ANALYZE

        Raises:
            ValueError: report_id 或 line_ids 不存在
            IterationLimitExceeded: AC-11 累积达上限
        """
        # 1. 取 Phase 1 报告
        phase1_report = self._repo.get_analysis_report(report_id)
        if phase1_report is None:
            raise ValueError(f"phase1 report not found: {report_id}")

        # 2. 取选定 LogEntry（按 line_ids）
        all_entries = self._repo.list_log_entries(report_id)
        entries_by_id = {e.line_id: e for e in all_entries}
        selected_entries: list[LogEntry] = []
        for lid in line_ids:
            if lid not in entries_by_id:
                raise ValueError(
                    f"line_id {lid} not found in report {report_id}"
                )
            selected_entries.append(entries_by_id[lid])

        # 3. 对每个 entry 通过 log_message_template 重新匹配 M1 LogPoint
        match_results = self._matcher.match(selected_entries)
        log_points = [r.log_point for r in match_results if r.log_point is not None]

        # 4. 对每个 LogPoint 调 M1 get_call_context
        call_contexts = []
        for lp in log_points:
            ctx = self._m1.get_call_context(
                repo_id=phase1_report.repo_id or lp.repo_id,
                function_signature=lp.function_signature,
            )
            call_contexts.append(ctx)

        # 5. 取前次 iteration 作为 parent（AC-10 累积上下文）
        existing = self._repo.list_deep_analyses(report_id)
        # Q4 修复：父链匹配改为"有非空交集且 iteration 最大"，
        # 多候选取交集最大者（最相关）。
        # 场景：前次 [L1, L2] 本次 [L1]（子集）应继承 iteration + parent 链，
        # 铲屎官"二次/多次"深入分析最常见的是"上次多行 → 这次一行"。
        # 边界：完全不相交 → 新链 iteration=1。
        parent_record: DeepAnalysisRecord | None = None
        if existing:
            target_line_set = set(line_ids)
            # 候选 = 有非空交集的前次 record
            candidates_with_overlap = [
                (r, len(set(r.line_ids) & target_line_set))
                for r in existing
                if set(r.line_ids) & target_line_set
            ]
            if candidates_with_overlap:
                # 多候选取交集最大者；并列时取 iteration 最大者
                candidates_with_overlap.sort(
                    key=lambda x: (x[1], x[0].iteration),
                    reverse=True,
                )
                parent_record = candidates_with_overlap[0][0]

        # 6. DeepAnalyzer.analyze() 调 LLM
        t0 = time.perf_counter()
        record = await self._deep.analyze(
            report_id=report_id,
            entries=selected_entries,
            log_points=log_points,
            call_contexts=call_contexts,
            phase1_report=phase1_report,
            parent_record=parent_record,
        )
        elapsed = time.perf_counter() - t0

        # AC-14: LLM 调用耗时 + 成本累计 + deep_analysis counter
        if self._metrics is not None:
            self._metrics.observe_llm_call_duration(phase="phase2", seconds=elapsed)
            self._metrics.inc_llm_cost(usd=record.token_usage.total_cost_usd)
            self._metrics.inc_deep_analysis(
                repo_id=phase1_report.repo_id or "<no-repo>",
            )

        # 7. 持久化
        self._repo.save_deep_analysis(record)

        # 8. 回写 M1 LogPoint.llm_hypothesis（AC-9）
        # 用 phase1_report.repo_id（若 None，writer 内部 log_point_ids 也空，会跳过）
        self._writer.write_back(
            repo_id=phase1_report.repo_id or "",
            record=record,
        )

        # 9. AC-15: 写 audit_log
        self._audit.log(
            actor=analyzer.id,
            action=ACTION_PHASE2_DEEP_ANALYZE,
            target_repo_id=phase1_report.repo_id,
            target_log_point_ids=record.log_point_ids,
            extra={
                "report_id": report_id,
                "deep_analysis_id": record.id,
                "iteration": record.iteration,
                "parent_record_id": record.parent_record_id,
                "line_ids": line_ids,
            },
        )

        return record

    # ---- get_report ----

    def get_report(self, report_id: str) -> AnalysisReport | None:
        """查 Phase 1 报告。"""
        return self._repo.get_analysis_report(report_id)

    # ---- list_deep_analyses ----

    def list_deep_analyses(
        self, report_id: str, line_id: str | None = None,
    ) -> list[DeepAnalysisRecord]:
        """列 Phase 2 深入分析记录（可按 line 过滤，spec §四）。"""
        results = self._repo.list_deep_analyses(report_id)
        if line_id is None:
            return results
        return [r for r in results if line_id in r.line_ids]

    # ---- archive_report ----

    def archive_report(self, report_id: str, archiver: User) -> None:
        """归档报告（draft → archived，spec §四 + AC-15）。

        Raises:
            ValueError: report 不存在
        """
        # 先校验存在性
        existing = self._repo.get_analysis_report(report_id)
        if existing is None:
            raise ValueError(f"report not found: {report_id}")

        updated = self._repo.archive_report(report_id)
        if not updated:
            # 已是 archived 状态，幂等返回
            return

        # AC-15: 写 audit_log
        self._audit.log(
            actor=archiver.id,
            action=ACTION_ARCHIVE_REPORT,
            target_repo_id=existing.repo_id,
            extra={"report_id": report_id, "previous_status": existing.ingestion_status},
        )


# 协议类型（避免 M2 ↔ M1 循环 import）
from typing import Protocol  # noqa: E402


class M1ServiceProtocol(Protocol):
    """M1 RepoLogGraphService 的最小协议（仅暴露 M2 需要的方法）。"""
    def get_call_context(
        self, repo_id: str, function_signature: str,
    ) -> "CallContext": ...

    def update_log_point_hypothesis(
        self, log_point_ids: list[str], hypothesis: "LLMHypothesis", writer: str,
    ) -> int: ...


# 延迟 import 用于类型提示（避免循环）
from packages.contracts.log_point import CallContext, LLMHypothesis  # noqa: E402
