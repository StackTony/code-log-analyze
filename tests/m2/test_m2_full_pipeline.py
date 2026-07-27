"""F002 M2 — AC-19 端到端 fixture 测试。

spec §五文件结构：
    tests/m2/test_m2_full_pipeline.py # 端到端：Phase 1 + Phase 2 全链路

spec AC-19：
    端到端 fixture 测试：用户上传日志 → Phase 1 报告 → 选 line →
    Phase 2 深入分析 → 验证 M1 LogPoint.llm_hypothesis 被回写

与单元测试的区别：
  - 单元测试用 m1_service=MagicMock 验证 service 调用契约
  - 本测试用真实 RepoLogGraphService（含真实 update_log_point_hypothesis
    DB UPDATE），验证 LogPointModel.llm_hypothesis_json 在 DB 真改写

红测试理由（赛前已知会失败）：
  - 当前无文件 → ImportError
  - 这是 spec §五明示文件结构要求，AC-19 验收必须项
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.log_entry import LogSource
from packages.m1.audit_log import AuditLogger
from packages.m1.config_loader import Config, LLMConfig, SanitizerConfig as M1SanitizerConfig
from packages.m1.llm_hypothesis_generator import LLMClient
from packages.m1.log_sanitizer import LogSanitizer
from packages.m1.log_sanitizer import SanitizerConfig as LogSanitizerConfig
from packages.m1.repo_log_graph_service import RepoLogGraphService
from packages.m1.storage.models import Base, LogPointModel
from packages.m1.tree_sitter_parser import TreeSitterParser
from packages.m1.unit_a_repo_registrar import User
from packages.m2.deep_analyzer import DeepAnalyzer, Phase2Config
from packages.m2.hypothesis_writer import HypothesisWriter
from packages.m2.log_analysis_service import LogAnalysisService
from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher
from packages.m2.report_generator import Phase1Config, ReportGenerator
from packages.m2.storage.repository import M2Repository
from packages.m2.storage_backed_log_point_index import (
    LogPointIndexFactory,
    StorageBackedLogPointIndex,
)


# ---- Shared fixtures ----

@pytest.fixture()
def session():
    """In-memory SQLite + M1+M2 全表建好。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    # M2 三张表
    from packages.m2.storage.models import (  # type: ignore[import-not-found]
        Base as M2Base,
    )
    M2Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture()
def audit(session: Session) -> AuditLogger:
    return AuditLogger(session)


@pytest.fixture()
def cache() -> MagicMock:
    """Redis cache mock（cache miss 走 LLM 路径）。"""
    from packages.m1.llm_hypothesis_generator import RedisCache
    c = MagicMock(spec=RedisCache)
    c.get.return_value = None
    return c


@pytest.fixture()
def sanitizer() -> LogSanitizer:
    return LogSanitizer(LogSanitizerConfig(
        enabled=True, patterns=["api_key", "password", "token"],
        replacement="[REDACTED_{kind}]",
    ))


@pytest.fixture()
def llm_phase1() -> AsyncMock:
    """Phase 1 LLM mock — 返回三类信息 JSON。"""
    client = AsyncMock(spec=LLMClient)
    client.complete.return_value = json.dumps({
        "system_summary": "auth module had repeated login failures",
        "anomaly_localization": [{
            "line_ids": ["__placeholder__"],  # 由测试动态替换
            "severity": "error",
            "module": "auth",
            "summary": "User 12345 login loop",
            "evidence_snippets": ["User 12345 logged in"],
        }],
        "error_correlation": [{
            "chain_id": "c1",
            "line_ids_ordered": ["__placeholder__"],
            "relation": "causal",
            "summary": "auth failures",
            "confidence_score": 0.8,
        }],
        "token_usage": {
            "prompt_tokens": 100, "completion_tokens": 50,
            "total_cost_usd": 0.02,
        },
    })
    return client


@pytest.fixture()
def llm_phase2() -> AsyncMock:
    """Phase 2 LLM mock — 返回 root_cause + fix_suggestion JSON。"""
    client = AsyncMock(spec=LLMClient)
    client.complete.return_value = json.dumps({
        "root_cause_hypothesis": "session pool exhausted under high load",
        "fix_suggestion": "increase pool size + add retry",
        "related_evidence": [],
        "token_usage": {
            "prompt_tokens": 200, "completion_tokens": 100,
            "total_cost_usd": 0.05,
        },
    })
    return client


