"""Config 加载测试。"""
from __future__ import annotations

import pathlib

import pytest

from packages.m1.config_loader import load_config


def test_load_config_from_yaml(tmp_path: pathlib.Path) -> None:
    yaml_file = tmp_path / "config.local.yaml"
    yaml_file.write_text(
        """
llm:
  api_key: test-key
  model_name: gpt-4-test
  endpoint: https://api.test.com/v1
  timeout_seconds: 10
  max_retries: 2
  batch_size: 5
storage:
  postgres_dsn: postgresql://test:test@localhost/test
  redis_port: 6398
  redis_namespace: codefly-m1-test
extraction:
  top_n_candidates: 10
  include_print: true
  ingest_timeout_minutes: 5
  candidate_ttl_days: 7
  extractor_version: "1.0.0"
sanitizer:
  enabled: true
  patterns: [api_key, password, token, ipv4, ipv6, email]
  replacement: "[REDACTED_{kind}]"
metrics:
  enabled: true
  endpoint: /metrics
  port: 9101
""",
        encoding="utf-8",
    )

    config = load_config(yaml_file)

    assert config.llm.api_key == "test-key"
    assert config.llm.model_name == "gpt-4-test"
    assert config.storage.redis_port == 6398  # 铁律：不碰 6399
    assert config.extraction.top_n_candidates == 10
    assert config.sanitizer.enabled is True
    assert config.metrics.port == 9101


def test_env_var_overrides_yaml(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_file = tmp_path / "config.local.yaml"
    yaml_file.write_text(
        """
llm:
  api_key: yaml-key
  model_name: gpt-4-test
  endpoint: https://api.test.com/v1
storage:
  postgres_dsn: postgresql://test:test@localhost/test
  redis_port: 6398
  redis_namespace: codefly-m1-test
extraction:
  top_n_candidates: 50
  include_print: false
  ingest_timeout_minutes: 30
  candidate_ttl_days: 30
  extractor_version: "1.0.0"
sanitizer:
  enabled: true
  patterns: [api_key]
  replacement: "[REDACTED_{kind}]"
metrics:
  enabled: true
  endpoint: /metrics
  port: 9464
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("CODEFLY_LLM_API_KEY", "env-key-override")

    config = load_config(yaml_file)

    # 环境变量应覆盖 yaml
    assert config.llm.api_key == "env-key-override"


def test_redis_port_6399_forbidden(tmp_path: pathlib.Path) -> None:
    yaml_file = tmp_path / "config.local.yaml"
    yaml_file.write_text(
        """
llm: {api_key: k, model_name: m, endpoint: e}
storage: {postgres_dsn: dsn, redis_port: 6399, redis_namespace: ns}
extraction: {top_n_candidates: 50, include_print: false, ingest_timeout_minutes: 30, candidate_ttl_days: 30, extractor_version: "1.0.0"}
sanitizer: {enabled: true, patterns: [api_key], replacement: "[REDACTED_{kind}]"}
metrics: {enabled: true, endpoint: /metrics, port: 9464}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"6399.*Cat Cafe.*production"):
        load_config(yaml_file)
