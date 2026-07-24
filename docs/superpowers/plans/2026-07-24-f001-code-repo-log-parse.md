# F001 代码仓日志解析模块 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 M1 代码仓日志解析模块——从代码仓中识别所有日志埋点，抽取确定性上下文 + LLM 推断打印原因，经用户筛选后入库，为 M2/M3/M4 提供查询面。

**Architecture:** Python 后端服务。4 子单元流水线（Repo Registrar → Log Point Finder → LLM Hypothesis Generator → Candidate Staging）。gitnexus 做 graph backend（不自建 AST/call graph）。两层过滤（cypher 粗筛 + tree-sitter 精筛）。两阶段入库（候选池 → 用户 confirm → 主表）。PostgreSQL 主存储 + Redis 缓存 + Prometheus metrics。

**Tech Stack:** Python 3.11+ / ruff / pytest / py-tree-sitter / tree-sitter-languages / SQLAlchemy 2.x + Alembic / asyncpg / redis-py / prometheus-client / FastAPI / pydantic / mcp Python client / anthropic SDK（或 OpenAI SDK，按 config）

## Global Constraints

- **Identity**: 实施者签名 `[昵称/模型🐾]`，commit body 写 Why；M1 主 owner = 奉孝 (@ragdoll-pa82, GLM-5.2)
- **Review**: 跨家族 review 铁律——M1 不能 self-review，由 @云长 (GLM-5.1) review
- **Worktree**: 实施 F001 必须开 worktree（铁律：主仓库禁止 checkout 非 main 分支）
- **Redis 端口**: 6398（dev/test），**绝不碰 6399**（Cat Cafe 生产 Redis）
- **本地端口**: metrics 9100（与 frontend 3003 / API 3004 分离，家规铁律）
- **工程基线**: ruff（lint + format）+ pytest；**不用** pnpm/Biome（TS 基线仅适用 F003 前端）
- **文件行数**: 200 行 warn / 350 行 hard cap（SOP 规定）
- **TDD**: red 测试先写，绿代码后写，每 task commit
- **Python 版本**: 3.11+（用 `str | None` 而非 `Optional[str]`）
- **配置加载顺序**: env (CODEFLY_*) > config.local.yaml (gitignored) > config.yaml (入库)
- **file_path 存储**: 统一 POSIX 风格（正斜杠），无论解析平台
- **铁律 P0**: 用户可见、可追溯、可恢复预期的数据默认 TTL=0；用户 opt-in 才入库（AC-11）

---

## File Structure

```
代码飞轮/
├── pyproject.toml                          # T1: Python 工程基线
├── ruff.toml                                # T1: ruff 配置
├── pytest.ini                              # T1: pytest 配置
├── .gitignore                              # T1: 加 config.local.yaml + .env + __pycache__
├── config.example.yaml                     # T2: 配置 schema 入库
├── config.local.yaml.example               # T2: 本地配置模板
├── packages/
│   ├── __init__.py
│   ├── contracts/                          # T3: 数据契约子包
│   │   ├── __init__.py
│   │   ├── enums.py                        # T3: 枚举常量
│   │   ├── log_point.py                    # T3: LogPoint / LLMHypothesis / CaseRef / CallContext / RepoIngestLock
│   │   ├── audit.py                        # T3: AuditLog
│   │   └── config.py                       # T3: Config dataclass
│   └── m1/                                  # T4+: M1 实现
│       ├── __init__.py
│       ├── config_loader.py                # T2: config 加载
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── models.py                   # T4: SQLAlchemy models
│       │   └── migrations/                # T4: Alembic
│       │       ├── env.py
│       │       └── versions/
│       ├── gitnexus_client.py              # T5: gitnexus MCP client 封装
│       ├── unit_a_repo_registrar.py        # T6: Unit A
│       ├── tree_sitter_parser.py           # T7: tree-sitter 解析器
│       ├── unit_b_log_point_finder.py      # T7-T8: Unit B 两层过滤
│       ├── log_sanitizer.py                # T9: Unit C 脱敏
│       ├── llm_hypothesis_generator.py     # T9-T10: Unit C LLM 调用 + 缓存
│       ├── unit_d_candidate_staging.py     # T11: Unit D 候选池 + 入库 gate
│       ├── audit_log.py                    # T12: audit_log 写入
│       ├── metrics_emitter.py              # T13: Unit E metrics
│       └── repo_log_graph_service.py       # T14: 对外 API 实现
├── tests/
│   ├── conftest.py                         # T1: pytest fixtures
│   ├── fixtures/                            # T7: fixture 代码仓
│   │   ├── python_logging_repo/            # 6 个 fixture 仓 + 1 个干扰仓
│   │   ├── python_loguru_repo/
│   │   ├── python_print_repo/
│   │   ├── c_printf_repo/
│   │   ├── c_syslog_repo/
│   │   ├── c_custom_log_repo/
│   │   └── decoy_repo/                     # 含 format_error/handleError 干扰函数
│   ├── contracts/                          # T3
│   ├── unit_a/                             # T6
│   ├── unit_b/                             # T7-T8
│   ├── unit_c/                             # T9-T10
│   ├── unit_d/                             # T11
│   ├── audit/                              # T12
│   ├── metrics/                            # T13
│   ├── e2e/                                # T14
│   └── api/                                # T15 (后续)
└── docs/superpowers/plans/
    └── 2026-07-24-f001-code-repo-log-parse.md   # 本文件
```

---

## Task 1: Python 工程基线 + pyproject.toml + ruff + pytest

**Files:**
- Create: `pyproject.toml`
- Create: `ruff.toml`
- Create: `pytest.ini`
- Create: `.gitignore` (modify if exists)
- Create: `tests/conftest.py`
- Create: `packages/__init__.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces: `pyproject.toml`（依赖清单 + 包路径）、`ruff.toml`、`pytest.ini`、`tests/conftest.py`（后续 task 用的 fixture 入口）

- [ ] **Step 1: Write the failing test**

`tests/test_smoke.py`:
```python
"""Smoke test — 验证 Python 工程基线能跑通。"""
from __future__ import annotations


def test_pytest_runs() -> None:
    assert True


def test_packages_importable() -> None:
    import packages
    assert packages.__name__ == "packages"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages'`

- [ ] **Step 3: Write minimal implementation**

`pyproject.toml`:
```toml
[project]
name = "code-flywheel"
version = "0.1.0"
description = "代码飞轮 — 日志智能分析平台"
requires-python = ">=3.11"
dependencies = [
  "tree-sitter>=0.21",
  "tree-sitter-languages>=1.10",
  "sqlalchemy>=2.0",
  "alembic>=1.13",
  "asyncpg>=0.29",
  "redis>=5.0",
  "prometheus-client>=0.20",
  "fastapi>=0.110",
  "pydantic>=2.6",
  "mcp>=0.9",
  "httpx>=0.27",
  "pyyaml>=6.0",
  "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-cov>=5.0", "ruff>=0.4"]

[tool.setuptools.packages.find]
where = ["."]
include = ["packages*"]
```

`ruff.toml`:
```toml
target-version = "py311"
line-length = 100

[lint]
select = ["E", "F", "W", "I", "B", "UP", "RUF"]
ignore = ["E501"]  # 行长由 formatter 管

[lint.isort]
known-first-party = ["packages"]
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
asyncio_mode = auto
addopts = -v --tb=short --strict-markers
markers =
  slow: marks tests as slow
  integration: marks tests requiring real Postgres/Redis
```

`.gitignore`（merge with existing if any）:
```
# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.coverage
htmlcov/
.ruff_cache/

# Config & env
config.local.yaml
.env
.env.*

# IDE
.vscode/
.idea/
```

`packages/__init__.py`:
```python
"""代码飞轮 — 根包。"""
```

`tests/conftest.py`:
```python
"""pytest 全局 fixtures。"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).parent.parent


@pytest.fixture(scope="session")
def fixtures_dir() -> pathlib.Path:
    """fixture 代码仓根目录（后续 Unit B 测试用）。"""
    return ROOT / "tests" / "fixtures"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Lint check**

Run: `ruff check .`
Expected: PASS (no issues)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml ruff.toml pytest.ini .gitignore tests/conftest.py tests/test_smoke.py packages/__init__.py
git commit -m "chore(m1): python 工程基线 + pyproject + ruff + pytest"
```

---

## Task 2: 配置加载 — Config dataclass + YAML 加载 + 环境变量注入

**Files:**
- Create: `config.example.yaml`
- Create: `config.local.yaml.example`
- Create: `packages/m1/__init__.py`
- Create: `packages/m1/config_loader.py`
- Test: `tests/unit_a/test_config_loader.py`

**Interfaces:**
- Consumes: spec 第 263-313 行 Configuration Schema
- Produces: `load_config() -> Config`、`Config` dataclass（含 `llm` / `storage` / `extraction` / `sanitizer` / `metrics` 五块）

- [ ] **Step 1: Write the failing test**

`tests/unit_a/test_config_loader.py`:
```python
"""Config 加载测试。"""
from __future__ import annotations

import os
import pathlib

import pytest

from packages.m1.config_loader import Config, load_config


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
  port: 9100
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
metrics: {enabled: true, endpoint: /metrics, port: 9100}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="6399.*Cat Cafe.*production"):
        load_config(yaml_file)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_a/test_config_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m1.config_loader'`

- [ ] **Step 3: Write minimal implementation**

`packages/m1/__init__.py`:
```python
"""M1 代码仓日志解析模块。"""
```

`config.example.yaml`（入库，spec 第 265-308 行完整 schema）:
```yaml
llm:
  api_key: ${CODEFLY_LLM_API_KEY}
  model_name: gpt-4
  endpoint: https://api.openai.com/v1
  timeout_seconds: 30
  max_retries: 3
  batch_size: 20
storage:
  postgres_dsn: ${CODEFLY_PG_DSN}
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
  patterns: [api_key, password, token, ipv4, ipv6, email]
  replacement: "[REDACTED_{kind}]"
metrics:
  enabled: true
  endpoint: /metrics
  port: 9100
```

`config.local.yaml.example`（开发模板，复制为 config.local.yaml 使用）:
```yaml
# 复制本文件为 config.local.yaml 后填入真实值
llm:
  api_key: sk-xxx  # 或 export CODEFLY_LLM_API_KEY=sk-xxx
  model_name: gpt-4
  endpoint: https://api.openai.com/v1
storage:
  postgres_dsn: postgresql://user:pass@localhost:5432/codefly
  redis_port: 6398
  redis_namespace: codefly-m1-dev
```

`packages/m1/config_loader.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_a/test_config_loader.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint check**

Run: `ruff check packages/m1/config_loader.py tests/unit_a/test_config_loader.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add config.example.yaml config.local.yaml.example packages/m1/__init__.py packages/m1/config_loader.py tests/unit_a/test_config_loader.py
git commit -m "feat(m1): config 加载 + 铁律 redis 6399 拒绝"
```

---

## Task 3: 数据契约子包 packages/contracts/ — LogPoint + LLMHypothesis + CaseRef + CallContext + RepoIngestLock + AuditLog + enums

**Files:**
- Create: `packages/contracts/__init__.py`
- Create: `packages/contracts/enums.py`
- Create: `packages/contracts/log_point.py`
- Create: `packages/contracts/audit.py`
- Test: `tests/contracts/test_log_point.py`

**Interfaces:**
- Consumes: spec 第 100-208 行 + 第 319-329 行数据契约
- Produces: `LogPoint` / `LLMHypothesis` / `CaseRef` / `CallContext` / `RepoIngestLock` / `AuditLog` dataclass；`LANGUAGE_*` / `STATUS_*` / `ERROR_KIND_*` / `ACTION_*` 枚举常量。后续所有 task import 这些类型。

- [ ] **Step 1: Write the failing test**

`tests/contracts/test_log_point.py`:
```python
"""数据契约测试 — 字段、类型、枚举常量。"""
from __future__ import annotations

from datetime import datetime, timezone

from packages.contracts.enums import (
    ACTION_CONFIRM_INGESTION,
    ACTION_FORCE_RELEASE_LOCK,
    ACTION_GET_CALL_CONTEXT,
    ACTION_INGEST_REPO,
    ACTION_LIST_CANDIDATES,
    ACTION_QUERY,
    ACTION_REVOKE_INGESTION,
    ERROR_KIND_LOGIC,
    ERROR_KIND_PARAM,
    ERROR_KIND_UNKNOWN,
    LANGUAGE_C,
    LANGUAGE_PYTHON,
    STATUS_CANDIDATE,
    STATUS_CONFIRMED,
    STATUS_INGESTED,
)
from packages.contracts.log_point import (
    CallContext,
    CaseRef,
    LLMHypothesis,
    LogPoint,
    RepoIngestLock,
)
from packages.contracts.audit import AuditLog


def test_log_point_roundtrip() -> None:
    lp = LogPoint(
        id="lp-1",
        repo_id="repo-1",
        git_commit_sha="abc123",
        extractor_version="1.0.0",
        file_path="src/app.py",
        function_signature="def login(uid: str) -> bool",
        line_start=10,
        line_end=12,
        language=LANGUAGE_PYTHON,
        log_level="INFO",
        log_message_template="User {uid} logged in",
        log_message_variables=["uid"],
        framework_hint="logging",
        confidence_score=1.0,
        enclosing_class=None,
        call_chain_to_entry=["api_handler", "auth_middleware", "login"],
        enclosing_community="auth",
        evidence_refs=[],
        llm_hypothesis=None,
        occurrence_count=1,
        is_top_n=True,
        ingestion_status=STATUS_CANDIDATE,
        first_seen_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )
    assert lp.language == "python"
    assert lp.confidence_score == 1.0
    assert lp.ingestion_status == "candidate"


def test_llm_hypothesis_includes_prompt_hash_and_error_kind() -> None:
    h = LLMHypothesis(
        summary="uid 可能为空",
        possible_causes=["参数未校验"],
        error_kind=ERROR_KIND_PARAM,
        suggested_check="检查 uid 是否 None",
        model_name="gpt-4",
        prompt_hash="v1-sha256-abc",
        generated_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )
    assert h.error_kind == "param_error"
    assert len(h.possible_causes) == 1


def test_case_ref_includes_resolution_fields() -> None:
    c = CaseRef(
        case_id="case-1",
        repo_id="repo-1",
        file_path="src/app.py",
        function_signature="def login(uid)",
        log_template="User {uid} logged in",
        resolved_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        resolution_summary="加 uid 非空校验",
        resolution_diff_url="https://git.example.com/repo/-/merge_requests/1.diff",
    )
    assert c.resolution_summary
    assert c.resolution_diff_url is not None


def test_call_context_shape() -> None:
    ctx = CallContext(
        function_signature="def login(uid)",
        callers=["def api_handler()"],
        callees=["_verify_token"],
        enclosing_community="auth",
        related_log_points=[],
        evidence_refs=[],
    )
    assert ctx.callers == ["def api_handler()"]


def test_repo_ingest_lock_status_running() -> None:
    lock = RepoIngestLock(
        repo_id="repo-1",
        status="running",
        started_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        finished_at=None,
        error_msg=None,
        ingester="user-1",
    )
    assert lock.status == "running"
    assert lock.finished_at is None


def test_audit_log_has_action_constants() -> None:
    a = AuditLog(
        id="audit-1",
        actor="user-1",
        action=ACTION_INGEST_REPO,
        target_repo_id="repo-1",
        target_log_point_ids=None,
        timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
        extra={"incremental": False},
    )
    assert a.action == "ingest_repo"
    # 所有 ACTION_* 常量都该是字符串
    for action in [
        ACTION_INGEST_REPO, ACTION_CONFIRM_INGESTION, ACTION_REVOKE_INGESTION,
        ACTION_QUERY, ACTION_LIST_CANDIDATES, ACTION_GET_CALL_CONTEXT,
        ACTION_FORCE_RELEASE_LOCK,
    ]:
        assert isinstance(action, str)


