"""Config 加载 — 环境变量 > config.local.yaml > config.yaml。"""
from __future__ import annotations

import dataclasses
import os
import pathlib
import re
from typing import Any

import yaml

# 铁律：Cat Cafe 生产 Redis 6399 不可碰
FORBIDDEN_REDIS_PORT = 6399
_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


@dataclasses.dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model_name: str
    endpoint: str
    timeout_seconds: int = 30
    max_retries: int = 3
    batch_size: int = 20


@dataclasses.dataclass(frozen=True)
class StorageConfig:
    postgres_dsn: str
    redis_port: int
    redis_namespace: str


@dataclasses.dataclass(frozen=True)
class ExtractionConfig:
    top_n_candidates: int
    include_print: bool
    ingest_timeout_minutes: int
    candidate_ttl_days: int
    extractor_version: str


@dataclasses.dataclass(frozen=True)
class SanitizerConfig:
    enabled: bool
    patterns: list[str]
    replacement: str


@dataclasses.dataclass(frozen=True)
class MetricsConfig:
    enabled: bool
    endpoint: str
    port: int


@dataclasses.dataclass(frozen=True)
class Config:
    llm: LLMConfig
    storage: StorageConfig
    extraction: ExtractionConfig
    sanitizer: SanitizerConfig
    metrics: MetricsConfig


def _expand_env(value: Any) -> Any:
    """递归展开 ${VAR} 引用为环境变量值。"""
    if isinstance(value, str):
        def _replacer(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), m.group(0))

        return _ENV_PATTERN.sub(_replacer, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _env_override(config_dict: dict[str, Any]) -> dict[str, Any]:
    """环境变量 CODEFLY_* 覆盖 config 字段（扁平键映射）。"""
    env_map = {
        "CODEFLY_LLM_API_KEY": ("llm", "api_key"),
        "CODEFLY_PG_DSN": ("storage", "postgres_dsn"),
    }
    for env_key, (section, field) in env_map.items():
        val = os.environ.get(env_key)
        if val:
            config_dict.setdefault(section, {})[field] = val
    return config_dict


def load_config(path: pathlib.Path | None = None) -> Config:
    """加载 config：env > config.local.yaml > config.yaml。"""
    if path is None:
        local = pathlib.Path("config.local.yaml")
        path = local if local.exists() else pathlib.Path("config.example.yaml")

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    expanded = _expand_env(raw)
    expanded = _env_override(expanded)

    # 铁律：6399 是 Cat Cafe 生产 Redis
    redis_port = expanded.get("storage", {}).get("redis_port")
    if redis_port == FORBIDDEN_REDIS_PORT:
        raise ValueError(
            f"redis_port={FORBIDDEN_REDIS_PORT} 禁止使用 — Cat Cafe production Redis"
        )

    return Config(
        llm=LLMConfig(**expanded["llm"]),
        storage=StorageConfig(**expanded["storage"]),
        extraction=ExtractionConfig(**expanded["extraction"]),
        sanitizer=SanitizerConfig(**expanded["sanitizer"]),
        metrics=MetricsConfig(**expanded["metrics"]),
    )
