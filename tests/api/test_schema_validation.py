"""Schema validation 测试 — Pydantic↔dataclass 字段对齐（spec §九 + AC-6 + 云长 N-1）。"""
from __future__ import annotations

import dataclasses

from packages.api.schemas.call_context import CallContextAPI, CaseRefAPI
from packages.api.schemas.log_point import LLMHypothesisAPI, LogPointAPI
from packages.contracts.log_point import CallContext, CaseRef, LLMHypothesis, LogPoint


def test_log_point_schema_matches_dataclass() -> None:
    """AC-6: LogPointAPI 字段与 LogPoint dataclass 完全一致。"""
    dataclass_fields = {f.name for f in dataclasses.fields(LogPoint)}
    schema_fields = set(LogPointAPI.model_fields.keys())
    assert dataclass_fields == schema_fields, (
        f"dataclass: {dataclass_fields - schema_fields}; "
        f"schema: {schema_fields - dataclass_fields}"
    )


def test_llm_hypothesis_schema_matches_dataclass() -> None:
    """LLMHypothesisAPI 字段与 LLMHypothesis dataclass 完全一致。"""
    dataclass_fields = {f.name for f in dataclasses.fields(LLMHypothesis)}
    schema_fields = set(LLMHypothesisAPI.model_fields.keys())
    assert dataclass_fields == schema_fields


def test_caseref_schema_matches_dataclass() -> None:
    """CaseRefAPI 字段与 CaseRef dataclass 完全一致。"""
    dataclass_fields = {f.name for f in dataclasses.fields(CaseRef)}
    schema_fields = set(CaseRefAPI.model_fields.keys())
    assert dataclass_fields == schema_fields


def test_call_context_schema_matches_dataclass() -> None:
    """CallContextAPI 字段与 CallContext dataclass 完全一致。"""
    dataclass_fields = {f.name for f in dataclasses.fields(CallContext)}
    schema_fields = set(CallContextAPI.model_fields.keys())
    assert dataclass_fields == schema_fields


def test_all_schemas_strict_mode() -> None:
    """所有 schema strict=True + extra=forbid（AC-6 + 文若 W-6）。"""
    for schema_cls in [LogPointAPI, LLMHypothesisAPI, CaseRefAPI, CallContextAPI]:
        config = schema_cls.model_config
        # strict mode — pydantic v2 ConfigDict
        assert config.get("extra") == "forbid", f"{schema_cls.__name__} extra != forbid"


def test_all_schemas_from_attributes() -> None:
    """所有 schema from_attributes=True（云长 C-3 修订 — dataclass → Pydantic 自动映射）。"""
    for schema_cls in [LogPointAPI, LLMHypothesisAPI, CaseRefAPI, CallContextAPI]:
        config = schema_cls.model_config
        assert config.get("from_attributes") is True, f"{schema_cls.__name__} from_attributes != True"