@pytest.fixture()
def m1_log_point(session: Session) -> LogPointModel:
    """M1 主表预置一条 confirmed LogPoint（模板与 M2 日志一致）。

    M1 提取侧用真实变量名 "User {uid} logged in"。
    M2 LogParser 会从 "User 12345 logged in" 提取 "User {var_0} logged in"。
    归一化后两侧都是 "User {x} logged in" → 哈希匹配。
    """
    now = datetime.now(UTC)
    row = LogPointModel(
        id="lp-e2e-1",
        repo_id="repo-e2e",
        git_commit_sha="abc123",
        extractor_version="v1",
        file_path="app/auth.py",
        function_signature="def login()",
        line_start=42,
        line_end=42,
        language="python",
        log_level="INFO",
        log_message_template="User {uid} logged in",
        log_message_variables=["uid"],
        framework_hint="logging",
        confidence_score=0.95,
        enclosing_class="AuthService",
        call_chain_to_entry=["def login()"],
        enclosing_community="AuthModule",
        evidence_refs_json="[]",
        llm_hypothesis_json=None,  # 初始为空，验证 Phase 2 回写
        occurrence_count=1,
        is_top_n=True,
        ingestion_status="confirmed",
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture()
def m1_service(
    session: Session, audit: AuditLogger, cache: MagicMock,
    sanitizer: LogSanitizer,
) -> RepoLogGraphService:
    """真实 M1 RepoLogGraphService（含真实 update_log_point_hypothesis）。

    不 mock 任何 M1 方法——AC-19 要验证 DB 真改，不是 mock 调用契约。
    """
    # 构造 Config（最小可工作配置）
    config = Config(
        llm=LLMConfig(
            api_key="${CODEFLY_LLM_API_KEY}",
            model_name="gpt-4",
            endpoint="https://api.openai.com/v1",
            timeout_seconds=30,
            max_retries=3,
            batch_size=20,
        ),
        storage=MagicMock(),  # 不实际用
        extraction=MagicMock(),
        sanitizer=MagicMock(),
        metrics=MagicMock(),
        api=MagicMock(),
        m2=MagicMock(),
    )
    # GitNexus + TreeSitter 不在 AC-19 路径上（deep_analyze 不调 ingest）
    gn = MagicMock()
    gn.analyze.return_value = None
    gn.cypher.return_value = []
    gn.context.return_value = {}
    llm = AsyncMock(spec=LLMClient)
    return RepoLogGraphService(
        session=session,
        gitnexus=gn,
        llm_client=llm,
        cache=cache,
        config=config,
        tree_sitter=TreeSitterParser(),
        audit=audit,
        metrics=MagicMock(),
    )


@pytest.fixture()
def index_factory(session: Session) -> LogPointIndexFactory:
    return LogPointIndexFactory(session=session)


@pytest.fixture()
def service(
    session: Session, audit: AuditLogger, cache: MagicMock,
    llm_phase1: AsyncMock, llm_phase2: AsyncMock,
    sanitizer: LogSanitizer, m1_service: RepoLogGraphService,
    index_factory: LogPointIndexFactory,
) -> LogAnalysisService:
    """真实 LogAnalysisService — 全链路真实依赖（除 LLM 占位外）。"""
    # fallback matcher 用空 index（无 repo_id 时返回 None）；
    # service 内部 _resolve_matcher 在 repo_id 非空时用 index_factory 覆盖
    from packages.m2.log_point_matcher import NullLogPointIndex

    return LogAnalysisService(
        session=session,
        audit=audit,
        repository=M2Repository(session),
        log_parser=LogParser(),
        log_point_matcher=LogPointMatcher(NullLogPointIndex()),
        report_generator=ReportGenerator(
            llm_client=llm_phase1, cache=cache, sanitizer=sanitizer,
            config=Phase1Config(
                model_name="gpt-4o-mini", window_hours=24,
                max_log_lines_per_call=200, cache_ttl_seconds=86400,
            ),
        ),
        deep_analyzer=DeepAnalyzer(
            llm_client=llm_phase2, cache=cache, sanitizer=sanitizer,
            config=Phase2Config(
                model_name="gpt-4", max_iterations=5,
                cache_ttl_seconds=86400,
            ),
        ),
        hypothesis_writer=HypothesisWriter(m1_service=m1_service),
        m1_service=m1_service,
        index_factory=index_factory,
    )


# ---- AC-19 端到端测试 ----

class TestAC19FullPipeline:
    """AC-19: 用户上传日志 → Phase 1 → 选 line → Phase 2 → M1 回写。"""

    async def test_full_pipeline_writes_back_m1_llm_hypothesis(
        self,
        session: Session,
        service: LogAnalysisService,
        m1_log_point: LogPointModel,
        llm_phase1: AsyncMock,
        analyzer: User = User(id="u-e2e", name="alice"),
    ) -> None:
        """完整端到端：上传日志 → Phase 1 → 选 line → Phase 2 → 验证 M1 DB 改写。"""
        # ---- 比赛前置断言：M1 LogPoint.llm_hypothesis_json 初始为空 ----
        assert m1_log_point.llm_hypothesis_json is None

        # ---- Phase 1: 上传日志 → 生成报告 ----
        log_text = "2026-07-27 08:30:00,123 INFO User 12345 logged in"
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=analyzer,
            repo_id="repo-e2e",
        )
        # Phase 1 报告落地
        assert report.id is not None
        assert report.system_summary == "auth module had repeated login failures"

        # 拿 LogEntry.line_id（用于 Phase 2 选 line）
        entries = service._repo.list_log_entries(report.id)  # type: ignore[attr-defined]
        assert len(entries) == 1
        line_id = entries[0].line_id

        # 动态调整 Phase 1 LLM mock 的 anomaly line_ids（line_id 是生成时分配的）
        # —— 实际 mock 已写死 "__placeholder__"，但 Phase 2 不依赖 anomaly_localization
        # 的 line_ids 字段，所以这里不修 mock。

        # ---- Phase 2: 选 line → deep_analyze ----
        record = await service.deep_analyze(
            report_id=report.id,
            line_ids=[line_id],
            analyzer=analyzer,
        )

        # Phase 2 record 落地
        assert record.id is not None
        assert record.iteration == 1
        assert record.root_cause_hypothesis == "session pool exhausted under high load"
        # log_point_ids 含真实 M1 LogPoint id（经归一化哈希匹配到 m1_log_point）
        assert "lp-e2e-1" in record.log_point_ids

        # ---- 端到端关键断言：M1 LogPoint.llm_hypothesis_json DB 真改写 ----
        # 重新从 DB 拉一次，避免 ORM session 缓存干扰
        session.expire_all()
        row = session.get(LogPointModel, "lp-e2e-1")
        assert row is not None, "M1 LogPoint 行应该存在"
        assert row.llm_hypothesis_json is not None, (
            "AC-19：Phase 2 deep_analyze 完成后，M1 LogPoint.llm_hypothesis_json "
            "必须被回写（DB 真改，不是 mock 调用契约）"
        )

        # 回写内容应该是 DeepAnalysisRecord → LLMHypothesis 映射后的 JSON
        written = json.loads(row.llm_hypothesis_json)
        # HypothesisWriter 字段映射规则（hypothesis_writer.py §字段映射）：
        #   root_cause_hypothesis → summary
        #   fix_suggestion        → suggested_check
        assert written["summary"] == "session pool exhausted under high load"
        assert written["suggested_check"] == "increase pool size + add retry"
        assert written["model_name"] == "gpt-4"  # Phase2Config.model_name
        assert written["error_kind"] == "unknown"  # DeepAnalysisRecord 无等价字段

        # last_seen_at 应被 update_log_point_hypothesis 更新为 hypothesis.generated_at。
        # SQLite 不存 tz 信息，比较到秒级（核心断言是 llm_hypothesis_json 真改写，
        # last_seen_at 是附带字段，弱比较到秒级即可）。
        naive_generated = record.generated_at.replace(tzinfo=None)
        assert row.last_seen_at.replace(microsecond=0) == \
            naive_generated.replace(microsecond=0)