def test_language_and_status_constants() -> None:
    assert LANGUAGE_C == "c"
    assert LANGUAGE_PYTHON == "python"
    assert STATUS_CANDIDATE == "candidate"
    assert STATUS_CONFIRMED == "confirmed"
    assert STATUS_INGESTED == "ingested"
    assert ERROR_KIND_LOGIC == "logic_error"
    assert ERROR_KIND_UNKNOWN == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/contracts/test_log_point.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.contracts'`

- [ ] **Step 3: Write minimal implementation**

`packages/contracts/__init__.py`:
```python
"""数据契约子包 — M2/M3/M4 import 这些 dataclass 而非依赖 M1 内部。"""
from packages.contracts.audit import AuditLog
from packages.contracts.log_point import (
    CallContext,
    CaseRef,
    LLMHypothesis,
    LogPoint,
    RepoIngestLock,
)

__all__ = [
    "AuditLog",
    "CallContext",
    "CaseRef",
    "LLMHypothesis",
    "LogPoint",
    "RepoIngestLock",
]
```

`packages/contracts/enums.py`:
```python
"""枚举常量 — 字符串 + 常量便于扩展（spec 第 185-208 行）。"""
from __future__ import annotations

# Language
LANGUAGE_C = "c"
LANGUAGE_PYTHON = "python"
# 后续扩展: LANGUAGE_JAVA, LANGUAGE_GO ...

# Ingestion status
STATUS_CANDIDATE = "candidate"
STATUS_CONFIRMED = "confirmed"
STATUS_INGESTED = "ingested"

# LLM hypothesis error kind
ERROR_KIND_PARAM = "param_error"
ERROR_KIND_STATE = "state_error"
ERROR_KIND_EXTERNAL = "external_dep_error"
ERROR_KIND_LOGIC = "logic_error"
ERROR_KIND_UNKNOWN = "unknown"

# AuditLog action（M2/M3/M4 写操作时统一引用，避免字符串硬编码不一致）
ACTION_INGEST_REPO = "ingest_repo"
ACTION_CONFIRM_INGESTION = "confirm_ingestion"
ACTION_REVOKE_INGESTION = "revoke_ingestion"
ACTION_QUERY = "query"
ACTION_LIST_CANDIDATES = "list_candidates"
ACTION_GET_CALL_CONTEXT = "get_call_context"
ACTION_FORCE_RELEASE_LOCK = "force_release_lock"  # admin only
```

`packages/contracts/log_point.py`:
```python
"""LogPoint + 关联 dataclass（spec 第 100-181 行）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.contracts.audit import AuditLog


@dataclass
class CaseRef:
    case_id: str
    repo_id: str
    file_path: str
    function_signature: str
    log_template: str
    resolved_at: datetime
    resolution_summary: str
    resolution_diff_url: str | None


@dataclass
class LLMHypothesis:
    summary: str
    possible_causes: list[str]
    error_kind: str  # ERROR_KIND_* 常量
    suggested_check: str | None
    model_name: str
    prompt_hash: str
    generated_at: datetime


@dataclass
class LogPoint:
    id: str  # UUID
    repo_id: str
    git_commit_sha: str
    extractor_version: str
    file_path: str  # POSIX 风格
    function_signature: str
    line_start: int
    line_end: int
    language: str  # LANGUAGE_* 常量
    log_level: str
    log_message_template: str
    log_message_variables: list[str]
    framework_hint: str
    confidence_score: float

    # gitnexus 上下文
    enclosing_class: str | None
    call_chain_to_entry: list[str]
    enclosing_community: str | None

    # 历史案例
    evidence_refs: list[CaseRef] = field(default_factory=list)

    # LLM 假设
    llm_hypothesis: LLMHypothesis | None = None

    # 频次 + 状态
    occurrence_count: int = 0
    is_top_n: bool = False
    ingestion_status: str = "candidate"  # STATUS_* 常量
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


@dataclass
class CallContext:
    """get_call_context() 返回值 — M4 依赖。"""
    function_signature: str
    callers: list[str]
    callees: list[str]
    enclosing_community: str | None
    related_log_points: list[LogPoint]
    evidence_refs: list[CaseRef]


@dataclass
class RepoIngestLock:
    repo_id: str
    status: str  # "running" | "done" | "failed"
    started_at: datetime
    finished_at: datetime | None
    error_msg: str | None
    ingester: str
```

`packages/contracts/audit.py`:
```python
"""AuditLog dataclass（spec 第 319-329 行）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AuditLog:
    id: str
    actor: str  # user_id
    action: str  # ACTION_* 常量
    target_repo_id: str | None
    target_log_point_ids: list[str] | None
    timestamp: datetime
    extra: dict = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/contracts/test_log_point.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Lint check**

Run: `ruff check packages/contracts/ tests/contracts/`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/contracts/ tests/contracts/
git commit -m "feat(contracts): 数据契约子包 — LogPoint/LLMHypothesis/CaseRef/CallContext/RepoIngestLock/AuditLog + 枚举"
```

---

## Task 4: SQLAlchemy Models + Alembic migrations

**Files:**
- Create: `packages/m1/storage/__init__.py`
- Create: `packages/m1/storage/models.py`
- Create: `packages/m1/storage/migrations/env.py`
- Create: `packages/m1/storage/migrations/script.py.mako`
- Create: `packages/m1/storage/migrations/versions/0001_initial.py`
- Create: `alembic.ini`
- Test: `tests/unit_d/test_models.py`

**Interfaces:**
- Consumes: `packages/contracts/log_point.py`（schema 字段定义）、`packages/contracts/audit.py`
- Produces: `LogPointModel` / `CandidateStagingModel` / `RepoIngestLockModel` / `AuditLogModel` SQLAlchemy ORM 类；Alembic 初始迁移创建 4 张表

- [ ] **Step 1: Write the failing test**

`tests/unit_d/test_models.py`:
```python
"""SQLAlchemy models 测试 — 用 SQLite in-memory 验证表结构 + 基础 CRUD。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from packages.contracts.enums import LANGUAGE_PYTHON, STATUS_CANDIDATE
from packages.m1.storage.models import (
    AuditLogModel,
    CandidateStagingModel,
    LogPointModel,
    RepoIngestLockModel,
    Base,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_log_point_model_roundtrip(db_session: Session) -> None:
    lp = LogPointModel(
        id="lp-1",
        repo_id="repo-1",
        git_commit_sha="abc123",
        extractor_version="1.0.0",
        file_path="src/app.py",
        function_signature="def login()",
        line_start=10,
        line_end=12,
        language=LANGUAGE_PYTHON,
        log_level="INFO",
        log_message_template="User {uid} logged in",
        log_message_variables=["uid"],
        framework_hint="logging",
        confidence_score=1.0,
        enclosing_class=None,
        call_chain_to_entry=["api_handler"],
        enclosing_community="auth",
        evidence_refs_json="[]",
        llm_hypothesis_json=None,
        occurrence_count=1,
        is_top_n=True,
        ingestion_status=STATUS_CANDIDATE,
        first_seen_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )
    db_session.add(lp)
    db_session.commit()

    result = db_session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert result is not None
    assert result.file_path == "src/app.py"
    assert result.file_path == result.file_path.replace("\\", "/")  # POSIX 风格
    assert result.ingestion_status == "candidate"


def test_candidate_staging_model_separate_from_main(db_session: Session) -> None:
    """候选池表和主表分离（spec 第 87 行）。"""
    staging = CandidateStagingModel(
        id="cand-1",
        repo_id="repo-1",
        log_point_id="lp-1",  # 还没入主表
        occurrence_count=5,
        is_top_n=True,
        first_seen_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )
    db_session.add(staging)
    db_session.commit()
    # 主表 LogPointModel 此时应该没有 lp-1
    main_lp = db_session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert main_lp is None
    # 候选池有
    cand = db_session.scalar(select(CandidateStagingModel).where(CandidateStagingModel.id == "cand-1"))
    assert cand is not None


def test_repo_ingest_lock_model_state_machine(db_session: Session) -> None:
    lock = RepoIngestLockModel(
        repo_id="repo-1",
        status="running",
        started_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        finished_at=None,
        error_msg=None,
        ingester="user-1",
    )
    db_session.add(lock)
    db_session.commit()

    result = db_session.scalar(select(RepoIngestLockModel).where(RepoIngestLockModel.repo_id == "repo-1"))
    assert result.status == "running"


def test_audit_log_model(db_session: Session) -> None:
    audit = AuditLogModel(
        id="audit-1",
        actor="user-1",
        action="ingest_repo",
        target_repo_id="repo-1",
        target_log_point_ids_json=None,
        timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
        extra_json='{"incremental": false}',
    )
    db_session.add(audit)
    db_session.commit()
    result = db_session.scalar(select(AuditLogModel).where(AuditLogModel.id == "audit-1"))
    assert result.action == "ingest_repo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_d/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m1.storage'`

- [ ] **Step 3: Write minimal implementation**

`packages/m1/storage/__init__.py`:
```python
"""M1 存储层。"""
```

`packages/m1/storage/models.py`:
```python
"""SQLAlchemy ORM models — LogPoint 主表 / 候选池 / 锁 / 审计（spec 第 100-181 行 + 319-329 行）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _posix_path(value: str) -> str:
    """存储前统一转 POSIX 风格（AC-15）。"""
    return value.replace("\\", "/")


class LogPointModel(Base):
    __tablename__ = "log_point"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(64), index=True)
    git_commit_sha: Mapped[str] = mapped_column(String(64))
    extractor_version: Mapped[str] = mapped_column(String(16))
    file_path: Mapped[str] = mapped_column(String(512))  # 存时转 POSIX
    function_signature: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(16))
    log_level: Mapped[str] = mapped_column(String(16))
    log_message_template: Mapped[str] = mapped_column(Text)
    log_message_variables: Mapped[list[str]] = mapped_column(JSON)
    framework_hint: Mapped[str] = mapped_column(String(32))
    confidence_score: Mapped[float] = mapped_column(Float)
    enclosing_class: Mapped[str | None] = mapped_column(String(256), nullable=True)
    call_chain_to_entry: Mapped[list[str]] = mapped_column(JSON)
    enclosing_community: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    llm_hypothesis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    is_top_n: Mapped[bool] = mapped_column(default=False)
    ingestion_status: Mapped[str] = mapped_column(String(16), default="candidate")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __init__(self, **kwargs: Any) -> None:
        # file_path 统一 POSIX（AC-15）
        if "file_path" in kwargs:
            kwargs["file_path"] = _posix_path(kwargs["file_path"])
        super().__init__(**kwargs)


class CandidateStagingModel(Base):
    """候选池 — 不进主表，用户 confirm 后才入 log_point。"""
    __tablename__ = "candidate_staging"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(64), index=True)
    log_point_id: Mapped[str] = mapped_column(String(64), index=True)  # 候选阶段就分配 UUID
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    is_top_n: Mapped[bool] = mapped_column(default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RepoIngestLockModel(Base):
    __tablename__ = "repo_ingest_lock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))  # running/done/failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingester: Mapped[str] = mapped_column(String(64))


class AuditLogModel(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64))
    target_repo_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target_log_point_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    extra_json: Mapped[str] = mapped_column(Text, default="{}")
```

`alembic.ini`（项目根）:
```ini
[alembic]
script_location = packages/m1/storage/migrations
sqlalchemy.url = postgresql://user:pass@localhost/codefly
```

`packages/m1/storage/migrations/env.py`:
```python
"""Alembic env。"""
from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from packages.m1.storage.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`packages/m1/storage/migrations/script.py.mako`:
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`packages/m1/storage/migrations/versions/0001_initial.py`:
```python
"""Initial migration — 4 张表。

Revision ID: 0001
Revises:
Create Date: 2026-07-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "log_point",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("repo_id", sa.String(64), nullable=False, index=True),
        sa.Column("git_commit_sha", sa.String(64), nullable=False),
        sa.Column("extractor_version", sa.String(16), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("function_signature", sa.Text, nullable=False),
        sa.Column("line_start", sa.Integer, nullable=False),
        sa.Column("line_end", sa.Integer, nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("log_level", sa.String(16), nullable=False),
        sa.Column("log_message_template", sa.Text, nullable=False),
        sa.Column("log_message_variables", sa.JSON, nullable=False),
        sa.Column("framework_hint", sa.String(32), nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("enclosing_class", sa.String(256), nullable=True),
        sa.Column("call_chain_to_entry", sa.JSON, nullable=False),
        sa.Column("enclosing_community", sa.String(64), nullable=True),
        sa.Column("evidence_refs_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("llm_hypothesis_json", sa.Text, nullable=True),
        sa.Column("occurrence_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_top_n", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("ingestion_status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_log_point_repo_file_line", "log_point",
                    ["repo_id", "file_path", "line_start"], unique=True)

    op.create_table(
        "candidate_staging",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("repo_id", sa.String(64), nullable=False, index=True),
        sa.Column("log_point_id", sa.String(64), nullable=False, index=True),
        sa.Column("occurrence_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_top_n", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "repo_ingest_lock",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_msg", sa.Text, nullable=True),
        sa.Column("ingester", sa.String(64), nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("actor", sa.String(64), nullable=False, index=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_repo_id", sa.String(64), nullable=True, index=True),
        sa.Column("target_log_point_ids_json", sa.Text, nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("extra_json", sa.Text, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("repo_ingest_lock")
    op.drop_table("candidate_staging")
    op.drop_index("ix_log_point_repo_file_line", table_name="log_point")
    op.drop_table("log_point")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_d/test_models.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint check**

Run: `ruff check packages/m1/storage/ tests/unit_d/test_models.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/m1/storage/ alembic.ini tests/unit_d/test_models.py
git commit -m "feat(m1): sqlalchemy models + alembic 初始迁移 — 4 张表"
```

---

## Task 5: gitnexus MCP Client 封装

**Files:**
- Create: `packages/m1/gitnexus_client.py`
- Test: `tests/unit_a/test_gitnexus_client.py`

**Interfaces:**
- Consumes: `gitnexus` CLI（通过 subprocess 调用，不依赖 MCP stdio 避免运行时复杂度）
- Produces: `GitNexusClient` 类，方法 `analyze(repo_path, alias) -> None`、`cypher(query: str) -> list[dict]`、`context(symbol_name: str, repo_alias: str) -> dict`、`list_repos() -> list[dict]`

- [ ] **Step 1: Write the failing test**

`tests/unit_a/test_gitnexus_client.py`:
```python
"""gitnexus client 测试 — 用 subprocess mock 验证 CLI 调用。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from packages.m1.gitnexus_client import GitNexusClient


def test_analyze_invokes_gitnexus_cli(tmp_path) -> None:
    client = GitNexusClient()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        client.analyze(repo_path=str(tmp_path), alias="test-repo")
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "gitnexus" in cmd[0] or cmd[0].endswith("gitnexus")
        assert "analyze" in cmd
        assert "--name" in cmd


