"""Deps 测试 — get_session / get_service（spec §五 + 云长 I-1）。"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import packages.api.deps as deps_mod
from packages.m1.storage.models import Base


def _setup_test_engine() -> None:
    """override 全局 engine + SessionLocal with in-memory SQLite。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    deps_mod._engine = engine
    deps_mod.SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_get_session_yields_session() -> None:
    _setup_test_engine()
    gen = deps_mod.get_session()
    session = next(gen)
    assert isinstance(session, Session)
    try:
        next(gen)
    except StopIteration:
        pass


def test_get_session_closes_after_yield() -> None:
    _setup_test_engine()
    gen = deps_mod.get_session()
    session = next(gen)
    try:
        next(gen)
    except StopIteration:
        pass
    assert session.in_transaction() is False
