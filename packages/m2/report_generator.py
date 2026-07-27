"""F002 M2 — ReportGenerator（spec §三 + AC-3/4/5/6/17）。

Phase 1 全量分析报告生成器：
  LogEntry 列表 → prompt 装配（脱敏） → LLM 调用 → JSON 解析 → AnalysisReport

设计要点：
  - AC-4 时间窗兜底：window_hours 默认 24h，超出截断 + 警告
  - AC-5 脱敏：复用 M1 LogSanitizer，所有 prompt 调用前先过 sanitize
  - AC-6 缓存：cache key 含 phase1 + log_template + model_name，TTL=86400s
  - AC-17 成本控制：max_log_lines_per_call 上限（v1 直接拒绝 + 提示，避免单次 token 爆炸）

LLM 调用 schema（Phase 1）：
  Input: 装配后的 prompt 字符串（含日志条目原文 + 模板摘要）
  Output: JSON 含 system_summary / anomaly_localization / error_correlation / token_usage
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from packages.contracts.analysis_report import (
    AnalysisReport,
    Anomaly,
    ErrorChain,
    TokenUsage,
)
from packages.contracts.enums import STATUS_DRAFT
from packages.contracts.log_entry import LogEntry
from packages.m1.log_sanitizer import LogSanitizer, generate_prompt_hash
from packages.m1.llm_hypothesis_generator import LLMClient, RedisCache


@dataclass(frozen=True)
class Phase1Config:
    """Phase 1 LLM 调用配置。"""
    model_name: str               # 便宜模型（spec AC-17）
    window_hours: int = 24        # AC-4 默认 24h
    max_log_lines_per_call: int = 200  # AC-17 单次调用上限
    cache_ttl_seconds: int = 86400  # AC-6 默认 24h


@dataclass(frozen=True)
class WindowTruncationResult:
    """AC-4 时间窗截断结果。"""
    kept: list[LogEntry]
    truncated_count: int
    warning: str


class ReportGenerator:
    """Phase 1 全量分析报告生成器（spec §三 + AC-3/4/5/6/17）。"""

    PHASE_TAG = "phase1"

    def __init__(
        self,
        llm_client: LLMClient,
        cache: RedisCache,
        sanitizer: LogSanitizer,
        config: Phase1Config,
    ) -> None:
        self._llm = llm_client
        self._cache = cache
        self._sanitizer = sanitizer
        self._config = config

    # ---- AC-4 时间窗兜底 ----

    def truncate_to_window(
        self,
        entries: list[LogEntry],
        window_end: datetime,
        window_hours: int,
    ) -> WindowTruncationResult:
        """AC-4: 截断超出时间窗的日志条目，返回截断后保留集 + 警告。

        无 timestamp 的条目（未识别格式）保留，不参与截断判断。
        """
        window_start = window_end - timedelta(hours=window_hours)
        kept: list[LogEntry] = []
        truncated = 0

        for e in entries:
            if e.timestamp is None:
                kept.append(e)
                continue
            if window_start <= e.timestamp <= window_end:
                kept.append(e)
            else:
                truncated += 1

        warning = ""
        if truncated > 0:
            warning = (
                f"window truncation: {truncated} entries outside "
                f"{window_hours}h window [{window_start.isoformat()}..{window_end.isoformat()}]"
            )

        return WindowTruncationResult(
            kept=kept, truncated_count=truncated, warning=warning,
        )

    # ---- AC-6 Redis 缓存 ----

    def _cache_key(self, entries: list[LogEntry]) -> str:
        """AC-6: cache key 含 phase1 + log_template + model_name。

        entry.line_id 不影响 key（相同模板的日志产生相同 key）。
        """
        templates = sorted({
            e.log_message_template or e.raw_text
            for e in entries
        })
        templates_str = "|".join(templates)
        h = hashlib.sha256(templates_str.encode("utf-8")).hexdigest()[:32]
        return f"m2:{self.PHASE_TAG}:model={self._config.model_name}:{h}"

    # ---- AC-5 脱敏 ----

    def _build_prompt(self, entries: list[LogEntry]) -> str:
        """装配 prompt（原文 + 模板摘要）。"""
        lines = [e.raw_text for e in entries]
        templates = sorted({
            e.log_message_template or "<unparsed>"
            for e in entries
        })
        return (
            "You are analyzing application logs to produce a system overview report.\n\n"
            f"Log entries ({len(entries)} lines):\n"
            + "\n".join(f"  [{i}] {l}" for i, l in enumerate(lines))
            + f"\n\nTemplates detected:\n"
            + "\n".join(f"  - {t}" for t in templates)
            + "\n\nReturn JSON with:\n"
            "  system_summary: str (one paragraph)\n"
            "  anomaly_localization: list of {line_ids, severity, module, summary, evidence_snippets}\n"
            "  error_correlation: list of {chain_id, line_ids_ordered, relation, summary, confidence_score}\n"
            "  token_usage: {prompt_tokens, completion_tokens, total_cost_usd}\n"
        )

    def _sanitize(self, text: str) -> str:
        """AC-5: 调 LLM 前脱敏。"""
        sanitized, _hits = self._sanitizer.sanitize(text)
        return sanitized

    # ---- AC-3 主流程 ----

    async def generate(
        self,
        entries: list[LogEntry],
        log_source: str,
        repo_id: str | None = None,
        window_end: datetime | None = None,
    ) -> AnalysisReport:
        """生成 Phase 1 全量分析报告。

        Args:
            entries: LogParser 解析出的 LogEntry 列表
            log_source: 日志来源标识（文件名 / M3 流标识）
            repo_id: 关联代码仓 id（无 LogPoint 匹配时为 None）
            window_end: 时间窗终点（默认 now）

        Returns:
            AnalysisReport dataclass（持久化由调用方负责）
        """
        # AC-17: 单次调用上限检查
        if len(entries) > self._config.max_log_lines_per_call:
            raise ValueError(
                f"entries count {len(entries)} exceeds max_log_lines_per_call "
                f"{self._config.max_log_lines_per_call}; "
                f"split into batches or use Phase 2 deep_analyze for targeted analysis"
            )

        # AC-4: 时间窗兜底（默认 24h）
        we = window_end or datetime.now(UTC)
        trunc = self.truncate_to_window(
            entries, window_end=we, window_hours=self._config.window_hours,
        )
        analyzed_entries = trunc.kept

        # AC-6: 缓存命中检查
        cache_key = self._cache_key(analyzed_entries)
        cached = self._cache.get(cache_key)
        if cached is not None:
            payload = json.loads(cached)
        else:
            # AC-5: 脱敏 → LLM 调用
            prompt = self._sanitize(self._build_prompt(analyzed_entries))
            raw = await self._llm.complete(prompt)
            payload = json.loads(raw)
            self._cache.set(cache_key, raw, ttl_seconds=self._config.cache_ttl_seconds)

        # 解析三类信息
        anomalies = [
            Anomaly(
                line_ids=a["line_ids"], severity=a["severity"],
                module=a["module"], summary=a["summary"],
                evidence_snippets=a["evidence_snippets"],
            )
            for a in payload.get("anomaly_localization", [])
        ]
        error_chains = [
            ErrorChain(
                chain_id=ec["chain_id"], line_ids_ordered=ec["line_ids_ordered"],
                relation=ec["relation"], summary=ec["summary"],
                confidence_score=ec["confidence_score"],
            )
            for ec in payload.get("error_correlation", [])
        ]
        tu = payload.get("token_usage", {})
        token_usage = TokenUsage(
            prompt_tokens=tu.get("prompt_tokens", 0),
            completion_tokens=tu.get("completion_tokens", 0),
            total_cost_usd=tu.get("total_cost_usd", 0.0),
        )

        # 计算 window_start/end
        timestamps = [e.timestamp for e in analyzed_entries if e.timestamp is not None]
        window_start = min(timestamps) if timestamps else None
        window_end_final = max(timestamps) if timestamps else None

        # prompt_hash（用于版本追溯，spec §三 AnalysisReport.prompt_hash）
        prompt_hash = generate_prompt_hash(self._build_prompt(analyzed_entries))

        return AnalysisReport(
            id=f"rpt-{uuid.uuid4().hex[:12]}",
            repo_id=repo_id,
            log_source=log_source,
            log_line_count=len(analyzed_entries),
            window_start=window_start,
            window_end=window_end_final,
            model_name=self._config.model_name,
            prompt_hash=prompt_hash,
            system_summary=payload.get("system_summary", ""),
            anomaly_localization=anomalies,
            error_correlation=error_chains,
            generated_at=datetime.now(UTC),
            duration_seconds=0.0,  # 由 service 层包装计时
            token_usage=token_usage,
            ingestion_status=STATUS_DRAFT,
        )