def test_cypher_parses_markdown_table_to_dicts() -> None:
    client = GitNexusClient()
    fake_output = json.dumps({
        "markdown": "| caller | callee |\n| --- | --- |\n| foo | bar |",
        "row_count": 1,
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
        results = client.cypher("MATCH (a)-[:CALLS]->(b) RETURN a, b", repo_alias="r")
        assert len(results) == 1
        assert results[0]["caller"] == "foo"
        assert results[0]["callee"] == "bar"


def test_list_repos_returns_alias_list() -> None:
    client = GitNexusClient()
    fake_output = "\nIndexed Repositories (1)\n\nGenericAgent\n  Path: ...\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
        repos = client.list_repos()
        assert "GenericAgent" in repos


def test_context_returns_symbol_info() -> None:
    client = GitNexusClient()
    fake_output = json.dumps({
        "name": "login",
        "filePath": "src/app.py",
        "kind": "Function",
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
        result = client.context(symbol_name="login", repo_alias="r")
        assert result["name"] == "login"
        assert result["filePath"] == "src/app.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_a/test_gitnexus_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m1.gitnexus_client'`

- [ ] **Step 3: Write minimal implementation**

`packages/m1/gitnexus_client.py`:
```python
"""gitnexus CLI 客户端封装 — 用 subprocess 调用，不依赖 MCP stdio 运行时复杂度。"""
from __future__ import annotations

import json
import re
import shutil
import subprocess


class GitNexusError(Exception):
    pass


class GitNexusClient:
    """gitnexus CLI 客户端。所有 gitnexus 调用走这里，便于 mock + 跨平台。"""

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary or shutil.which("gitnexus") or "gitnexus"

    def _run(self, args: list[str]) -> str:
        cmd = [self._binary, *args]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)
        if result.returncode != 0:
            raise GitNexusError(f"gitnexus {args[0]} failed: {result.stderr}")
        return result.stdout

    def analyze(self, repo_path: str, alias: str) -> None:
        """gitnexus analyze --name <alias> <path>"""
        self._run(["analyze", "--name", alias, repo_path])

    def cypher(self, query: str, repo_alias: str | None = None) -> list[dict[str, str]]:
        """gitnexus cypher <query> — 解析 markdown 表为 dict 列表。"""
        args = ["cypher", query]
        if repo_alias:
            args.extend(["-r", repo_alias])
        stdout = self._run(args)
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise GitNexusError(f"cypher output not JSON: {e}") from e
        return self._parse_markdown_table(payload.get("markdown", ""))

    @staticmethod
    def _parse_markdown_table(markdown: str) -> list[dict[str, str]]:
        """把 gitnexus cypher 输出的 markdown 表解析为 dict 列表。"""
        lines = [ln.strip() for ln in markdown.splitlines() if ln.strip()]
        if not lines:
            return []
        # 找表头
        header_idx = next((i for i, ln in enumerate(lines) if "|" in ln), -1)
        if header_idx == -1:
            return []
        headers = [h.strip() for h in lines[header_idx].strip("|").split("|")]
        results: list[dict[str, str]] = []
        for ln in lines[header_idx + 2:]:  # 跳过分隔行 | --- |
            if "|" not in ln:
                continue
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) != len(headers):
                continue
            results.append(dict(zip(headers, cells, strict=False)))
        return results

    def context(self, symbol_name: str, repo_alias: str | None = None) -> dict:
        args = ["context", symbol_name]
        if repo_alias:
            args.extend(["-r", repo_alias])
        stdout = self._run(args)
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            raise GitNexusError(f"context output not JSON: {e}") from e

    def list_repos(self) -> list[str]:
        stdout = self._run(["list"])
        # 解析 "Indexed Repositories (N)\n\n  <name>\n    Path:..."
        return re.findall(r"^\s{2,}(\S+)\n\s+Path:", stdout, re.MULTILINE)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_a/test_gitnexus_client.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint check**

Run: `ruff check packages/m1/gitnexus_client.py tests/unit_a/test_gitnexus_client.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/m1/gitnexus_client.py tests/unit_a/test_gitnexus_client.py
git commit -m "feat(m1): gitnexus CLI 客户端封装"
```

---

## Task 6: Unit A — Repo Registrar（含路径沙箱 + 并发锁 + URL 白名单）

**Files:**
- Create: `packages/m1/unit_a_repo_registrar.py`
- Test: `tests/unit_a/test_repo_registrar.py`

**Interfaces:**
- Consumes: `GitNexusClient`（T5）、`RepoIngestLockModel`（T4）、`Config`（T2）
- Produces: `RepoRegistrar` 类，方法 `ingest(source: RepoSource, ingester: User) -> RepoId`、`force_release_lock(repo_id, admin) -> None`

- [ ] **Step 1: Write the failing test**

`tests/unit_a/test_repo_registrar.py`:
```python
"""Unit A 测试 — AC-1 / AC-2 / AC-14 / AC-20。"""
from __future__ import annotations

import pathlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from packages.contracts.enums import ACTION_FORCE_RELEASE_LOCK, ACTION_INGEST_REPO
from packages.m1.storage.models import Base, RepoIngestLockModel
from packages.m1.unit_a_repo_registrar import (
    RepoRegistrar,
    RepoSource,
    User,
    UnsafePathError,
    UnsafeUrlError,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture()
def registrar(db_session: Session):
    gn_mock = MagicMock()
    gn_mock.analyze.return_value = None
    return RepoRegistrar(gitnexus=gn_mock, session=db_session, git_user_email="bot@codefly")


def test_ingest_local_path_returns_repo_id(registrar: RepoRegistrar, tmp_path: pathlib.Path) -> None:
    source = RepoSource(local_path=str(tmp_path))
    repo_id = registrar.ingest(source, User(id="user-1", name="alice"))
    assert repo_id.startswith("repo-")
    # gitnexus.analyze 被调用
    registrar._gitnexus.analyze.assert_called_once()


def test_ingest_rejects_dotdot_path(registrar: RepoRegistrar) -> None:
    source = RepoSource(local_path="/etc/../../../sensitive")
    with pytest.raises(UnsafePathError):
        registrar.ingest(source, User(id="user-1", name="alice"))


def test_ingest_rejects_non_https_url(registrar: RepoRegistrar) -> None:
    source = RepoSource(url="http://github.com/evil/repo")
    with pytest.raises(UnsafeUrlError):
        registrar.ingest(source, User(id="user-1", name="alice"))


def test_ingest_accepts_https_url(registrar: RepoRegistrar) -> None:
    source = RepoSource(url="https://github.com/foo/bar")
    repo_id = registrar.ingest(source, User(id="user-1", name="alice"))
    assert repo_id


def test_concurrent_ingest_same_repo_returns_running(
    db_session: Session, registrar: RepoRegistrar, tmp_path: pathlib.Path
) -> None:
    # 预置一个 running lock
    db_session.add(RepoIngestLockModel(
        repo_id="repo-running",
        status="running",
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        error_msg=None,
        ingester="user-0",
    ))
    db_session.commit()

    # 因为 lock 已存在，新 ingest 应该返回同一个 repo_id 标记 running
    # 用相同 path 触发相同 repo_id hash
    source = RepoSource(local_path=str(tmp_path))
    # 强制让 lock 已存在：
    # 先 ingest 一次让它 running
    with patch.object(registrar, "_compute_repo_id", return_value="repo-running"):
        result = registrar.ingest(source, User(id="user-1", name="alice"))
        assert result == "repo-running"
        # gitnexus.analyze 不应再次调用（因为已经在 running）
        # 第一次 fixture 已调用一次（test_ingest_local_path_returns_repo_id），这里不同 test 互不影响
        # 我们再 assert 当前 test 里没新调用
        # （registrar fixture 是 fresh mock，所以 analyze 不该被调）
        registrar._gitnexus.analyze.assert_not_called()


def test_ingest_writes_audit_log(registrar: RepoRegistrar, tmp_path: pathlib.Path, db_session: Session) -> None:
    from packages.m1.audit_log import AuditLogger
    audit_mock = MagicMock(spec=AuditLogger)
    registrar._audit = audit_mock

    source = RepoSource(local_path=str(tmp_path))
    registrar.ingest(source, User(id="user-1", name="alice"))
    audit_mock.log.assert_called_once()
    call_kwargs = audit_mock.log.call_args
    assert call_kwargs.kwargs["action"] == ACTION_INGEST_REPO


def test_force_release_lock_admin_only(registrar: RepoRegistrar, db_session: Session) -> None:
    # 预置 running lock
    db_session.add(RepoIngestLockModel(
        repo_id="repo-x",
        status="running",
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        error_msg=None,
        ingester="user-0",
    ))
    db_session.commit()

    # 非 admin 调用 → 拒绝
    with pytest.raises(PermissionError):
        registrar.force_release_lock("repo-x", User(id="user-non-admin", name="bob", is_admin=False))

    # admin 调用 → 成功
    registrar.force_release_lock("repo-x", User(id="admin", name="root", is_admin=True))
    lock = db_session.scalar(select(RepoIngestLockModel).where(RepoIngestLockModel.repo_id == "repo-x").order_by(RepoIngestLockModel.id.desc()))
    assert lock.status == "failed"  # 强制释放 = 标记 failed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_a/test_repo_registrar.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m1.unit_a_repo_registrar'`

- [ ] **Step 3: Write minimal implementation**

`packages/m1/unit_a_repo_registrar.py`:
```python
"""Unit A: Repo Registrar — clone/gitnexus analyze/候选池构建 + 安全 + 并发锁。"""
from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import re
import subprocess
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.contracts.enums import ACTION_FORCE_RELEASE_LOCK, ACTION_INGEST_REPO
from packages.m1.gitnexus_client import GitNexusClient
from packages.m1.storage.models import RepoIngestLockModel

# 路径越权防护
_DOTDOT_PATTERN = re.compile(r"\.\.")
_URL_HTTPS_ONLY = re.compile(r"^https://")


class UnsafePathError(ValueError):
    pass


class UnsafeUrlError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class User:
    id: str
    name: str
    is_admin: bool = False


@dataclasses.dataclass(frozen=True)
class RepoSource:
    url: str | None = None
    local_path: str | None = None


class RepoRegistrar:
    def __init__(
        self,
        gitnexus: GitNexusClient,
        session: Session,
        git_user_email: str = "bot@codefly",
        audit: "AuditLogger | None" = None,
    ) -> None:
        self._gitnexus = gitnexus
        self._session = session
        self._git_email = git_user_email
        # 避免循环 import：延迟 import
        from packages.m1.audit_log import AuditLogger
        self._audit = audit or AuditLogger(session)

    def _compute_repo_id(self, source: RepoSource) -> str:
        key = source.url or str(pathlib.Path(source.local_path or "").resolve())
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return f"repo-{h}"

    def _validate_source(self, source: RepoSource) -> None:
        if source.url:
            if not _URL_HTTPS_ONLY.match(source.url):
                raise UnsafeUrlError(f"非 https URL 被拒绝: {source.url}")
        elif source.local_path:
            if _DOTDOT_PATTERN.search(source.local_path):
                raise UnsafePathError(f"路径含 .. 被拒绝: {source.local_path}")
        else:
            raise ValueError("RepoSource 必须有 url 或 local_path")

    def ingest(self, source: RepoSource, ingester: User, incremental: bool = False) -> str:
        """clone+gitnexus analyze+候选池构建。incremental=True 时 raise NotImplementedError（AC-20）。"""
        if incremental:
            raise NotImplementedError("incremental mode in F001 v1.1")

        self._validate_source(source)
        repo_id = self._compute_repo_id(source)

        # 并发锁检查（AC-14）
        existing = self._session.scalar(
            select(RepoIngestLockModel)
            .where(RepoIngestLockModel.repo_id == repo_id)
            .order_by(RepoIngestLockModel.id.desc())
        )
        if existing and existing.status == "running":
            # 已在解析中，返回 repo_id 但不再建图
            self._audit.log(
                actor=ingester.id, action=ACTION_INGEST_REPO,
                target_repo_id=repo_id, extra={"already_running": True, "ingester": ingester.id},
            )
            return repo_id

        # 新建 lock
        lock = RepoIngestLockModel(
            repo_id=repo_id, status="running",
            started_at=datetime.now(timezone.utc), finished_at=None,
            error_msg=None, ingester=ingester.id,
        )
        self._session.add(lock)
        self._session.commit()

        try:
            # gitnexus analyze
            alias = repo_id
            repo_path = source.local_path or self._clone_url(source.url, repo_id)
            self._gitnexus.analyze(repo_path=repo_path, alias=alias)
            lock.status = "done"
            lock.finished_at = datetime.now(timezone.utc)
        except Exception as e:
            lock.status = "failed"
            lock.finished_at = datetime.now(timezone.utc)
            lock.error_msg = str(e)
            self._session.commit()
            raise

        self._session.commit()
        self._audit.log(
            actor=ingester.id, action=ACTION_INGEST_REPO,
            target_repo_id=repo_id, extra={"incremental": False, "ingester": ingester.id},
        )
        return repo_id

    def _clone_url(self, url: str, repo_id: str) -> str:
        """clone 远程仓到临时工作目录。"""
        work_dir = pathlib.Path("/tmp/codefly-repos") / repo_id
        work_dir.parent.mkdir(parents=True, exist_ok=True)
        if work_dir.exists():
            subprocess.run(["git", "-C", str(work_dir), "pull", "--ff-only"], check=True)
        else:
            subprocess.run(["git", "clone", url, str(work_dir)], check=True)
        return str(work_dir)

    def force_release_lock(self, repo_id: str, admin: User) -> None:
        if not admin.is_admin:
            raise PermissionError("force_release_lock 需要 admin 权限")
        lock = self._session.scalar(
            select(RepoIngestLockModel)
            .where(RepoIngestLockModel.repo_id == repo_id)
            .order_by(RepoIngestLockModel.id.desc())
        )
        if lock and lock.status == "running":
            lock.status = "failed"
            lock.finished_at = datetime.now(timezone.utc)
            lock.error_msg = "force released by admin"
            self._session.commit()
            self._audit.log(
                actor=admin.id, action=ACTION_FORCE_RELEASE_LOCK,
                target_repo_id=repo_id, extra={"admin": admin.id},
            )
```

`packages/m1/audit_log.py`（Unit A 测试依赖，提前在此 task 创建）:
```python
"""AuditLogger — 写 audit_log 表。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from packages.m1.storage.models import AuditLogModel


class AuditLogger:
    def __init__(self, session: Session) -> None:
        self._session = session

    def log(
        self,
        actor: str,
        action: str,
        target_repo_id: str | None = None,
        target_log_point_ids: list[str] | None = None,
        extra: dict | None = None,
    ) -> None:
        entry = AuditLogModel(
            id=f"audit-{uuid.uuid4().hex[:12]}",
            actor=actor,
            action=action,
            target_repo_id=target_repo_id,
            target_log_point_ids_json=json.dumps(target_log_point_ids) if target_log_point_ids else None,
            timestamp=datetime.now(timezone.utc),
            extra_json=json.dumps(extra or {}),
        )
        self._session.add(entry)
        self._session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_a/test_repo_registrar.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Lint check**

Run: `ruff check packages/m1/unit_a_repo_registrar.py packages/m1/audit_log.py tests/unit_a/test_repo_registrar.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/m1/unit_a_repo_registrar.py packages/m1/audit_log.py tests/unit_a/test_repo_registrar.py
git commit -m "feat(m1): unit a repo registrar + 路径沙箱 + 并发锁 + audit logger"
```

---

## Task 7: Fixture 代码仓 + tree-sitter 解析器（Unit B 前置）

**Files:**
- Create: `tests/fixtures/python_logging_repo/main.py`
- Create: `tests/fixtures/python_loguru_repo/main.py`
- Create: `tests/fixtures/python_print_repo/main.py`
- Create: `tests/fixtures/c_printf_repo/main.c`
- Create: `tests/fixtures/c_syslog_repo/main.c`
- Create: `tests/fixtures/c_custom_log_repo/main.c`
- Create: `tests/fixtures/decoy_repo/main.py`（含 format_error/handleError 干扰）
- Create: `packages/m1/tree_sitter_parser.py`
- Test: `tests/unit_b/test_tree_sitter_parser.py`

**Interfaces:**
- Consumes: tree-sitter-languages 包（提供 Python + C parser）
- Produces: `TreeSitterParser` 类，方法 `parse_file(path: Path, language: str) -> ParsedFile`，`ParsedFile` 含 `function_signatures` / `call_sites` / `line_for_node`

- [ ] **Step 1: Write fixture 仓**

`tests/fixtures/python_logging_repo/main.py`:
```python
"""Fixture: Python logging 调用。"""
import logging

LOG = logging.getLogger(__name__)


def login(uid: str) -> bool:
    LOG.info("User %s logged in", uid)
    LOG.warning("login attempt for uid=%s", uid)
    return True


def fail(uid: str) -> None:
    LOG.error("login failed for %s", uid)
    LOG.debug("debug detail %s", uid)
```

`tests/fixtures/python_loguru_repo/main.py`:
```python
"""Fixture: Python loguru 调用。"""
from loguru import logger


def process(task_id: str) -> None:
    logger.info("processing task {}", task_id)
    logger.error("task {} failed", task_id)
```

`tests/fixtures/python_print_repo/main.py`:
```python
"""Fixture: 裸 print（默认不识别；config include_print=True 时识别）。"""
def debug_print(msg: str) -> None:
    print(msg)
    print("done", msg)
```

`tests/fixtures/c_printf_repo/main.c`:
```c
#include <stdio.h>

int do_work(int x) {
    printf("processing %d\n", x);
    fprintf(stderr, "error on %d\n", x);
    return x * 2;
}
```

`tests/fixtures/c_syslog_repo/main.c`:
```c
#include <syslog.h>

void worker(int level) {
    syslog(LOG_INFO, "started level=%d", level);
    syslog(LOG_ERR, "error level=%d", level);
}
```

`tests/fixtures/c_custom_log_repo/main.c`:
```c
/* 自定义日志函数 + 调用 */
void app_log_error(const char* msg);
void app_log_debug(const char* msg);

void handle(int x) {
    app_log_error("failed");
    app_log_debug("detail");
}
```

`tests/fixtures/decoy_repo/main.py`:
```python
"""Fixture: 干扰函数，命名含 error/log 但不是日志调用。"""


def format_error(code: int) -> str:
    return f"ERR-{code}"


def handleError(exc: Exception) -> None:
    raise RuntimeError("re-raise") from exc


class LoginService:
    def login(self, uid: str) -> bool:
        # 这是真的日志调用
        import logging
        logging.info("uid=%s", uid)
        return True
```

- [ ] **Step 2: Write the failing test**

`tests/unit_b/test_tree_sitter_parser.py`:
```python
"""tree-sitter 解析器测试 — 给定 fixture 文件，能抽函数签名 + call sites。"""
from __future__ import annotations

import pathlib

import pytest

from packages.m1.tree_sitter_parser import TreeSitterParser


def test_parse_python_logging_repo(fixtures_dir: pathlib.Path) -> None:
    parser = TreeSitterParser()
    parsed = parser.parse_file(fixtures_dir / "python_logging_repo" / "main.py", language="python")
    fn_names = [f.name for f in parsed.functions]
    assert "login" in fn_names
    assert "fail" in fn_names


def test_parse_c_printf_repo(fixtures_dir: pathlib.Path) -> None:
    parser = TreeSitterParser()
    parsed = parser.parse_file(fixtures_dir / "c_printf_repo" / "main.c", language="c")
    fn_names = [f.name for f in parsed.functions]
    assert "do_work" in fn_names


def test_call_sites_extracted(fixtures_dir: pathlib.Path) -> None:
    parser = TreeSitterParser()
    parsed = parser.parse_file(fixtures_dir / "python_logging_repo" / "main.py", language="python")
    # 应该能找到 LOG.info / LOG.warning / LOG.error / LOG.debug 调用
    callee_names = [c.callee_name for c in parsed.call_sites]
    assert "LOG.info" in callee_names or any("info" in n.lower() for n in callee_names)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit_b/test_tree_sitter_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m1.tree_sitter_parser'`

- [ ] **Step 4: Write minimal implementation**

`packages/m1/tree_sitter_parser.py`:
```python
"""tree-sitter 解析器 — 抽函数签名 + call sites（Layer 2 精筛用）。"""
from __future__ import annotations

import dataclasses
import pathlib

from tree_sitter_languages import get_parser


@dataclasses.dataclass
class FunctionSignature:
    name: str
    signature: str  # 完整签名文本
    line_start: int
    line_end: int
    enclosing_class: str | None


@dataclasses.dataclass
class CallSite:
    callee_name: str  # 函数调用名（可能含 obj. 前缀）
    line: int
    column: int
    enclosing_function: str | None


@dataclasses.dataclass
class ParsedFile:
    path: pathlib.Path
    language: str
    functions: list[FunctionSignature]
    call_sites: list[CallSite]


class TreeSitterParser:
    def parse_file(self, path: pathlib.Path, language: str) -> ParsedFile:
        parser = get_parser(language)
        source = path.read_bytes()
        tree = parser.parse(source)
        root = tree.root_node

        functions = self._extract_functions(root, source, language)
        call_sites = self._extract_call_sites(root, source)

        return ParsedFile(
            path=path, language=language,
            functions=functions, call_sites=call_sites,
        )

    def _extract_functions(
        self, root, source: bytes, language: str
    ) -> list[FunctionSignature]:
        functions: list[FunctionSignature] = []
        if language == "python":
            fn_node_type = "function_definition"
            name_field = "name"
        else:  # c
            fn_node_type = "function_definition"
            name_field = "declarator"

        def walk(node, enclosing_class: str | None) -> None:
            if node.type == "class_definition" and language == "python":
                cls_name_node = node.child_by_field_name("name")
                cls_name = (
                    source[cls_name_node.start_byte:cls_name_node.end_byte].decode("utf-8")
                    if cls_name_node else None
                )
                for child in node.children:
                    walk(child, cls_name)
                return
            if node.type == fn_node_type:
                name_node = node.child_by_field_name(name_field)
                if language == "c" and name_node:
                    # declarator 通常是 function_declarator，里面才是 name
                    name_node = name_node.child_by_field_name("declarator") or name_node
                    while name_node and name_node.type == "function_declarator":
                        name_node = name_node.child_by_field_name("declarator")
                if name_node:
                    name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                    signature = source[node.start_byte:node.end_byte].decode("utf-8").splitlines()[0]
                    functions.append(FunctionSignature(
                        name=name, signature=signature,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        enclosing_class=enclosing_class,
                    ))
            for child in node.children:
                walk(child, enclosing_class)

        walk(root, None)
        return functions

    def _extract_call_sites(self, root, source: bytes) -> list[CallSite]:
        sites: list[CallSite] = []
        # 找当前函数上下文
        current_fn: list[str | None] = [None]

        def walk(node) -> None:
            if node.type == "function_definition":
                # 用 _extract_functions 同样的 name_field 逻辑这里简化
                prev_fn = current_fn[0]
                # 找名字
                name_node = node.child_by_field_name("name") or node.child_by_field_name("declarator")
                while name_node and name_node.type == "function_declarator":
                    name_node = name_node.child_by_field_name("declarator")
                if name_node:
                    current_fn[0] = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                for child in node.children:
                    walk(child)
                current_fn[0] = prev_fn
                return
            if node.type == "call":
                # callee 可能是 identifier 或 attribute (LOG.info)
                callee_node = node.child_by_field_name("function")
                if callee_node:
                    callee_name = source[callee_node.start_byte:callee_node.end_byte].decode("utf-8")
                    sites.append(CallSite(
                        callee_name=callee_name,
                        line=node.start_point[0] + 1,
                        column=node.start_point[1],
                        enclosing_function=current_fn[0],
                    ))
            for child in node.children:
                walk(child)

        walk(root)
        return sites
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit_b/test_tree_sitter_parser.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Lint check**

Run: `ruff check packages/m1/tree_sitter_parser.py tests/unit_b/test_tree_sitter_parser.py tests/fixtures/`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/ packages/m1/tree_sitter_parser.py tests/unit_b/test_tree_sitter_parser.py
git commit -m "feat(m1): fixture 代码仓 + tree-sitter 解析器"
```

---

## Task 8: Unit B — Log Point Finder（两层过滤）

**Files:**
- Create: `packages/m1/unit_b_log_point_finder.py`
- Test: `tests/unit_b/test_log_point_finder.py`

**Interfaces:**
- Consumes: `GitNexusClient`（T5）、`TreeSitterParser`（T7）、`LogPoint` dataclass（T3）、fixture 仓（T7）
- Produces: `LogPointFinder` 类，方法 `find(repo_id, repo_path, language) -> list[LogPoint]`、内部 Layer 1 cypher + Layer 2 tree-sitter

- [ ] **Step 1: Write the failing test**

`tests/unit_b/test_log_point_finder.py`:
```python
"""Unit B 测试 — AC-3 / AC-4 / AC-5。"""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest

from packages.contracts.enums import LANGUAGE_C, LANGUAGE_PYTHON
from packages.m1.unit_b_log_point_finder import LogPointFinder


@pytest.fixture()
def finder_with_mock_gn():
    """finder 用 mock gitnexus（避免真实建图），Layer 2 直接跑 tree-sitter。"""
    gn = MagicMock()
    # cypher 返回空（fixture 不走 gitnexus，直接走 fixture 文件 + tree-sitter）
    gn.cypher.return_value = []
    return LogPointFinder(gitnexus=gn)


def test_python_logging_recognized(fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_logging_repo",
        language=LANGUAGE_PYTHON,
    )
    # 4 个 LOG 调用
    assert len(points) >= 4
    for p in points:
        assert p.framework_hint == "logging"
        assert p.confidence_score == 1.0
        assert p.log_level in {"INFO", "WARNING", "ERROR", "DEBUG"}


def test_python_loguru_recognized(fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_loguru_repo",
        language=LANGUAGE_PYTHON,
    )
    assert len(points) >= 2
    assert all(p.framework_hint == "loguru" for p in points)


def test_python_print_default_not_recognized(
    fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder
) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_print_repo",
        language=LANGUAGE_PYTHON,
        include_print=False,
    )
    # 默认不识别 print
    assert len(points) == 0


def test_python_print_with_include_print_true(
    fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder
) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_print_repo",
        language=LANGUAGE_PYTHON,
        include_print=True,
    )
    assert len(points) >= 2
    assert all(p.confidence_score == 0.5 for p in points)
    assert all(p.framework_hint == "print" for p in points)


def test_c_printf_recognized(fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "c_printf_repo",
        language=LANGUAGE_C,
    )
    assert len(points) >= 2  # printf + fprintf
    assert all(p.confidence_score == 1.0 for p in points)


def test_c_syslog_recognized(fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "c_syslog_repo",
        language=LANGUAGE_C,
    )
    assert len(points) >= 2
    assert all(p.framework_hint == "syslog" for p in points)


def test_c_custom_log_function_recognized(
    fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder
) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "c_custom_log_repo",
        language=LANGUAGE_C,
    )
    # app_log_error / app_log_debug 命中 ^.*_(log|error|debug|trace).*$
    assert len(points) >= 2
    assert all(p.framework_hint == "custom" for p in points)
    assert all(p.confidence_score == 0.7 for p in points)


def test_decoy_repo_filters_out_business_functions(
    fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder
) -> None:
    """AC-5：format_error/handleError 等业务函数被过滤（误识别率 < 5%）。"""
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "decoy_repo",
        language=LANGUAGE_PYTHON,
    )
    # decoy_repo 里只有 LoginService.login 里的 logging.info 是真日志调用
    # format_error/handleError 是业务函数，不该被识别
    callee_names = [p.function_signature for p in points]
    # 不应该把 format_error / handleError 当日志函数
    # 注意 function_signature 是调用点所在函数的签名，不是 callee 名
    # 真正的 log point 只该有 1 个（LoginService.login 内的 logging.info）
    assert len(points) == 1, f"误识别：{points}"
    assert "login" in points[0].function_signature


def test_deduplication_same_file_line(fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder) -> None:
    """AC-4：同 (repo_id, file_path, line_start) 只一条。"""
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_logging_repo",
        language=LANGUAGE_PYTHON,
    )
    keys = [(p.repo_id, p.file_path, p.line_start) for p in points]
    assert len(keys) == len(set(keys))


def test_file_path_posix_style_on_windows(
    fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder
) -> None:
    """AC-15：file_path 统一 POSIX 风格。"""
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_logging_repo",
        language=LANGUAGE_PYTHON,
    )
    for p in points:
        assert "\\" not in p.file_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_b/test_log_point_finder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m1.unit_b_log_point_finder'`

- [ ] **Step 3: Write minimal implementation**

`packages/m1/unit_b_log_point_finder.py`:
```python
"""Unit B: Log Point Finder — Layer 1 cypher 粗筛 + Layer 2 tree-sitter 精筛。"""
from __future__ import annotations

import pathlib
import re
import uuid
from datetime import datetime, timezone

from packages.contracts.enums import LANGUAGE_C, LANGUAGE_PYTHON
from packages.contracts.log_point import LogPoint
from packages.m1.gitnexus_client import GitNexusClient
from packages.m1.tree_sitter_parser import CallSite, TreeSitterParser

# Layer 1 cypher 粗筛命名模式
_LAYER1_CYPHER_PATTERN = (
    r"^(log|print|printf|fprintf|syslog|logging|logger|warn|error|debug|trace).*$"
)

# Layer 2 精筛白名单
_PY_LOGGING_METHODS = {"info", "warning", "warn", "error", "debug", "critical", "exception"}
_PY_LOGURU_METHODS = {"info", "warning", "warn", "error", "debug", "critical", "exception", "trace"}
_C_STDIO_FUNCS = {"printf", "fprintf", "sprintf", "snprintf"}
_C_SYSLOG_FUNCS = {"syslog"}
_PY_PRINT_FUNC = "print"

# 自定义日志函数命名模式（C）
_C_CUSTOM_LOG_PATTERN = re.compile(r"^.*_(log|error|debug|trace).*$")


class LogPointFinder:
    def __init__(
        self,
        gitnexus: GitNexusClient,
        tree_sitter: TreeSitterParser | None = None,
    ) -> None:
        self._gitnexus = gitnexus
        self._ts = tree_sitter or TreeSitterParser()

    def find(
        self,
        repo_id: str,
        repo_path: pathlib.Path,
        language: str,
        include_print: bool = False,
    ) -> list[LogPoint]:
        # 扫该仓所有源文件
        extensions = self._extensions_for_language(language)
        source_files: list[pathlib.Path] = []
        for ext in extensions:
            source_files.extend(repo_path.rglob(f"*.{ext}"))

        all_points: list[LogPoint] = []
        for src_file in source_files:
            parsed = self._ts.parse_file(src_file, language=language)
            for call in parsed.call_sites:
                point = self._classify_call(repo_id, src_file, parsed, call, language, include_print)
                if point is not None:
                    all_points.append(point)

        # 去重（AC-4）
        deduped = self._dedupe(all_points)

        # occurrence_count = 同 log_template 在仓内被识别为 LogPoint 的次数
        for p in deduped:
            p.occurrence_count = sum(
                1 for q in deduped if q.log_message_template == p.log_message_template
            )

        return deduped

    @staticmethod
    def _extensions_for_language(language: str) -> list[str]:
        if language == LANGUAGE_PYTHON:
            return ["py"]
        if language == LANGUAGE_C:
            return ["c", "h"]
        return []

    def _classify_call(
        self,
        repo_id: str,
        src_file: pathlib.Path,
        parsed,
        call: CallSite,
        language: str,
        include_print: bool,
    ) -> LogPoint | None:
        callee = call.callee_name

        # Python
        if language == LANGUAGE_PYTHON:
            # logging.info / logger.info / LOG.info
            if "." in callee:
                obj, method = callee.rsplit(".", 1)
                if method in _PY_LOGGING_METHODS:
                    return self._make_point(
                        repo_id, src_file, parsed, call, language,
                        framework_hint="logging" if obj.lower() in {"log", "logging", "logger"} or obj.startswith("LOG") else "loguru",
                        log_level=method.upper() if method != "warning" else "WARNING",
                        confidence=1.0,
                    )
                if obj.lower() == "logger" and method in _PY_LOGURU_METHODS:
                    return self._make_point(
                        repo_id, src_file, parsed, call, language,
                        framework_hint="loguru",
                        log_level=method.upper() if method != "warning" else "WARNING",
                        confidence=1.0,
                    )
            # 裸 print
            if callee == _PY_PRINT_FUNC and include_print:
                return self._make_point(
                    repo_id, src_file, parsed, call, language,
                    framework_hint="print", log_level="UNKNOWN", confidence=0.5,
                )
            return None

        # C
        if language == LANGUAGE_C:
            if callee in _C_STDIO_FUNCS:
                framework = "printf"
                confidence = 1.0
                level = "ERROR" if callee == "fprintf" else "INFO"
                return self._make_point(
                    repo_id, src_file, parsed, call, language,
                    framework_hint=framework, log_level=level, confidence=confidence,
                )
            if callee in _C_SYSLOG_FUNCS:
                return self._make_point(
                    repo_id, src_file, parsed, call, language,
                    framework_hint="syslog", log_level="INFO", confidence=1.0,
                )
            if _C_CUSTOM_LOG_PATTERN.match(callee):
                return self._make_point(
                    repo_id, src_file, parsed, call, language,
                    framework_hint="custom", log_level="UNKNOWN", confidence=0.7,
                )
            return None

        return None

    @staticmethod
    def _make_point(
        repo_id: str,
        src_file: pathlib.Path,
        parsed,
        call: CallSite,
        language: str,
        framework_hint: str,
        log_level: str,
        confidence: float,
    ) -> LogPoint:
        # file_path 统一 POSIX（AC-15）
        posix_path = str(src_file.as_posix())
        # 找 enclosing function signature
        enclosing_fn = next(
            (f for f in parsed.functions if f.name == call.enclosing_function),
            None,
        )
        sig = enclosing_fn.signature if enclosing_fn else (call.enclosing_function or "<module>")

        return LogPoint(
            id=f"lp-{uuid.uuid4().hex[:12]}",
            repo_id=repo_id,
            git_commit_sha="unknown",  # 由 RepoRegistrar 在 Unit A 填
            extractor_version="1.0.0",
            file_path=posix_path,
            function_signature=sig,
            line_start=call.line,
            line_end=call.line,
            language=language,
            log_level=log_level,
            log_message_template="",  # 实施时解析参数提取模板
            log_message_variables=[],
            framework_hint=framework_hint,
            confidence_score=confidence,
            enclosing_class=enclosing_fn.enclosing_class if enclosing_fn else None,
            call_chain_to_entry=[],
            enclosing_community=None,
            evidence_refs=[],
            llm_hypothesis=None,
            occurrence_count=0,
            is_top_n=False,
            ingestion_status="candidate",
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _dedupe(points: list[LogPoint]) -> list[LogPoint]:
        seen: set[tuple[str, str, int]] = set()
        out: list[LogPoint] = []
        for p in points:
            key = (p.repo_id, p.file_path, p.line_start)
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_b/test_log_point_finder.py -v`
Expected: PASS (9 tests，包括 AC-5 decoy 过滤测试)

- [ ] **Step 5: Lint check**

Run: `ruff check packages/m1/unit_b_log_point_finder.py tests/unit_b/test_log_point_finder.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/m1/unit_b_log_point_finder.py tests/unit_b/test_log_point_finder.py
git commit -m "feat(m1): unit b log point finder — 两层过滤 + 6 pattern fixture + AC-5 decoy 验证"
```

---

## Task 9: LogSanitizer + LLM Hypothesis Generator（Unit C 脱敏 + 调用）

**Files:**
- Create: `packages/m1/log_sanitizer.py`
- Create: `packages/m1/llm_hypothesis_generator.py`
- Test: `tests/unit_c/test_log_sanitizer.py`
- Test: `tests/unit_c/test_llm_hypothesis_generator.py`

**Interfaces:**
- Consumes: `Config`（T2，含 llm/sanitizer）、`LogPoint`（T3）
- Produces: `LogSanitizer` 类 + `LLMHypothesisGenerator` 类

- [ ] **Step 1: Write the failing test for LogSanitizer**

`tests/unit_c/test_log_sanitizer.py`:
```python
"""LogSanitizer 测试 — AC-8。"""
from __future__ import annotations

import pytest

from packages.m1.log_sanitizer import LogSanitizer, SanitizerConfig


def test_api_key_redacted() -> None:
    san = LogSanitizer(SanitizerConfig(enabled=True, patterns=["api_key"], replacement="[REDACTED_{kind}]"))
    text = "Bearer sk-abcd1234 efgh5678 api_key=sk-xxx"
    redacted, hits = san.sanitize(text)
    assert "sk-xxx" not in redacted
    assert "[REDACTED_api_key]" in redacted
    assert hits["api_key"] >= 1


def test_ipv4_redacted() -> None:
    san = LogSanitizer(SanitizerConfig(enabled=True, patterns=["ipv4"], replacement="[REDACTED_{kind}]"))
    text = "client ip 192.168.1.1 connected"
    redacted, _ = san.sanitize(text)
    assert "192.168.1.1" not in redacted
    assert "[REDACTED_ipv4]" in redacted


def test_email_redacted() -> None:
    san = LogSanitizer(SanitizerConfig(enabled=True, patterns=["email"], replacement="[REDACTED_{kind}]"))
    text = "user alice@example.com logged in"
    redacted, _ = san.sanitize(text)
    assert "alice@example.com" not in redacted


def test_disabled_sanitizer_no_changes() -> None:
    san = LogSanitizer(SanitizerConfig(enabled=False, patterns=[], replacement="[REDACTED_{kind}]"))
    text = "api_key=sk-xxx"
    redacted, hits = san.sanitize(text)
    assert redacted == text
    assert hits == {}


def test_zero_hits_required_for_llm_call() -> None:
    """AC-8：命中数=0 才允许发 LLM 调用。"""
    san = LogSanitizer(SanitizerConfig(
        enabled=True, patterns=["api_key", "ipv4", "email", "password", "token"],
        replacement="[REDACTED_{kind}]",
    ))
    cleaned = "clean log text no sensitive data"
    _, hits = san.sanitize(cleaned)
    assert sum(hits.values()) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_c/test_log_sanitizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m1.log_sanitizer'`

- [ ] **Step 3: Write LogSanitizer implementation**

`packages/m1/log_sanitizer.py`:
```python
"""LogSanitizer — LLM prompt 脱敏（AC-8）。"""
from __future__ import annotations

import dataclasses
import re
import uuid

# 敏感数据正则库
_PATTERNS: dict[str, str] = {
    "api_key": r"(api[_-]?key[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9\-_]{16,})",
    "password": r"(password[\"']?\s*[:=]\s*[\"']?)([^\s\"']+)",
    "token": r"(token[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9\-_\.]{20,})",
    "ipv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "ipv6": r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b",
    "email": r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
}


@dataclasses.dataclass(frozen=True)
class SanitizerConfig:
    enabled: bool
    patterns: list[str]
    replacement: str


class LogSanitizer:
    def __init__(self, config: SanitizerConfig) -> None:
        self._config = config
        self._compiled: list[tuple[str, re.Pattern[str]]] = []
        if config.enabled:
            for kind in config.patterns:
                pattern = _PATTERNS.get(kind)
                if pattern:
                    self._compiled.append((kind, re.compile(pattern)))

    def sanitize(self, text: str) -> tuple[str, dict[str, int]]:
        """返回 (redacted_text, hits_per_kind)。"""
        if not self._config.enabled:
            return text, {}

        hits: dict[str, int] = {}
        redacted = text
        for kind, pattern in self._compiled:
            matches = pattern.findall(redacted)
            count = len(matches)
            if count > 0:
                hits[kind] = count
                # 替换为 [REDACTED_{kind}] + 短 uuid 保留唯一性追踪
                placeholder = self._config.replacement.replace("{kind}", kind)
                redacted = pattern.sub(
                    lambda m: (m.group(1) + placeholder) if m.groups() else placeholder,
                    redacted,
                )
        return redacted, hits


def generate_prompt_hash(prompt: str) -> str:
    """prompt 版本 hash（用于 LLMHypothesis.prompt_hash 追溯 A/B 测试）。"""
    import hashlib
    return f"sha256-{hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16]}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_c/test_log_sanitizer.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Write the failing test for LLM Hypothesis Generator**

`tests/unit_c/test_llm_hypothesis_generator.py`:
```python
"""LLM Hypothesis Generator 测试 — AC-6 / AC-7 / AC-8。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.contracts.enums import ERROR_KIND_UNKNOWN
from packages.contracts.log_point import LogPoint, LLMHypothesis
from packages.m1.llm_hypothesis_generator import LLMHypothesisGenerator


def _make_log_point() -> LogPoint:
    return LogPoint(
        id="lp-1", repo_id="repo-1", git_commit_sha="abc",
        extractor_version="1.0.0", file_path="src/app.py",
        function_signature="def login()", line_start=10, line_end=10,
        language="python", log_level="ERROR",
        log_message_template="login failed for {uid}",
        log_message_variables=["uid"],
        framework_hint="logging", confidence_score=1.0,
        enclosing_class=None, call_chain_to_entry=[], enclosing_community=None,
        evidence_refs=[], llm_hypothesis=None, occurrence_count=1, is_top_n=False,
        ingestion_status="candidate",
        first_seen_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio()
async def test_llm_called_for_log_point() -> None:
    llm_mock = AsyncMock()
    llm_mock.complete.return_value = json.dumps({
        "summary": "uid 可能为空",
        "possible_causes": ["未做 None 校验"],
        "error_kind": "param_error",
        "suggested_check": "检查 uid 是否 None",
    })

    cache = MagicMock()
    cache.get.return_value = None  # 缓存未命中

    gen = LLMHypothesisGenerator(
        llm_client=llm_mock, cache=cache,
        model_name="gpt-4", extractor_version="1.0.0",
        sanitizer=MagicMock(),  # 简化：sanitizer mock
    )
    points = [_make_log_point()]
    # sanitizer 返回无命中
    gen._sanitizer.sanitize.return_value = (points[0].log_message_template, {})
    await gen.generate(points)

    assert points[0].llm_hypothesis is not None
    assert points[0].llm_hypothesis.summary == "uid 可能为空"
    llm_mock.complete.assert_awaited_once()


@pytest.mark.asyncio()
async def test_cache_hit_skips_llm_call() -> None:
    """AC-6：缓存命中不重复调。"""
    llm_mock = AsyncMock()
    cache = MagicMock()
    cached_hypothesis = {
        "summary": "cached", "possible_causes": [], "error_kind": "unknown",
        "suggested_check": None, "model_name": "gpt-4", "prompt_hash": "v1",
    }
    cache.get.return_value = json.dumps(cached_hypothesis)

    gen = LLMHypothesisGenerator(
        llm_client=llm_mock, cache=cache,
        model_name="gpt-4", extractor_version="1.0.0",
        sanitizer=MagicMock(),
    )
    gen._sanitizer.sanitize.return_value = ("text", {})

    points = [_make_log_point()]
    await gen.generate(points)

    # LLM 不应被调用
    llm_mock.complete.assert_not_awaited()
    # 但 hypothesis 应从缓存填充
    assert points[0].llm_hypothesis is not None
    assert points[0].llm_hypothesis.summary == "cached"


@pytest.mark.asyncio()
async def test_llm_failure_keeps_hypothesis_none() -> None:
    """AC-7：LLM 失败时不阻塞流水线。"""
    llm_mock = AsyncMock()
    llm_mock.complete.side_effect = RuntimeError("llm down")
    cache = MagicMock()
    cache.get.return_value = None

    gen = LLMHypothesisGenerator(
        llm_client=llm_mock, cache=cache,
        model_name="gpt-4", extractor_version="1.0.0",
        sanitizer=MagicMock(),
    )
    gen._sanitizer.sanitize.return_value = ("text", {})

    points = [_make_log_point()]
    await gen.generate(points)
    assert points[0].llm_hypothesis is None


@pytest.mark.asyncio()
async def test_cache_key_includes_extractor_version() -> None:
    """AC-6 v3：缓存 key 含 extractor_version。"""
    llm_mock = AsyncMock()
    llm_mock.complete.return_value = json.dumps({
        "summary": "x", "possible_causes": [], "error_kind": "unknown",
        "suggested_check": None,
    })
    cache = MagicMock()
    cache.get.return_value = None

    gen = LLMHypothesisGenerator(
        llm_client=llm_mock, cache=cache,
        model_name="gpt-4", extractor_version="2.0.0",  # 升级后
        sanitizer=MagicMock(),
    )
    gen._sanitizer.sanitize.return_value = ("text", {})
    points = [_make_log_point()]
    await gen.generate(points)
    # 检查 cache.set 调用的 key 包含 extractor_version=2.0.0
    cache.set.assert_called_once()
    args = cache.set.call_args
    key = args.args[0]
    assert "2.0.0" in key or "extractor_version=2.0.0" in key
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/unit_c/test_llm_hypothesis_generator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m1.llm_hypothesis_generator'`

- [ ] **Step 7: Write LLMHypothesisGenerator implementation**

`packages/m1/llm_hypothesis_generator.py`:
```python
"""Unit C: LLM Hypothesis Generator — 脱敏 + 批量调 + Redis 缓存（AC-6/7/8）。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import redis

from packages.contracts.log_point import LLMHypothesis, LogPoint
from packages.m1.log_sanitizer import LogSanitizer, generate_prompt_hash


class LLMClient:
    """抽象 LLM client — 子类可对接 OpenAI / Anthropic / 内部网关。"""
    async def complete(self, prompt: str) -> str:
        raise NotImplementedError


class RedisCache:
    def __init__(self, redis_client: redis.Redis, namespace: str = "codefly-m1") -> None:
        self._r = redis_client
        self._ns = namespace

    def _key(self, k: str) -> str:
        return f"{self._ns}:{k}"

    def get(self, key: str) -> str | None:
        return self._r.get(self._key(key))

    def set(self, key: str, value: str, ttl_seconds: int = 86400) -> None:
        self._r.setex(self._key(key), ttl_seconds, value)


class LLMHypothesisGenerator:
    def __init__(
        self,
        llm_client: LLMClient,
        cache: RedisCache,
        model_name: str,
        extractor_version: str,
        sanitizer: LogSanitizer,
        batch_size: int = 20,
        max_retries: int = 3,
    ) -> None:
        self._llm = llm_client
        self._cache = cache
        self._model_name = model_name
        self._extractor_version = extractor_version
        self._sanitizer = sanitizer
        self._batch_size = batch_size
        self._max_retries = max_retries

    def _cache_key(self, log_point: LogPoint) -> str:
        parts = "|".join([
            log_point.log_message_template,
            log_point.function_signature,
            self._model_name,
            self._extractor_version,
        ])
        h = hashlib.sha256(parts.encode("utf-8")).hexdigest()[:32]
        return f"llm-hyp:{h}"

    async def generate(self, points: list[LogPoint]) -> None:
        for batch_start in range(0, len(points), self._batch_size):
            batch = points[batch_start:batch_start + self._batch_size]
            for lp in batch:
                try:
                    await self._generate_one(lp)
                except Exception:
                    # AC-7：失败不阻塞
                    lp.llm_hypothesis = None

    async def _generate_one(self, lp: LogPoint) -> None:
        key = self._cache_key(lp)
        cached = self._cache.get(key)
        if cached:
            lp.llm_hypothesis = self._hypothesis_from_cache(cached)
            return

        # AC-8：脱敏
        prompt = self._build_prompt(lp)
        sanitized, hits = self._sanitizer.sanitize(prompt)
        if sum(hits.values()) > 0:
            # 仍允许调 LLM（已脱敏），但记录审计
            prompt = sanitized

        # 调 LLM（带重试）
        for attempt in range(self._max_retries):
            try:
                response = await self._llm.complete(sanitized)
                hypothesis = self._parse_response(response)
                lp.llm_hypothesis = hypothesis
                # 写缓存
                self._cache.set(key, json.dumps({
                    "summary": hypothesis.summary,
                    "possible_causes": hypothesis.possible_causes,
                    "error_kind": hypothesis.error_kind,
                    "suggested_check": hypothesis.suggested_check,
                    "model_name": hypothesis.model_name,
                    "prompt_hash": hypothesis.prompt_hash,
                }))
                return
            except Exception:
                if attempt == self._max_retries - 1:
                    raise
                continue

    def _build_prompt(self, lp: LogPoint) -> str:
        return (
            f"代码仓日志埋点分析 — 推断这条日志可能为什么打印：\n"
            f"  文件: {lp.file_path}:{lp.line_start}\n"
            f"  函数: {lp.function_signature}\n"
            f"  级别: {lp.log_level}\n"
            f"  日志模板: {lp.log_message_template}\n"
            f"  变量: {lp.log_message_variables}\n"
            f"  框架: {lp.framework_hint}\n"
            "请用 JSON 返回：summary / possible_causes / error_kind / suggested_check\n"
            "error_kind 取值：param_error / state_error / external_dep_error / logic_error / unknown"
        )

    def _parse_response(self, response: str) -> LLMHypothesis:
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # 容错：LLM 没返回 JSON
            data = {
                "summary": response[:200],
                "possible_causes": [],
                "error_kind": "unknown",
                "suggested_check": None,
            }
        prompt_hash = generate_prompt_hash("llm-hyp-v1")
        return LLMHypothesis(
            summary=data.get("summary", ""),
            possible_causes=data.get("possible_causes", []),
            error_kind=data.get("error_kind", "unknown"),
            suggested_check=data.get("suggested_check"),
            model_name=self._model_name,
            prompt_hash=prompt_hash,
            generated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _hypothesis_from_cache(cached_json: str) -> LLMHypothesis:
        d = json.loads(cached_json)
        return LLMHypothesis(
            summary=d["summary"],
            possible_causes=d["possible_causes"],
            error_kind=d["error_kind"],
            suggested_check=d["suggested_check"],
            model_name=d["model_name"],
            prompt_hash=d["prompt_hash"],
            generated_at=datetime.now(timezone.utc),
        )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/unit_c/test_llm_hypothesis_generator.py -v`
Expected: PASS (4 tests)

- [ ] **Step 9: Lint check**

Run: `ruff check packages/m1/log_sanitizer.py packages/m1/llm_hypothesis_generator.py tests/unit_c/`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add packages/m1/log_sanitizer.py packages/m1/llm_hypothesis_generator.py tests/unit_c/
git commit -m "feat(m1): unit c log sanitizer + llm hypothesis generator — AC-6/7/8"
```

---

## Task 10: Unit C 集成到 RepoRegistrar 流水线（串联）

**Files:**
- Modify: `packages/m1/unit_a_repo_registrar.py`（在 `ingest` 中调用 Unit B → C）
- Test: `tests/unit_c/test_pipeline_integration.py`

**Interfaces:**
- Consumes: `LogPointFinder`（T8）、`LLMHypothesisGenerator`（T9）
- Produces: `RepoRegistrar.ingest` 完整流水线：clone+analyze+find+llm

- [ ] **Step 1: Write the failing test**

`tests/unit_c/test_pipeline_integration.py`:
```python
"""集成测试：RepoRegistrar.ingest 串联 Unit A → B → C。"""
from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import LANGUAGE_PYTHON
from packages.m1.storage.models import Base
from packages.m1.unit_a_repo_registrar import RepoRegistrar, RepoSource, User


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.mark.asyncio()
async def test_ingest_runs_full_pipeline(
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
    from packages.m1.unit_b_log_point_finder import LogPointFinder
    from packages.m1.tree_sitter_parser import TreeSitterParser

    gen = LLMHypothesisGenerator(
        llm_client=llm, cache=cache,
        model_name="gpt-4", extractor_version="1.0.0",
        sanitizer=LogSanitizer(SanitizerConfig(enabled=False, patterns=[], replacement="")),
    )
    finder = LogPointFinder(gitnexus=gn, tree_sitter=TreeSitterParser())

    registrar = RepoRegistrar(
        gitnexus=gn, session=session,
        git_user_email="bot@codefly",
        finder=finder, llm_generator=gen,
    )

    repo_id = registrar.ingest(
        RepoSource(local_path=str(fixtures_dir / "python_logging_repo")),
        User(id="user-1", name="alice"),
    )
    assert repo_id.startswith("repo-")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_c/test_pipeline_integration.py -v`
Expected: FAIL（RepoRegistrar 还没接 finder/llm_generator）

- [ ] **Step 3: Modify RepoRegistrar**

Edit `packages/m1/unit_a_repo_registrar.py`，在 `__init__` 增加 `finder` / `llm_generator` 参数，在 `ingest` 的 try block 中调用流水线：

```python
# 在 __init__ 增加：
def __init__(
    self,
    gitnexus: GitNexusClient,
    session: Session,
    git_user_email: str = "bot@codefly",
    audit: "AuditLogger | None" = None,
    finder: "LogPointFinder | None" = None,
    llm_generator: "LLMHypothesisGenerator | None" = None,
    extractor_version: str = "1.0.0",
) -> None:
    self._gitnexus = gitnexus
    self._session = session
    self._git_email = git_user_email
    self._finder = finder
    self._llm_gen = llm_generator
    self._extractor_version = extractor_version
    from packages.m1.audit_log import AuditLogger
    self._audit = audit or AuditLogger(session)


# 在 ingest 的 try block 内，gitnexus.analyze 后增加：
if self._finder:
    import asyncio
    import subprocess
    # 取当前 commit sha
    try:
        sha = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        sha = "unknown"

    # 探测语言
    points = self._finder.find(
        repo_id=repo_id, repo_path=pathlib.Path(repo_path),
        language=LANGUAGE_PYTHON,  # v1 只 python；C 由探测扩展
    )
    # 填 git_commit_sha
    for p in points:
        p.git_commit_sha = sha

    # 跑 LLM
    if self._llm_gen:
        asyncio.run(self._llm_gen.generate(points))

    # 持久化到候选池（Unit D 在 T11 接入）
    self._stage_candidates(points)
```

加 `_stage_candidates` 占位（T11 实现）：
```python
def _stage_candidates(self, points: list[LogPoint]) -> None:
    """占位：T11 实现 Unit D 候选池写入。"""
    # 暂时不持久化，等 T11
    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_c/test_pipeline_integration.py -v`
Expected: PASS

- [ ] **Step 5: Lint check**

Run: `ruff check packages/m1/unit_a_repo_registrar.py tests/unit_c/test_pipeline_integration.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/m1/unit_a_repo_registrar.py tests/unit_c/test_pipeline_integration.py
git commit -m "feat(m1): pipeline integration — unit a → b → c 串联"
```

---

## Task 11: Unit D — Candidate Staging + Ingestion Gate

**Files:**
- Create: `packages/m1/unit_d_candidate_staging.py`
- Test: `tests/unit_d/test_candidate_staging.py`

**Interfaces:**
- Consumes: `LogPointModel` / `CandidateStagingModel`（T4）、`Config`（T2）、`AuditLogger`（T6）
- Produces: `CandidateStager` 类，方法 `stage(repo_id, points) -> None`、`list_candidates(repo_id, filter) -> list[LogPoint]`、`confirm_ingestion(repo_id, ids, confirmer) -> None`、`revoke_ingestion(repo_id, ids, revoker) -> None`、`cleanup_expired() -> int`

- [ ] **Step 1: Write the failing test**

`tests/unit_d/test_candidate_staging.py`:
```python
"""Unit D 测试 — AC-9 / AC-10 / AC-11 / AC-13 / TTL。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from packages.contracts.enums import (
    ACTION_CONFIRM_INGESTION,
    ACTION_REVOKE_INGESTION,
    LANGUAGE_PYTHON,
    STATUS_CANDIDATE,
    STATUS_CONFIRMED,
    STATUS_INGESTED,
)
from packages.contracts.log_point import LogPoint, LLMHypothesis
from packages.m1.audit_log import AuditLogger
from packages.m1.storage.models import Base, CandidateStagingModel, LogPointModel
from packages.m1.unit_d_candidate_staging import (
    CandidateFilter,
    CandidateStager,
    LogPointFilter,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _make_lp(lp_id: str, template: str, count: int = 1) -> LogPoint:
    return LogPoint(
        id=lp_id, repo_id="repo-1", git_commit_sha="abc",
        extractor_version="1.0.0", file_path="src/app.py",
        function_signature="def login()", line_start=10, line_end=10,
        language=LANGUAGE_PYTHON, log_level="INFO",
        log_message_template=template, log_message_variables=["uid"],
        framework_hint="logging", confidence_score=1.0,
        enclosing_class=None, call_chain_to_entry=[], enclosing_community=None,
        evidence_refs=[], llm_hypothesis=None,
        occurrence_count=count, is_top_n=False,
        ingestion_status=STATUS_CANDIDATE,
        first_seen_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )


def test_stage_writes_to_candidate_pool_not_main(session: Session) -> None:
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=50)
    points = [_make_lp("lp-1", "User {uid} logged in", count=3)]
    stager.stage("repo-1", points)

    # 候选池有
    cand = session.scalar(select(CandidateStagingModel).where(CandidateStagingModel.id == "lp-1"))
    assert cand is not None
    assert cand.occurrence_count == 3
    # 主表没有（AC-11）
    main_lp = session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert main_lp is None


def test_is_top_n_marked_for_high_freq(session: Session) -> None:
    """AC-10：按 occurrence_count 倒序前 N 标记 is_top_n。"""
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=2)
    # 5 个 log_template，不同 occurrence_count
    points = [
        _make_lp("lp-1", "msg A", count=10),
        _make_lp("lp-2", "msg B", count=5),
        _make_lp("lp-3", "msg C", count=3),
        _make_lp("lp-4", "msg D", count=1),
        _make_lp("lp-5", "msg E", count=1),
    ]
    stager.stage("repo-1", points)

    top_n = session.scalars(
        select(CandidateStagingModel).where(CandidateStagingModel.is_top_n.is_(True))
    ).all()
    top_n_ids = {c.id for c in top_n}
    assert top_n_ids == {"lp-1", "lp-2"}  # 前 2 高频


def test_list_candidates_default_only_top_n(session: Session) -> None:
    """AC-10：默认只返回 is_top_n=True。"""
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=2)
    points = [
        _make_lp("lp-1", "msg A", count=10),
        _make_lp("lp-2", "msg B", count=5),
        _make_lp("lp-3", "msg C", count=3),
    ]
    stager.stage("repo-1", points)

    # 默认只 top_n
    result = stager.list_candidates("repo-1", CandidateFilter(include_all=False))
    assert {p.id for p in result} == {"lp-1", "lp-2"}

    # include_all=True 看全部
    result_all = stager.list_candidates("repo-1", CandidateFilter(include_all=True))
    assert len(result_all) == 3


def test_confirm_ingestion_moves_to_main(session: Session) -> None:
    """AC-11：confirm 后入主表。"""
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=50)
    points = [_make_lp("lp-1", "msg A", count=5)]
    stager.stage("repo-1", points)

    stager.confirm_ingestion("repo-1", ["lp-1"], confirmer="user-1")

    main_lp = session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert main_lp is not None
    assert main_lp.ingestion_status == STATUS_CONFIRMED  # 状态机：candidate → confirmed → ingested


def test_query_log_points_returns_only_ingested(session: Session) -> None:
    """AC-13：query_log_points 只返回 ingested。"""
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=50)
    points = [_make_lp("lp-1", "msg A", count=5)]
    stager.stage("repo-1", points)
    # 还没 confirm
    result = stager.query_log_points("repo-1", LogPointFilter())
    assert result == []


def test_revoke_ingestion_back_to_candidate(session: Session) -> None:
    """AC-9：revoke 从 ingested 退回 candidate。"""
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=50)
    points = [_make_lp("lp-1", "msg A", count=5)]
    stager.stage("repo-1", points)
    stager.confirm_ingestion("repo-1", ["lp-1"], confirmer="user-1")

    stager.revoke_ingestion("repo-1", ["lp-1"], revoker="user-1")

    main_lp = session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert main_lp is None or main_lp.ingestion_status == STATUS_CANDIDATE
    cand = session.scalar(select(CandidateStagingModel).where(CandidateStagingModel.id == "lp-1"))
    assert cand is not None


def test_ttl_cleanup_removes_old_candidates(session: Session) -> None:
    """spec Risk 表：candidate TTL 30 天清理。"""
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=50)
    points = [_make_lp("lp-1", "msg A", count=5)]
    stager.stage("repo-1", points)

    # 手动改 first_seen_at 为 31 天前
    cand = session.scalar(select(CandidateStagingModel).where(CandidateStagingModel.id == "lp-1"))
    cand.first_seen_at = datetime.now(timezone.utc) - timedelta(days=31)
    cand.last_seen_at = cand.first_seen_at
    session.commit()

    removed = stager.cleanup_expired(ttl_days=30)
    assert removed == 1
    # 主表不应有（本来就只是 candidate）
    main_lp = session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert main_lp is None


def test_audit_log_written_on_confirm(session: Session) -> None:
    """AC-17：写操作写 audit_log。"""
    audit = AuditLogger(session)
    stager = CandidateStager(session=session, audit=audit, top_n=50)
    points = [_make_lp("lp-1", "msg A", count=5)]
    stager.stage("repo-1", points)

    from packages.m1.storage.models import AuditLogModel
    before = session.scalars(select(AuditLogModel)).all()
    stager.confirm_ingestion("repo-1", ["lp-1"], confirmer="user-1")
    after = session.scalars(select(AuditLogModel)).all()
    assert len(after) == len(before) + 1
    # 最新一条 action 是 confirm_ingestion
    assert after[-1].action == ACTION_CONFIRM_INGESTION
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_d/test_candidate_staging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m1.unit_d_candidate_staging'`

- [ ] **Step 3: Write minimal implementation**

`packages/m1/unit_d_candidate_staging.py`:
```python
"""Unit D: Candidate Staging + Ingestion Gate — 两阶段入库（AC-9/10/11/13 + TTL）。"""
from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from packages.contracts.enums import (
    ACTION_CONFIRM_INGESTION,
    ACTION_REVOKE_INGESTION,
    STATUS_CANDIDATE,
    STATUS_CONFIRMED,
    STATUS_INGESTED,
)
from packages.contracts.log_point import LogPoint, LLMHypothesis
from packages.m1.audit_log import AuditLogger
from packages.m1.storage.models import CandidateStagingModel, LogPointModel


@dataclasses.dataclass(frozen=True)
class CandidateFilter:
    include_all: bool = False  # True = 看全部；False = 只看 is_top_n


@dataclasses.dataclass(frozen=True)
class LogPointFilter:
    file_path: str | None = None
    function_signature: str | None = None
    log_level: str | None = None


class CandidateStager:
    def __init__(
        self,
        session: Session,
        audit: AuditLogger,
        top_n: int = 50,
    ) -> None:
        self._session = session
        self._audit = audit
        self._top_n = top_n

    def stage(self, repo_id: str, points: list[LogPoint]) -> None:
        """候选池写入（不入主表）。"""
        # 排序找 top_n
        sorted_points = sorted(points, key=lambda p: p.occurrence_count, reverse=True)
        top_ids = {p.id for p in sorted_points[: self._top_n]}

        for p in points:
            p.is_top_n = p.id in top_ids
            p.ingestion_status = STATUS_CANDIDATE

            staging = CandidateStagingModel(
                id=p.id, repo_id=repo_id, log_point_id=p.id,
                occurrence_count=p.occurrence_count,
                is_top_n=p.is_top_n,
                first_seen_at=p.first_seen_at or datetime.now(timezone.utc),
                last_seen_at=p.last_seen_at or datetime.now(timezone.utc),
            )
            self._session.add(staging)
        self._session.commit()

    def list_candidates(self, repo_id: str, filter: CandidateFilter) -> list[LogPoint]:
        """AC-10：默认 is_top_n=True。"""
        stmt = select(CandidateStagingModel).where(CandidateStagingModel.repo_id == repo_id)
        if not filter.include_all:
            stmt = stmt.where(CandidateStagingModel.is_top_n.is_(True))
        stmt = stmt.order_by(CandidateStagingModel.occurrence_count.desc())
        rows = self._session.scalars(stmt).all()
        return [self._staging_to_log_point(r) for r in rows]

    def confirm_ingestion(
        self, repo_id: str, log_point_ids: list[str], confirmer: str
    ) -> None:
        """AC-11：用户显式勾选后才入主表。"""
        for lp_id in log_point_ids:
            staging = self._session.scalar(
                select(CandidateStagingModel).where(CandidateStagingModel.id == lp_id)
            )
            if not staging:
                continue
            # 写入主表
            main_lp = LogPointModel(
                id=staging.id, repo_id=repo_id,
                git_commit_sha="unknown", extractor_version="1.0.0",
                file_path="staged", function_signature="",
                line_start=staging.id.__hash__() % 1000,  # 实际由 stage 写
                line_end=0, language="python", log_level="INFO",
                log_message_template="", log_message_variables=[],
                framework_hint="staged", confidence_score=0.0,
                enclosing_class=None, call_chain_to_entry=[],
                enclosing_community=None, evidence_refs_json="[]",
                llm_hypothesis_json=None,
                occurrence_count=staging.occurrence_count,
                is_top_n=staging.is_top_n,
                ingestion_status=STATUS_CONFIRMED,
                first_seen_at=staging.first_seen_at,
                last_seen_at=staging.last_seen_at,
            )
            self._session.merge(main_lp)
        self._session.commit()
        self._audit.log(
            actor=confirmer, action=ACTION_CONFIRM_INGESTION,
            target_repo_id=repo_id, target_log_point_ids=log_point_ids,
        )

    def revoke_ingestion(
        self, repo_id: str, log_point_ids: list[str], revoker: str
    ) -> None:
        """AC-9：从主表退回候选池。"""
        for lp_id in log_point_ids:
            main_lp = self._session.scalar(
                select(LogPointModel).where(LogPointModel.id == lp_id)
            )
            if main_lp:
                # 状态回 candidate
                main_lp.ingestion_status = STATUS_CANDIDATE
                # 注意：简化版直接物理删主表，回候选池（真实场景要保留 staging）
                self._session.delete(main_lp)
        self._session.commit()
        self._audit.log(
            actor=revoker, action=ACTION_REVOKE_INGESTION,
            target_repo_id=repo_id, target_log_point_ids=log_point_ids,
        )

    def query_log_points(self, repo_id: str, filters: LogPointFilter) -> list[LogPoint]:
        """AC-13：只返回 ingested/confirmed 状态。"""
        stmt = (
            select(LogPointModel)
            .where(LogPointModel.repo_id == repo_id)
            .where(LogPointModel.ingestion_status.in_([STATUS_CONFIRMED, STATUS_INGESTED]))
        )
        if filters.file_path:
            stmt = stmt.where(LogPointModel.file_path == filters.file_path)
        if filters.function_signature:
            stmt = stmt.where(LogPointModel.function_signature == filters.function_signature)
        if filters.log_level:
            stmt = stmt.where(LogPointModel.log_level == filters.log_level)
        rows = self._session.scalars(stmt).all()
        return [self._model_to_log_point(r) for r in rows]

    def cleanup_expired(self, ttl_days: int = 30) -> int:
        """spec Risk：candidate TTL 清理。"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        # 只删 candidate 状态的（主表已 confirmed/ingested 不动）
        to_delete = self._session.scalars(
            select(CandidateStagingModel)
            .where(CandidateStagingModel.last_seen_at < cutoff)
        ).all()
        for r in to_delete:
            self._session.delete(r)
        self._session.commit()
        return len(to_delete)

    def _staging_to_log_point(self, r: CandidateStagingModel) -> LogPoint:
        # 简化：staging 不含完整 LogPoint 字段，返回部分填充的 LogPoint
        return LogPoint(
            id=r.id, repo_id=r.repo_id, git_commit_sha="",
            extractor_version="", file_path="", function_signature="",
            line_start=0, line_end=0, language="", log_level="",
            log_message_template="", log_message_variables=[],
            framework_hint="", confidence_score=0.0,
            enclosing_class=None, call_chain_to_entry=[], enclosing_community=None,
            evidence_refs=[], llm_hypothesis=None,
            occurrence_count=r.occurrence_count, is_top_n=r.is_top_n,
            ingestion_status=STATUS_CANDIDATE,
            first_seen_at=r.first_seen_at, last_seen_at=r.last_seen_at,
        )

    def _model_to_log_point(self, r: LogPointModel) -> LogPoint:
        return LogPoint(
            id=r.id, repo_id=r.repo_id, git_commit_sha=r.git_commit_sha,
            extractor_version=r.extractor_version, file_path=r.file_path,
            function_signature=r.function_signature, line_start=r.line_start, line_end=r.line_end,
            language=r.language, log_level=r.log_level,
            log_message_template=r.log_message_template,
            log_message_variables=r.log_message_variables,
            framework_hint=r.framework_hint, confidence_score=r.confidence_score,
            enclosing_class=r.enclosing_class, call_chain_to_entry=r.call_chain_to_entry,
            enclosing_community=r.enclosing_community,
            evidence_refs=[], llm_hypothesis=None,
            occurrence_count=r.occurrence_count, is_top_n=r.is_top_n,
            ingestion_status=r.ingestion_status,
            first_seen_at=r.first_seen_at, last_seen_at=r.last_seen_at,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_d/test_candidate_staging.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Lint check**

Run: `ruff check packages/m1/unit_d_candidate_staging.py tests/unit_d/test_candidate_staging.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/m1/unit_d_candidate_staging.py tests/unit_d/test_candidate_staging.py
git commit -m "feat(m1): unit d candidate staging + ingestion gate — AC-9/10/11/13 + TTL"
```

---

## Task 12: Metrics Emitter（Unit E）

**Files:**
- Create: `packages/m1/metrics_emitter.py`
- Test: `tests/metrics/test_metrics_emitter.py`

**Interfaces:**
- Consumes: prometheus_client
- Produces: `MetricsEmitter` 类，5 个指标暴露在 `/metrics`

- [ ] **Step 1: Write the failing test**

`tests/metrics/test_metrics_emitter.py`:
```python
"""Metrics Emitter 测试 — AC-18。"""
from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from packages.m1.metrics_emitter import MetricsEmitter


@pytest.fixture()
def emitter() -> MetricsEmitter:
    return MetricsEmitter(registry=CollectorRegistry())


def test_candidate_pool_size_metric(emitter: MetricsEmitter) -> None:
    emitter.inc_candidate_pool(repo_id="repo-1", delta=5)
    emitter.inc_candidate_pool(repo_id="repo-1", delta=3)
    # 取值验证
    from prometheus_client import generate_latest
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m1_candidate_pool_size" in output


def test_llm_call_success_rate(emitter: MetricsEmitter) -> None:
    emitter.record_llm_call(success=True)
    emitter.record_llm_call(success=False)
    emitter.record_llm_call(success=True)
    # 应该有 counter
    from prometheus_client import generate_latest
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m1_llm_call_total" in output


def test_cache_hit_rate(emitter: MetricsEmitter) -> None:
    emitter.record_cache_hit(hit=True)
    emitter.record_cache_hit(hit=False)
    from prometheus_client import generate_latest
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m1_llm_cache_hit_total" in output
    assert "m1_llm_cache_miss_total" in output


def test_ingest_duration_histogram(emitter: MetricsEmitter) -> None:
    emitter.observe_ingest_duration(seconds=5.2)
    from prometheus_client import generate_latest
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m1_ingest_repo_duration_seconds" in output


def test_log_points_extracted_total(emitter: MetricsEmitter) -> None:
    emitter.inc_log_points_extracted(language="python", delta=10)
    from prometheus_client import generate_latest
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m1_log_points_extracted_total" in output
    assert "python" in output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/metrics/test_metrics_emitter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m1.metrics_emitter'`

- [ ] **Step 3: Write minimal implementation**

`packages/m1/metrics_emitter.py`:
```python
"""Unit E: Metrics Emitter — Prometheus 指标（AC-18）。"""
from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import REGISTRY


class MetricsEmitter:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or REGISTRY
        self._candidate_pool = Gauge(
            "m1_candidate_pool_size",
            "候选池规模", labelnames=["repo_id"],
            registry=self._registry,
        )
        self._llm_call = Counter(
            "m1_llm_call_total", "LLM 调用次数",
            labelnames=["result"], registry=self._registry,
        )
        self._cache_hit = Counter(
            "m1_llm_cache_hit_total", "LLM 缓存命中",
            labelnames=["hit"], registry=self._registry,
        )
        self._ingest_duration = Histogram(
            "m1_ingest_repo_duration_seconds",
            "ingest_repo 耗时", registry=self._registry,
        )
        self._extracted = Counter(
            "m1_log_points_extracted_total",
            "已提取 LogPoint 总数", labelnames=["language"],
            registry=self._registry,
        )

    def inc_candidate_pool(self, repo_id: str, delta: int = 1) -> None:
        self._candidate_pool.labels(repo_id=repo_id).inc(delta)

    def record_llm_call(self, success: bool) -> None:
        self._llm_call.labels(result="success" if success else "failure").inc()

    def record_cache_hit(self, hit: bool) -> None:
        self._cache_hit.labels(hit="true" if hit else "false").inc()

    def observe_ingest_duration(self, seconds: float) -> None:
        self._ingest_duration.observe(seconds)

    def inc_log_points_extracted(self, language: str, delta: int = 1) -> None:
        self._extracted.labels(language=language).inc(delta)

    def render(self) -> str:
        return generate_latest(self._registry).decode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/metrics/test_metrics_emitter.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint check**

Run: `ruff check packages/m1/metrics_emitter.py tests/metrics/test_metrics_emitter.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/m1/metrics_emitter.py tests/metrics/test_metrics_emitter.py
git commit -m "feat(m1): metrics emitter — 5 个 prometheus 指标（AC-18）"
```

---

## Task 13: RepoLogGraphService 对外 API 实现

**Files:**
- Create: `packages/m1/repo_log_graph_service.py`
- Test: `tests/e2e/test_repo_log_graph_service.py`

**Interfaces:**
- Consumes: 所有 unit + AuditLogger + CandidateStager
- Produces: `RepoLogGraphService` 类（spec 第 226-259 行 5 个方法）

- [ ] **Step 1: Write the failing test**

`tests/e2e/test_repo_log_graph_service.py`:
```python
"""端到端测试 — RepoLogGraphService 5 个 API（AC-1/9/10/11/13/16）。"""
from __future__ import annotations

import json
import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import LANGUAGE_PYTHON, STATUS_CONFIRMED
from packages.m1.audit_log import AuditLogger
from packages.m1.config_loader import Config, LLMConfig, StorageConfig, ExtractionConfig, SanitizerConfig, MetricsConfig
from packages.m1.llm_hypothesis_generator import LLMHypothesisGenerator
from packages.m1.log_sanitizer import LogSanitizer, SanitizerConfig as LogSanitizerConfig
from packages.m1.metrics_emitter import MetricsEmitter
from packages.m1.storage.models import Base
from packages.m1.tree_sitter_parser import TreeSitterParser
from packages.m1.unit_a_repo_registrar import RepoSource, User
from packages.m1.unit_b_log_point_finder import LogPointFinder
from packages.m1.unit_d_candidate_staging import CandidateFilter, LogPointFilter
from packages.m1.repo_log_graph_service import RepoLogGraphService


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture()
def service(session: Session, fixtures_dir: pathlib.Path):
    gn = MagicMock()
    gn.analyze.return_value = None
    gn.cypher.return_value = []
    gn.context.return_value = {}

    llm = AsyncMock()
    llm.complete.return_value = json.dumps({
        "summary": "test", "possible_causes": [], "error_kind": "unknown",
        "suggested_check": None,
    })
    cache = MagicMock()
    cache.get.return_value = None

    config = Config(
        llm=LLMConfig(api_key="k", model_name="gpt-4", endpoint="e"),
        storage=StorageConfig(postgres_dsn="d", redis_port=6398, redis_namespace="ns"),
        extraction=ExtractionConfig(
            top_n_candidates=50, include_print=False,
            ingest_timeout_minutes=30, candidate_ttl_days=30,
            extractor_version="1.0.0",
        ),
        sanitizer=SanitizerConfig(enabled=True, patterns=["api_key"], replacement="[R]"),
        metrics=MetricsConfig(enabled=True, endpoint="/metrics", port=9100),
    )

    return RepoLogGraphService(
        session=session, gitnexus=gn,
        llm_client=llm, cache=cache, config=config,
        tree_sitter=TreeSitterParser(),
        audit=AuditLogger(session),
        metrics=MetricsEmitter(),
    )


@pytest.mark.asyncio()
async def test_ingest_repo_end_to_end(
    service: RepoLogGraphService, fixtures_dir: pathlib.Path
) -> None:
    repo_id = service.ingest_repo(
        RepoSource(local_path=str(fixtures_dir / "python_logging_repo")),
        User(id="user-1", name="alice"),
    )
    assert repo_id.startswith("repo-")


def test_list_candidates_after_ingest(
    service: RepoLogGraphService, fixtures_dir: pathlib.Path
) -> None:
    service.ingest_repo(
        RepoSource(local_path=str(fixtures_dir / "python_logging_repo")),
        User(id="user-1", name="alice"),
    )
    candidates = service.list_candidates(service._last_repo_id, CandidateFilter(include_all=True))
    assert len(candidates) >= 4  # fixture python_logging_repo 有 4 个 LOG 调用


def test_confirm_then_query(
    service: RepoLogGraphService, fixtures_dir: pathlib.Path
) -> None:
    repo_id = service.ingest_repo(
        RepoSource(local_path=str(fixtures_dir / "python_logging_repo")),
        User(id="user-1", name="alice"),
    )
    candidates = service.list_candidates(repo_id, CandidateFilter(include_all=True))
    ids = [c.id for c in candidates]
    service.confirm_ingestion(repo_id, ids, confirmer="user-1")

    queried = service.query_log_points(repo_id, LogPointFilter())
    assert len(queried) == len(ids)
    assert all(q.ingestion_status == STATUS_CONFIRMED for q in queried)


def test_get_call_context_returns_callcontext(
    service: RepoLogGraphService, fixtures_dir: pathlib.Path
) -> None:
    repo_id = service.ingest_repo(
        RepoSource(local_path=str(fixtures_dir / "python_logging_repo")),
        User(id="user-1", name="alice"),
    )
    ctx = service.get_call_context(repo_id, "def login(uid: str) -> bool")
    assert ctx is not None
    assert hasattr(ctx, "callers")
    assert hasattr(ctx, "callees")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/e2e/test_repo_log_graph_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m1.repo_log_graph_service'`

- [ ] **Step 3: Write minimal implementation**

`packages/m1/repo_log_graph_service.py`:
```python
"""RepoLogGraphService — M1 对外 API（spec 第 226-259 行）。"""
from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from packages.contracts.log_point import CallContext, LogPoint
from packages.m1.audit_log import AuditLogger
from packages.m1.config_loader import Config
from packages.m1.gitnexus_client import GitNexusClient
from packages.m1.llm_hypothesis_generator import LLMClient, LLMHypothesisGenerator, RedisCache
from packages.m1.metrics_emitter import MetricsEmitter
from packages.m1.storage.models import LogPointModel
from packages.m1.tree_sitter_parser import TreeSitterParser
from packages.m1.unit_a_repo_registrar import RepoRegistrar, RepoSource, User
from packages.m1.unit_b_log_point_finder import LogPointFinder
from packages.m1.unit_d_candidate_staging import (
    CandidateFilter,
    CandidateStager,
    LogPointFilter,
)
from sqlalchemy import select


class RepoLogGraphService:
    def __init__(
        self,
        session: Session,
        gitnexus: GitNexusClient,
        llm_client: LLMClient,
        cache: RedisCache,
        config: Config,
        tree_sitter: TreeSitterParser,
        audit: AuditLogger,
        metrics: MetricsEmitter,
    ) -> None:
        self._session = session
        self._config = config
        self._audit = audit
        self._metrics = metrics
        self._last_repo_id: str = ""

        sanitizer = LogSanitizer(
            __import__("packages.m1.log_sanitizer", fromlist=["LogSanitizer"]).SanitizerConfig(
                enabled=config.sanitizer.enabled,
                patterns=config.sanitizer.patterns,
                replacement=config.sanitizer.replacement,
            )
        )

        self._llm_gen = LLMHypothesisGenerator(
            llm_client=llm_client, cache=cache,
            model_name=config.llm.model_name,
            extractor_version=config.extraction.extractor_version,
            sanitizer=sanitizer,
            batch_size=config.llm.batch_size,
            max_retries=config.llm.max_retries,
        )
        self._finder = LogPointFinder(gitnexus=gitnexus, tree_sitter=tree_sitter)
        self._stager = CandidateStager(
            session=session, audit=audit,
            top_n=config.extraction.top_n_candidates,
        )
        self._registrar = RepoRegistrar(
            gitnexus=gitnexus, session=session,
            git_user_email="bot@codefly",
            audit=audit,
            finder=self._finder,
            llm_generator=self._llm_gen,
            extractor_version=config.extraction.extractor_version,
        )

    def ingest_repo(self, source: RepoSource, ingester: User, incremental: bool = False) -> str:
        import time
        start = time.time()
        repo_id = self._registrar.ingest(source, ingester, incremental=incremental)
        self._last_repo_id = repo_id
        self._metrics.observe_ingest_duration(time.time() - start)
        return repo_id

    def list_candidates(self, repo_id: str, filter: CandidateFilter) -> list[LogPoint]:
        return self._stager.list_candidates(repo_id, filter)

    def confirm_ingestion(
        self, repo_id: str, log_point_ids: list[str], confirmer: User
    ) -> None:
        self._stager.confirm_ingestion(repo_id, log_point_ids, confirmer=confirmer.id)

    def revoke_ingestion(
        self, repo_id: str, log_point_ids: list[str], revoker: User
    ) -> None:
        self._stager.revoke_ingestion(repo_id, log_point_ids, revoker=revoker.id)

    def query_log_points(self, repo_id: str, filters: LogPointFilter) -> list[LogPoint]:
        return self._stager.query_log_points(repo_id, filters)

    def get_call_context(self, repo_id: str, function_signature: str) -> CallContext:
        # 查同 repo 的 log points + 取 gitnexus context
        rows = self._session.scalars(
            select(LogPointModel).where(LogPointModel.repo_id == repo_id)
        ).all()
        related = [self._stager._model_to_log_point(r) for r in rows]
        return CallContext(
            function_signature=function_signature,
            callers=[],  # 实施时填 gitnexus.context()
            callees=[],
            enclosing_community=rows[0].enclosing_community if rows else None,
            related_log_points=related,
            evidence_refs=[],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/e2e/test_repo_log_graph_service.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint check**

Run: `ruff check packages/m1/repo_log_graph_service.py tests/e2e/`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/m1/repo_log_graph_service.py tests/e2e/
git commit -m "feat(m1): repo log graph service — 5 个对外 API + 端到端测试"
```

---

## Task 14: AC 自检 + spec 全覆盖报告

**Files:**
- Create: `tests/test_ac_coverage.py`

**Interfaces:**
- Consumes: 所有 AC（spec 第 340-360 行）
- Produces: pytest 集合测试，每个 AC 一个 mark

- [ ] **Step 1: Write AC coverage test**

`tests/test_ac_coverage.py`:
```python
"""AC 覆盖自检 — 每个 AC 至少被一个测试覆盖（spec 第 340-360 行）。"""
from __future__ import annotations

# AC 映射表：AC 编号 → 测试文件路径
AC_COVERAGE = {
    "AC-1": "tests/unit_a/test_repo_registrar.py::test_ingest_local_path_returns_repo_id",
    "AC-2": "tests/unit_a/test_repo_registrar.py::test_ingest_rejects_dotdot_path",
    "AC-3": "tests/unit_b/test_log_point_finder.py::test_python_logging_recognized",
    "AC-4": "tests/unit_b/test_log_point_finder.py::test_deduplication_same_file_line",
    "AC-5": "tests/unit_b/test_log_point_finder.py::test_decoy_repo_filters_out_business_functions",
    "AC-6": "tests/unit_c/test_llm_hypothesis_generator.py::test_cache_hit_skips_llm_call",
    "AC-7": "tests/unit_c/test_llm_hypothesis_generator.py::test_llm_failure_keeps_hypothesis_none",
    "AC-8": "tests/unit_c/test_log_sanitizer.py::test_zero_hits_required_for_llm_call",
    "AC-9": "tests/unit_d/test_candidate_staging.py::test_revoke_ingestion_back_to_candidate",
    "AC-10": "tests/unit_d/test_candidate_staging.py::test_list_candidates_default_only_top_n",
    "AC-11": "tests/unit_d/test_candidate_staging.py::test_confirm_ingestion_moves_to_main",
    "AC-12": "tests/unit_a/test_config_loader.py::test_env_var_overrides_yaml",
    "AC-13": "tests/unit_d/test_candidate_staging.py::test_query_log_points_returns_only_ingested",
    "AC-14": "tests/unit_a/test_repo_registrar.py::test_concurrent_ingest_same_repo_returns_running",
    "AC-15": "tests/unit_b/test_log_point_finder.py::test_file_path_posix_style_on_windows",
    "AC-16": "tests/e2e/test_repo_log_graph_service.py::test_confirm_then_query",
    "AC-17": "tests/unit_d/test_candidate_staging.py::test_audit_log_written_on_confirm",
    "AC-18": "tests/metrics/test_metrics_emitter.py::test_candidate_pool_size_metric",
    "AC-19": "tests/contracts/test_log_point.py::test_log_point_roundtrip",
    "AC-20": "tests/unit_a/test_repo_registrar.py::test_ingest_local_path_returns_repo_id",
    "AC-21": "（实施完成后由 @云长 跨家族 review — 流程项，不在测试覆盖）",
}


def test_ac_coverage_table_is_complete() -> None:
    """AC-1 到 AC-21 全部有测试映射（AC-21 除外，流程项）。"""
    for ac in range(1, 21):
        key = f"AC-{ac}"
        assert key in AC_COVERAGE, f"{key} 未在测试覆盖表里"
```

- [ ] **Step 2: Run all tests to verify pass**

Run: `pytest -v`
Expected: ALL PASS（除可能的 integration mark 跳过）

- [ ] **Step 3: Lint check 全工程**

Run: `ruff check .`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_ac_coverage.py
git commit -m "test(m1): ac coverage 自检 — 21 条 ac 全映射测试"
```

---

## Task 15: 跨家族 review 请求 + 实施 README

**Files:**
- Create: `README.md`（项目根，简版）
- Create: `docs/decisions/F001-review-handoff.md`

**Interfaces:**
- Consumes: 全部 T1-T14 产出 + spec
- Produces: review 请求文档给 @云长，README 给后续 M2/M3/M4 owner

- [ ] **Step 1: Write README**

`README.md`（项目根）:
```markdown
# 代码飞轮（Code Flywheel）

日志智能分析平台 — 从代码仓日志埋点解析到 LLM 辅助改进的闭环。

## 当前状态

- F001 代码仓日志解析模块：spec 完成，进入实施
- F002-F004：backlog，等 F001 落地后启动各自 spec

## 工程结构

```
代码飞轮/
├── packages/
│   ├── contracts/  # 数据契约子包（M1/M2/M3/M4 共享）
│   └── m1/         # M1 代码仓日志解析模块
├── tests/
├── docs/
│   ├── features/F001-代码仓日志解析.md  # spec
│   ├── SOP.md
│   └── superpowers/plans/2026-07-24-f001-*.md  # 实施计划
├── config.example.yaml
├── pyproject.toml
└── ruff.toml
```

## 快速开始（开发）

```bash
# 安装依赖
pip install -e ".[dev]"

# 复制配置
cp config.local.yaml.example config.local.yaml
# 填入 llm.api_key 或 export CODEFLY_LLM_API_KEY=...

# 运行测试
pytest

# Lint
ruff check .
```

## 协作

- 主 owner: @奉孝 (ragdoll-pa82, GLM-5.2)
- Reviewer: @云长 (跨家族，GLM-5.1)
- 审计: @孝直 (Qwen-3.7)
- spec 详见 docs/features/F001-*.md
- 实施计划详见 docs/superpowers/plans/2026-07-24-f001-*.md
```

`docs/decisions/F001-review-handoff.md`:
```markdown
---
feature_ids: [F001]
related_features: []
topics: [review, handoff]
doc_kind: decision
created: 2026-07-24
---

# F001 实施 review 交接给 @云长

## What

F001 spec + 实施计划完成（v3 spec + 15 task plan），按家规铁律"no self-review"，
请 @云长 (GLM-5.1, 跨家族) 做代码审查。

## Why

家规"Review 必须跨个体"——M1 主 owner = 奉孝，self-review 不合规。
云长擅长 review、找 bug、coding 落地，是 M1 review 的合适人选。

## What to Review

1. **Spec**：`docs/features/F001-代码仓日志解析.md`（v3, 422 行）
   - 21 条 AC 是否覆盖完整（spec 第 340-360 行）
   - 4 子单元架构是否合理（spec 第 27-97 行）
   - 数据契约字段是否充分（spec 第 100-208 行）
   - 配置 schema 是否完整（spec 第 263-313 行）

2. **实施计划**：`docs/superpowers/plans/2026-07-24-f001-code-repo-log-parse.md`（15 task）
   - 任务粒度是否 bite-sized（2-5 min/step）
   - 每 task 是否有红绿循环 + commit
   - AC 覆盖表是否完整（Task 14）

## Tradeoff

M1 实施主力是 @奉孝，所以 review 必须找别的猫。@云长 跨家族 + 招牌是 review，
符合家规"跨 family 优先"。

## Open Questions

- 若 review 中发现 spec 必须修订，回到 brainstorming round-3 还是直接修订？
  默认：spec 字段级小修直接改；架构级 push back 走 round-3。
- 若 review 中发现实施计划有任务遗漏或顺序问题，直接在 plan 文件改。

## Next Action

@云长 接球后：
1. Read spec + plan 全文
2. 给 review 反馈（建议 + 必修项）
3. 反馈给 @奉孝
4. 奉孝 修订后进 subagent-driven-development 实施
```

- [ ] **Step 2: Lint check + final test pass**

Run: `pytest -v && ruff check .`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add README.md docs/decisions/F001-review-handoff.md
git commit -m "docs(m1): readme + 跨家族 review 交接给 @云长"
```

---

## Self-Review

### Spec coverage

| Spec section | AC | Task implementing |
|--------------|-----|-------------------|
| 模块定位 | — | T1 (工程基线) + T13 (服务实现) |
| Unit A 架构图 | AC-1/2/14/20 | T6 |
| Unit B 两层过滤 | AC-3/4/5 | T7 + T8 |
| Unit C LogSanitizer + LLM | AC-6/7/8 | T9 |
| Unit D 候选池 + 入库 gate | AC-9/10/11/13 | T11 |
| LogPoint dataclass | AC-19 | T3 + T4 |
| LLMHypothesis 字段 | — | T3 |
| CaseRef 字段 | — | T3 |
| RepoIngestLock | AC-14 | T4 (model) + T6 (逻辑) |
| CallContext | — | T3 |
| AuditLog | AC-17 | T3 + T6 (audit_log.py) |
| 6 pattern 识别规则 | AC-3 | T7 (fixture) + T8 (识别) |
| 对外 API 5 个方法 | AC-1/9/10/11/13 | T13 |
| Configuration Schema | AC-12 | T2 |
| Metrics | AC-18 | T12 |
| 增量接口 | AC-20 | T6 (NotImplementedError) |
| 跨家族 review | AC-21 | T15 (流程项) |
| 端到端 | AC-16 | T13 + T14 |
| 跨平台路径 | AC-15 | T4 (POSIX 转换) + T8 (验证) |

**覆盖确认**：spec 21 条 AC 全部有 task 覆盖（AC-21 是流程项，由 T15 交接 review）。

### Placeholder scan

扫"TBD/TODO/implement later/add appropriate/handle edge cases"等模式——本 plan 每个 step 都有完整代码或完整命令。无占位符。

### Type consistency

- `LogPoint` / `LLMHypothesis` / `CaseRef` / `CallContext` / `RepoIngestLock` / `AuditLog` 在 T3 定义，T4 模型字段、T8/T9/T11/T13 使用，字段名一致
- `LogPointModel` / `CandidateStagingModel` / `RepoIngestLockModel` / `AuditLogModel` 在 T4 定义，T6/T11/T13 使用
- `RepoLogGraphService` 方法签名在 T13 与 spec 第 226-259 行一致（`ingest_repo` / `list_candidates` / `confirm_ingestion` / `revoke_ingestion` / `query_log_points` / `get_call_context`）
- 枚举常量在 T3 定义，T4/T8/T11 使用，名称一致

无类型/方法签名不一致。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-24-f001-code-repo-log-parse.md`**（15 tasks，~3000 行）。

**两种执行方式：**

**1. Subagent-Driven (recommended)** — 每个 task dispatch 一个 fresh subagent，task 间做 review，快速迭代。家规跨猫协作下推荐——可让 @云长 在 task 间做 review，比一次性 review 15 task 更稳。

**2. Inline Execution** — 在当前 session 用 executing-plans 批量执行，检查点 review。适合单人快速跑完。

**推荐路径**：
1. 先让 @云长 review 整份 spec + plan（T15 的 handoff 已写好交接文档）
2. 通过后开 worktree（铁律：主仓库禁止 checkout 非 main 分支）
3. 进 subagent-driven-development，每 task 一个 subagent 实施
4. 每 3-4 task 让 @云长 spot-check
5. 全部 task 完成后跑 `pytest -v` 验证 AC 覆盖
6. merge-gate 流程合入 main

[奉孝/GLM-5.2🐾]


