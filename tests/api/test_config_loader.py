"""Config loader 测试 — ApiConfig 段加载（spec §七）。"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from packages.m1.config_loader import ApiConfig, load_config


@pytest.fixture()
def config_yaml() -> pathlib.Path:
    """临时 config.yaml，含 api 段。"""
    content = """
llm:
  api_key: test-key
  model_name: gpt-4
  endpoint: https://api.openai.com/v1
  timeout_seconds: 30
  max_retries: 3
  batch_size: 20
storage:
  postgres_dsn: postgresql://localhost/codefly
  redis_port: 6398
  redis_namespace: codefly-m1
extraction:
  top_n_candidates: 50
  include_print: false
  ingest_timeout_minutes: 30
  candidate_ttl_days: 30
  extractor_version: "1.0.0"
sanitizer:
  enabled: true
  patterns: [api_key]
  replacement: "[R]"
metrics:
  enabled: true
  endpoint: /metrics
  port: 9464
api:
  host: 127.0.0.1
  port: 8000
  enable_auth: false
  cors_origins: ["http://localhost:3003"]
"""
    p = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
    p.write_text(content, encoding="utf-8")
    yield p
    p.unlink(missing_ok=True)


def test_api_config_loaded(config_yaml: pathlib.Path) -> None:
    """load_config 返回 Config 含 api 段。"""
    config = load_config(config_yaml)
    assert isinstance(config.api, ApiConfig)
    assert config.api.port == 8000  # v1.1 修正：避开 CatCafe runtime 3003/3004
    assert config.api.host == "127.0.0.1"
    assert config.api.enable_auth is False
    assert "http://localhost:3003" in config.api.cors_origins


def test_api_config_defaults_when_missing(config_yaml: pathlib.Path) -> None:
    """config.yaml 缺 api 段时用默认值。"""
    # 改写 yaml 去掉 api 段
    content = config_yaml.read_text(encoding="utf-8").replace(
        "api:\n  host: 127.0.0.1\n  port: 8000\n  enable_auth: false\n  cors_origins: [\"http://localhost:3003\"]\n",
        "",
    )
    config_yaml.write_text(content, encoding="utf-8")
    config = load_config(config_yaml)
    # 默认值（v1.1 修正：避开 CatCafe runtime 自留地 3003/3004，默认 8000）
    assert config.api.port == 8000
    assert config.api.host == "127.0.0.1"
    assert config.api.enable_auth is False


def test_api_env_override(config_yaml: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CODEFLY_API_PORT 环境变量覆盖 config。"""
    monkeypatch.setenv("CODEFLY_API_PORT", "4004")
    monkeypatch.setenv("CODEFLY_API_HOST", "0.0.0.0")
    config = load_config(config_yaml)
    assert config.api.port == 4004
    assert config.api.host == "0.0.0.0"
