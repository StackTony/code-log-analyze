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
class ApiConfig:
    """F001.1 — HTTP 服务层配置（spec §七）。

    端口避开 CatCafe runtime 自留地 3003/3004（家规铁律：外部项目禁占）。
    选 8000 = FastAPI/uvicorn 社区默认，便于 dev 切换。
    """
    host: str = "127.0.0.1"
    port: int = 8000  # 避开 CatCafe runtime 3003/3004（家规铁律方向修正）
    enable_auth: bool = False  # F001.1 dev-only
    cors_origins: tuple[str, ...] = ("http://localhost:3003",)  # F003 前端


@dataclasses.dataclass(frozen=True)
class M2Config:
    """F002 M2 — 离线 LLM 分析模块配置（spec §七）。

    两阶段 LLM 调用的关键参数：
      - phase1_model: 便宜模型（spec AC-17 成本控制）
      - phase2_model: 强模型（spec AC-7/8 深入分析）
      - phase1_window_hours: 时间窗兜底（spec AC-4 默认 24h）
      - phase1_batch_size: Phase 1 单次 LLM 调用日志行数上限
        （spec AC-17 max_log_lines_per_call）
      - phase2_max_iterations: Phase 2 同 line 累积上下文上限
        （spec AC-11 默认 5）
      - cache_ttl_days: LLM 调用缓存 TTL（spec AC-6 默认 30 天）
      - enable_log_sanitizer: 是否启用日志脱敏（spec AC-5 复用 M1 LogSanitizer）
    """
    phase1_model: str = "gpt-4o-mini"
    phase2_model: str = "gpt-4"
    phase1_window_hours: int = 24
    phase1_batch_size: int = 200
    phase2_max_iterations: int = 5
    cache_ttl_days: int = 30
    enable_log_sanitizer: bool = True


@dataclasses.dataclass(frozen=True)
class Config:
    llm: LLMConfig
    storage: StorageConfig
    extraction: ExtractionConfig
    sanitizer: SanitizerConfig
    metrics: MetricsConfig
    api: ApiConfig = dataclasses.field(default_factory=ApiConfig)  # F001.1 新增
    m2: M2Config = dataclasses.field(default_factory=M2Config)  # F002 新增


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
        "CODEFLY_API_HOST": ("api", "host"),
        "CODEFLY_API_PORT": ("api", "port"),
        "CODEFLY_API_ENABLE_AUTH": ("api", "enable_auth"),
        "CODEFLY_API_CORS_ORIGINS": ("api", "cors_origins"),
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

    # api 段（缺失时用默认值）
    api_dict = expanded.get("api", {})
    # cors_origins 可能是 list（YAML）或 str（env，逗号分隔）
    cors = api_dict.get("cors_origins", ["http://localhost:3003"])
    if isinstance(cors, str):
        cors = tuple(c.strip() for c in cors.split(",") if c.strip())
    else:
        cors = tuple(cors)

    # enable_auth 可能是 bool 或 str（env）
    enable_auth = api_dict.get("enable_auth", False)
    if isinstance(enable_auth, str):
        enable_auth = enable_auth.lower() in ("true", "1", "yes")
    port = int(api_dict.get("port", 8000))  # 避开 CatCafe runtime 3003/3004（家规铁律方向修正）

    # m2 段（缺失时用默认值 — spec §七）
    m2_dict = expanded.get("m2", {})

    return Config(
        llm=LLMConfig(**expanded["llm"]),
        storage=StorageConfig(**expanded["storage"]),
        extraction=ExtractionConfig(**expanded["extraction"]),
        sanitizer=SanitizerConfig(**expanded["sanitizer"]),
        metrics=MetricsConfig(**expanded["metrics"]),
        api=ApiConfig(
            host=api_dict.get("host", "127.0.0.1"),
            port=port,
            enable_auth=enable_auth,
            cors_origins=cors,
        ),
        m2=M2Config(
            phase1_model=m2_dict.get("phase1_model", "gpt-4o-mini"),
            phase2_model=m2_dict.get("phase2_model", "gpt-4"),
            phase1_window_hours=int(m2_dict.get("phase1_window_hours", 24)),
            phase1_batch_size=int(m2_dict.get("phase1_batch_size", 200)),
            phase2_max_iterations=int(m2_dict.get("phase2_max_iterations", 5)),
            cache_ttl_days=int(m2_dict.get("cache_ttl_days", 30)),
            enable_log_sanitizer=bool(m2_dict.get("enable_log_sanitizer", True)),
        ),
    )
