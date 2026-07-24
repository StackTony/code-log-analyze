"""集成测试：RepoRegistrar.ingest 串联 Unit A → B → C。"""
from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.m1.storage.models import Base
from packages.m1.unit_a_repo_registrar import RepoRegistrar, RepoSource, User


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def test_ingest_runs_full_pipeline(
    session: Session, fixtures_dir: pathlib.Path
) -> None:
    gn = MagicMock()
    gn.analyze.return_value = None
    gn.cypher.return_value = []
    gn.context.return_value = {}

    llm = AsyncMock()
    import json
    llm.complete.return_value = json.dumps({
        "summary": "test", "possible_causes": [], "error_kind": "unknown",
        "suggested_check": None,
    })

    cache = MagicMock()
    cache.get.return_value = None

    sanitizer = MagicMock()
    sanitizer.sanitize.return_value = ("text", {})

    from packages.m1.llm_hypothesis_generator import LLMHypothesisGenerator
    from packages.m1.log_sanitizer import LogSanitizer, SanitizerConfig
    from packages.m1.tree_sitter_parser import TreeSitterParser
    from packages.m1.unit_b_log_point_finder import LogPointFinder

    gen = LLMHypothesisGenerator(
        llm_client=llm, cache=cache,
        model_name="gpt-4", extractor_version="1.0.0",
        sanitizer=LogSanitizer(SanitizerConfig(enabled=False, patterns=[], replacement="")),
    )
    finder = LogPointFinder(gitnexus=gn, tree_sitter=TreeSitterParser())

    registrar = RepoRegistrar(
        gitnexus=gn, session=session,
        finder=finder, llm_generator=gen,
    )

    repo_id = registrar.ingest(
        RepoSource(local_path=str(fixtures_dir / "python_logging_repo")),
        User(id="user-1", name="alice"),
    )
    assert repo_id.startswith("repo-")
