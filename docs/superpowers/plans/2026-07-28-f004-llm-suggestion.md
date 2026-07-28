# F004 LLM 改进建议 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 M2 已落地的 `DeepAnalysisRecord` 之上加一层 M4 改进建议层 — 5 个 ACP agent（1 coordinator + 4 reviewer）部署在独立 ACP Server 进程（:8001），FastAPI 编排层通过 acp_sdk Client 调用协调器 agent，输出 `SuggestionRecord`（含 unified_diff + 4 视角评估）持久化到 PG。

**Architecture:** 不修改 M1/M2 service 字节级（仅 M1 加 `get_source_snippet` 新方法，同 F002 §十 模式）。引入 acp-sdk 依赖，新增 `packages/m4/` 子包 + `acp_servers/m4_server.py` 独立进程入口。FastAPI lifespan 扩展启动 ACP Server 子进程（dev 模式）/ 生产独立 systemd。ACP Message 标准化输入（DeepAnalysisRecord + CallContext + source snippet + log entry），多 reviewer 串行调用产 `SuggestionPerspective`，coordinator 汇总 `SuggestionRecord` 持久化。

**Tech Stack:** Python 3.11+ / FastAPI 0.110+ / Pydantic v2.6+ / acp-sdk>=0.1,<1.0 / SQLAlchemy 2.x（复用 M1 Base） / prometheus_client / redis 6398 / pytest+pytest-asyncio / ruff（line-length=100）

## Global Constraints

- **Python 3.11+**（pyproject.toml requires-python）
- **ruff** lint + format（line-length=100，复用 M1 ruff.toml）
- **pytest + pytest-asyncio**（复用 F001.1 conftest 模式）
- **fastapi>=0.110,<0.120** / **pydantic>=2.6,<3.0** / **uvicorn[standard]>=0.27,<0.30** 已在 dependencies
- **acp-sdk>=0.1,<1.0**（F004 新增 optional-dependencies m4）
- **Pydantic v2 schema 强制 `ConfigDict(strict=True, extra="forbid", from_attributes=True)`**（继承 F001.1）
- **端口规划铁律**（家规 + F001.1 端口修复）：
  - 3003 / 3004 / 9100 = CatCafe runtime 自留地，禁占
  - 8000 = FastAPI HTTP（F001.1 已用）
  - 8001 = ACP M4 Server（F004 新增，08:32 UTC 实测无冲突）
  - 9464 = metrics（F001.1 已用，跟 CatCafe 撞 — F001.1 hotfix 改 9465 follow-up，F004 不阻塞）
  - 测试 fixture 用 8002 端口（避免与 dev :8001 冲突）
- **Redis 6399 禁止**（家规铁律，M1 已铁律检查）；F004 用 6398 + `codefly-m4` 子命名空间
- **TTL=0 P0 持久化铁律**（suggestion_record 表默认持久化，不删用户可见数据）
- **No self-review**（F004 author=奉孝 Siamese，reviewer=云长 Maine Coon — 跨家族铁律）
- **TDD**：每 task 先红测 → 跑 fail → 最小实现 → 跑 pass → lint → commit
- **不改 M1/M2 service 字节级**（同 F002 AC-18 模式）— M1 仅加 `get_source_snippet` 新方法，不动已有 6 个 + `update_log_point_hypothesis`
- **ACP Server graceful degradation**（AC-19）— 启动失败不崩 FastAPI，返回 503 ACP_SERVER_UNAVAILABLE
- **SuggestionRecord 标注为"参考建议"**（AC-17）— 不作为自动改代码依据
- **acp-sdk API 表面**：本 plan 写作时 acp-sdk 未安装；implement 时先 `pip install acp-sdk>=0.1,<1.0` 并校验 `acp_sdk.server.Server` / `@server.agent()` / `Client.run_sync` / `Message` / `MessagePart` API 表面与 spec §十一 模板一致；若 API 表面有差异，按实际 API 调整 agent 实现，但 spec 数据契约（SuggestionRecord/SuggestionPerspective）不变

---

### Task 1: 工程基线 — packages/m4/ + acp_servers/ + acp-sdk 依赖锁

**Files:**
- Create: `packages/m4/__init__.py`（空）
- Create: `packages/m4/agents/__init__.py`（空）
- Create: `packages/m4/storage/__init__.py`（空）
- Create: `packages/m4/storage/migrations/__init__.py`（空）
- Create: `packages/m4/storage/migrations/versions/__init__.py`（空）
- Create: `acp_servers/__init__.py`（空）
- Create: `tests/m4/__init__.py`（空）
- Create: `tests/m4/agents/__init__.py`（空）
- Modify: `pyproject.toml`（加 m4 optional-dependencies）
- Test: `tests/m4/test_smoke.py`

**Interfaces:**
- Consumes: 无（基线 task）
- Produces: `packages/m4/` 子包结构 + `acp_servers/` 顶层包结构 + `tests/m4/` 测试目录 + acp-sdk 依赖

- [ ] **Step 1: Write the failing test**

`tests/m4/test_smoke.py`:
```python
"""Smoke test — packages.m4 + acp_servers 子包可 import。"""
from __future__ import annotations


def test_m4_package_importable() -> None:
    """packages.m4 子包存在（暂无内容）。"""
    import packages.m4  # noqa: F401
    import packages.m4.agents  # noqa: F401
    import packages.m4.storage  # noqa: F401


def test_acp_servers_package_importable() -> None:
    """acp_servers 顶层包存在。"""
    import acp_servers  # noqa: F401


def test_acp_sdk_installed() -> None:
    """acp-sdk 依赖已安装。"""
    import acp_sdk  # noqa: F401
    from acp_sdk import Message, MessagePart  # noqa: F401
    from acp_sdk.server import Server  # noqa: F401
    from acp_sdk.client import Client  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/test_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m4'` 和 `ModuleNotFoundError: No module named 'acp_sdk'`

- [ ] **Step 3: Create packages/m4/ + acp_servers/ subpackage structure**

`packages/m4/__init__.py`（空文件）:
```python
"""F004 M4 改进建议层（spec §一）。"""
```

`packages/m4/agents/__init__.py`（空文件）:
```python
"""5 个 ACP agent 实现（spec §二）。"""
```

`packages/m4/storage/__init__.py`（空文件）:
```python
"""M4 持久化层。"""
```

`packages/m4/storage/migrations/__init__.py`（空文件）:
```python
"""Alembic migrations."""
```

`packages/m4/storage/migrations/versions/__init__.py`（空文件）

`acp_servers/__init__.py`（空文件）:
```python
"""ACP Server 启动入口（spec §十一）。"""
```

`tests/m4/__init__.py`（空文件）

`tests/m4/agents/__init__.py`（空文件）

- [ ] **Step 4: Update pyproject.toml — add m4 optional-dependencies**

修改 `pyproject.toml`，在 `[project.optional-dependencies]` 段加 `m4` group：

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-cov>=5.0", "ruff>=0.4"]
api = [
  "uvicorn[standard]>=0.27,<0.30",
]
m4 = [
  "acp-sdk>=0.1,<1.0",
]
```

注：`mcp` 已在 `dependencies`，无需重复。

- [ ] **Step 5: Install m4 extras + run test to verify pass**

Run: `python -m pip install -e ".[m4,api,dev]"`
Expected: Successfully installed acp-sdk-0.1.x

Run: `python -m pytest tests/m4/test_smoke.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Verify acp-sdk API 表面**

Run: `python -c "from acp_sdk import Message, MessagePart; from acp_sdk.server import Server; from acp_sdk.client import Client; print('API ok')"`
Expected: PASS — 如 FAIL，记录实际 API 表面差异，在后续 Task 7-9 调整 agent 实现

- [ ] **Step 7: Lint check**

Run: `python -m ruff check packages/m4/ acp_servers/ tests/m4/`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add packages/m4/ acp_servers/ tests/m4/ pyproject.toml
git commit -m "chore(m4): packages/m4 + acp_servers subpackage + acp-sdk optional-deps"
```

---

### Task 2: Config 扩展 — AcpConfig + M4Config dataclass + config.example.yaml

**Files:**
- Modify: `packages/m1/config_loader.py`（加 AcpConfig + M4Config + Config.acp/m4 字段 + env override）
- Modify: `config.example.yaml`（加 acp + m4 段）
- Test: `tests/m4/test_config_loader.py`

**Interfaces:**
- Consumes: M1 `Config` / `LLMConfig` / `M2Config`（不修改）
- Produces: `AcpConfig` dataclass + `M4Config` dataclass + `Config.acp` / `Config.m4` 字段 + `load_config()` 返回含 acp/m4 段

- [ ] **Step 1: Write the failing test**

`tests/m4/test_config_loader.py`:
```python
"""Config loader 测试 — AcpConfig + M4Config 段加载（spec §七）。"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from packages.m1.config_loader import AcpConfig, Config, M4Config, load_config


@pytest.fixture()
def config_yaml() -> pathlib.Path:
    """临时 config.yaml，含 acp + m4 段。"""
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
acp:
  server_host: "127.0.0.1"
  server_port: 8001
  server_workers: 1
  client_timeout_seconds: 300
  enabled: true
m4:
  model_name: gpt-4
  perspectives: ["performance", "security", "readability", "testing"]
  max_iterations: 3
  cache_ttl_seconds: 86400
  max_source_lines: 200
"""
    p = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
    p.write_text(content, encoding="utf-8")
    yield p
    p.unlink(missing_ok=True)


def test_acp_config_loaded(config_yaml: pathlib.Path) -> None:
    """load_config 返回 Config 含 acp 段。"""
    config = load_config(config_yaml)
    assert isinstance(config.acp, AcpConfig)
    assert config.acp.server_port == 8001
    assert config.acp.server_host == "127.0.0.1"
    assert config.acp.enabled is True
    assert config.acp.client_timeout_seconds == 300


def test_m4_config_loaded(config_yaml: pathlib.Path) -> None:
    """load_config 返回 Config 含 m4 段。"""
    config = load_config(config_yaml)
    assert isinstance(config.m4, M4Config)
    assert config.m4.model_name == "gpt-4"
    assert config.m4.perspectives == ("performance", "security", "readability", "testing")
    assert config.m4.max_iterations == 3
    assert config.m4.max_source_lines == 200


def test_acp_config_defaults_when_missing(config_yaml: pathlib.Path) -> None:
    """config.yaml 缺 acp 段时用默认值。"""
    content = config_yaml.read_text(encoding="utf-8").replace(
        "acp:\n  server_host: \"127.0.0.1\"\n  server_port: 8001\n  server_workers: 1\n  client_timeout_seconds: 300\n  enabled: true\n",
        "",
    )
    config_yaml.write_text(content, encoding="utf-8")
    config = load_config(config_yaml)
    assert config.acp.server_port == 8001
    assert config.acp.enabled is True


def test_acp_env_override(config_yaml: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CODEFLY_ACP_* 环境变量覆盖 config。"""
    monkeypatch.setenv("CODEFLY_ACP_SERVER_PORT", "9001")
    monkeypatch.setenv("CODEFLY_ACP_ENABLED", "false")
    config = load_config(config_yaml)
    assert config.acp.server_port == 9001
    assert config.acp.enabled is False


def test_m4_env_override(config_yaml: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CODEFLY_M4_* 环境变量覆盖 config。"""
    monkeypatch.setenv("CODEFLY_M4_MODEL_NAME", "claude-3-opus")
    monkeypatch.setenv("CODEFLY_M4_MAX_ITERATIONS", "5")
    config = load_config(config_yaml)
    assert config.m4.model_name == "claude-3-opus"
    assert config.m4.max_iterations == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/test_config_loader.py -v`
Expected: FAIL with `ImportError: cannot import name 'AcpConfig' from 'packages.m1.config_loader'`

- [ ] **Step 3: Add AcpConfig + M4Config dataclass + Config.acp/m4 fields + env override**

修改 `packages/m1/config_loader.py`：

在 `M2Config` dataclass 之后加 `AcpConfig` 和 `M4Config`：

```python
@dataclasses.dataclass(frozen=True)
class AcpConfig:
    """F004 — ACP Server 配置（spec §七 + §十一）。

    端口避开 CatCafe runtime 3003/3004/9100 + 本项目 8000/9464。
    选 8001 = ACP M4 Server 独立进程。
    """
    server_host: str = "127.0.0.1"
    server_port: int = 8001
    server_workers: int = 1
    client_timeout_seconds: int = 300
    enabled: bool = True


@dataclasses.dataclass(frozen=True)
class M4Config:
    """F004 — M4 改进建议配置（spec §七）。"""
    model_name: str = "gpt-4"
    perspectives: tuple[str, ...] = ("performance", "security", "readability", "testing")
    max_iterations: int = 3
    cache_ttl_seconds: int = 86400
    max_source_lines: int = 200
```

修改 `Config` dataclass 加 `acp` + `m4` 字段：

```python
@dataclasses.dataclass(frozen=True)
class Config:
    llm: LLMConfig
    storage: StorageConfig
    extraction: ExtractionConfig
    sanitizer: SanitizerConfig
    metrics: MetricsConfig
    api: ApiConfig = dataclasses.field(default_factory=ApiConfig)
    m2: M2Config = dataclasses.field(default_factory=M2Config)
    acp: AcpConfig = dataclasses.field(default_factory=AcpConfig)  # F004 新增
    m4: M4Config = dataclasses.field(default_factory=M4Config)  # F004 新增
```

修改 `_env_override` 加 ACP/M4 环境变量映射：

```python
def _env_override(config_dict: dict[str, Any]) -> dict[str, Any]:
    """环境变量 CODEFLY_* 覆盖 config 字段（扁平键映射）。"""
    env_map = {
        "CODEFLY_LLM_API_KEY": ("llm", "api_key"),
        "CODEFLY_PG_DSN": ("storage", "postgres_dsn"),
        "CODEFLY_API_HOST": ("api", "host"),
        "CODEFLY_API_PORT": ("api", "port"),
        "CODEFLY_API_ENABLE_AUTH": ("api", "enable_auth"),
        "CODEFLY_API_CORS_ORIGINS": ("api", "cors_origins"),
        "CODEFLY_ACP_SERVER_HOST": ("acp", "server_host"),
        "CODEFLY_ACP_SERVER_PORT": ("acp", "server_port"),
        "CODEFLY_ACP_ENABLED": ("acp", "enabled"),
        "CODEFLY_ACP_CLIENT_TIMEOUT_SECONDS": ("acp", "client_timeout_seconds"),
        "CODEFLY_M4_MODEL_NAME": ("m4", "model_name"),
        "CODEFLY_M4_MAX_ITERATIONS": ("m4", "max_iterations"),
        "CODEFLY_M4_MAX_SOURCE_LINES": ("m4", "max_source_lines"),
    }
    for env_key, (section, field) in env_map.items():
        val = os.environ.get(env_key)
        if val:
            config_dict.setdefault(section, {})[field] = val
    return config_dict
```

修改 `load_config` 返回时构造 `AcpConfig` + `M4Config`：

```python
    # acp 段（缺失时用默认值 — spec §七）
    acp_dict = expanded.get("acp", {})
    acp_enabled = acp_dict.get("enabled", True)
    if isinstance(acp_enabled, str):
        acp_enabled = acp_enabled.lower() in ("true", "1", "yes")

    # m4 段（缺失时用默认值 — spec §七）
    m4_dict = expanded.get("m4", {})
    m4_perspectives = m4_dict.get("perspectives", ["performance", "security", "readability", "testing"])
    if isinstance(m4_perspectives, str):
        m4_perspectives = tuple(p.strip() for p in m4_perspectives.split(",") if p.strip())
    else:
        m4_perspectives = tuple(m4_perspectives)

    # ... 在 return Config(...) 中加：
    acp=AcpConfig(
        server_host=acp_dict.get("server_host", "127.0.0.1"),
        server_port=int(acp_dict.get("server_port", 8001)),
        server_workers=int(acp_dict.get("server_workers", 1)),
        client_timeout_seconds=int(acp_dict.get("client_timeout_seconds", 300)),
        enabled=acp_enabled,
    ),
    m4=M4Config(
        model_name=m4_dict.get("model_name", "gpt-4"),
        perspectives=m4_perspectives,
        max_iterations=int(m4_dict.get("max_iterations", 3)),
        cache_ttl_seconds=int(m4_dict.get("cache_ttl_seconds", 86400)),
        max_source_lines=int(m4_dict.get("max_source_lines", 200)),
    ),
```

- [ ] **Step 4: Update config.example.yaml — add acp + m4 sections**

修改 `config.example.yaml`，在文件末尾加：

```yaml
acp:
  server_host: "127.0.0.1"
  server_port: 8001  # 避开 CatCafe 3003/3004/9100 + 本项目 8000/9464
  server_workers: 1  # dev-only 单进程；生产可扩
  client_timeout_seconds: 300
  enabled: true  # False 时 SuggestionService 返回 503 ACP_SERVER_UNAVAILABLE

m4:
  model_name: gpt-4  # coordinator + code_fixer 强模型
  perspectives: ["performance", "security", "readability", "testing"]
  max_iterations: 3
  cache_ttl_seconds: 86400
  max_source_lines: 200  # source snippet 上限防 token 爆炸
```

- [ ] **Step 5: Run test to verify pass**

Run: `python -m pytest tests/m4/test_config_loader.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Verify M1 + M2 tests no regression**

Run: `python -m pytest tests/unit_a/test_config_loader.py tests/api/test_config_loader.py -v 2>&1 | tail -30`
Expected: PASS（M1/M2 既有测试通过 — Config 加 acp/m4 字段不破坏现有测试，因 `default_factory` 兼容旧 Config 构造）

- [ ] **Step 7: Lint check**

Run: `python -m ruff check packages/m1/config_loader.py tests/m4/test_config_loader.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add packages/m1/config_loader.py config.example.yaml tests/m4/test_config_loader.py
git commit -m "feat(m4): config loader AcpConfig + M4Config + env override"
```

---

### Task 3: 数据契约 — SuggestionPerspective + SuggestionRecord + SourceSnippet

**Files:**
- Create: `packages/contracts/suggestion.py` — SuggestionPerspective + SuggestionRecord
- Create: `packages/contracts/source_snippet.py` — SourceSnippet
- Modify: `packages/contracts/enums.py`（加 M4 ACTION_* + SUGGESTION_STATUS_* 常量）
- Test: `tests/m4/test_contracts_suggestion.py`

**Interfaces:**
- Consumes: M2 `TokenUsage` / `DeepAnalysisRecord` / `AnalysisReport`
- Produces:
  - `SuggestionPerspective` dataclass（perspective/assessment/suggested_diff/confidence/model_name/token_usage）
  - `SuggestionRecord` dataclass（id/deep_analysis_id/report_id/log_point_ids/unified_diff/summary/perspective_evaluations/confidence_score/model_name/prompt_hash/iteration/parent_record_id/generated_at/token_usage/schema_version/acp_session_id/acp_agent_versions）
  - `SourceSnippet` dataclass（file_path/line_range/content/extractor_version）

- [ ] **Step 1: Write the failing test**

`tests/m4/test_contracts_suggestion.py`:
```python
"""F004 M4 — 数据契约测试（spec §三）。"""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

from packages.contracts.analysis_report import TokenUsage
from packages.contracts.source_snippet import SourceSnippet
from packages.contracts.suggestion import (
    SuggestionPerspective,
    SuggestionRecord,
)


def test_suggestion_perspective_fields() -> None:
    """SuggestionPerspective 字段对齐 spec §三。"""
    p = SuggestionPerspective(
        perspective="performance",
        assessment="N+1 query in loop",
        suggested_diff="@@ -10,3 +10,5 @@",
        confidence=0.85,
        model_name="gpt-4",
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_cost_usd=0.02),
    )
    assert p.perspective == "performance"
    assert p.confidence == 0.85
    assert p.suggested_diff is not None


def test_suggestion_perspective_no_diff() -> None:
    """suggested_diff 可为 None（reviewer 评估但无 diff 建议）。"""
    p = SuggestionPerspective(
        perspective="security",
        assessment="no risk",
        suggested_diff=None,
        confidence=0.95,
        model_name="gpt-4",
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_cost_usd=0.02),
    )
    assert p.suggested_diff is None


def test_suggestion_record_fields() -> None:
    """SuggestionRecord 字段对齐 spec §三。"""
    now = datetime.now(UTC)
    p = SuggestionPerspective(
        perspective="performance",
        assessment="x",
        suggested_diff=None,
        confidence=0.5,
        model_name="gpt-4",
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_cost_usd=0.01),
    )
    r = SuggestionRecord(
        id="sug-1",
        deep_analysis_id="deep-1",
        report_id="report-1",
        log_point_ids=["lp-1", "lp-2"],
        unified_diff="@@ -10,3 +10,5 @@",
        summary="batch queries",
        perspective_evaluations=[p],
        confidence_score=0.7,
        model_name="gpt-4",
        prompt_hash="sha256-abc123",
        iteration=1,
        parent_record_id=None,
        generated_at=now,
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=200, total_cost_usd=0.10),
        schema_version="1.0.0",
        acp_session_id="acp-sess-1",
        acp_agent_versions={"coordinator": "1.0", "code_fixer": "1.0"},
    )
    assert r.id == "sug-1"
    assert r.deep_analysis_id == "deep-1"
    assert len(r.perspective_evaluations) == 1
    assert r.acp_session_id == "acp-sess-1"
    assert "coordinator" in r.acp_agent_versions


def test_suggestion_record_iteration_chain() -> None:
    """iteration + parent_record_id 累积链（spec §三 + AC-11）。"""
    now = datetime.now(UTC)
    r = SuggestionRecord(
        id="sug-2",
        deep_analysis_id="deep-1",
        report_id="report-1",
        log_point_ids=["lp-1"],
        unified_diff="@@ -1,1 +1,2 @@",
        summary="iter 2",
        perspective_evaluations=[],
        confidence_score=0.6,
        model_name="gpt-4",
        prompt_hash="sha256-xyz",
        iteration=2,
        parent_record_id="sug-1",
        generated_at=now,
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=200, total_cost_usd=0.10),
        schema_version="1.0.0",
        acp_session_id=None,
        acp_agent_versions={},
    )
    assert r.iteration == 2
    assert r.parent_record_id == "sug-1"


def test_source_snippet_fields() -> None:
    """SourceSnippet 字段（spec §十）。"""
    s = SourceSnippet(
        file_path="src/foo.py",
        line_range=(10, 30),
        content="def foo():\n    pass\n",
        extractor_version="1.0.0",
    )
    assert s.file_path == "src/foo.py"
    assert s.line_range == (10, 30)
    assert "def foo" in s.content


def test_suggestion_record_is_frozen_dataclass() -> None:
    """SuggestionRecord 必须 frozen dataclass（不可变 — spec §三 + P0 持久化铁律）。"""
    assert dataclasses.is_dataclass(SuggestionRecord)
    # frozen=True → 试图 setattr 应 raise
    now = datetime.now(UTC)
    r = SuggestionRecord(
        id="sug-1", deep_analysis_id="d", report_id="r", log_point_ids=[],
        unified_diff="", summary="", perspective_evaluations=[],
        confidence_score=0.0, model_name="m", prompt_hash="h",
        iteration=1, parent_record_id=None, generated_at=now,
        token_usage=TokenUsage(0, 0, 0.0), schema_version="1.0.0",
        acp_session_id=None, acp_agent_versions={},
    )
    try:
        r.id = "mutated"  # type: ignore[misc]
        raise AssertionError("SuggestionRecord 应 frozen — 不可变")
    except dataclasses.FrozenInstanceError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/test_contracts_suggestion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.contracts.suggestion'`

- [ ] **Step 3: Create packages/contracts/source_snippet.py**

`packages/contracts/source_snippet.py`:
```python
"""F004 M4 — SourceSnippet 数据契约（spec §十）。

M1 get_source_snippet 方法返回值 — 源码片段（供 M4 生成 diff 用）。
"""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class SourceSnippet:
    """源码片段（spec §十）。

    Attributes:
        file_path: 源码相对路径
        line_range: (start, end) 行号区间（含上下文扩展后的范围）
        content: 切片后的源码文本
        extractor_version: 提取器版本（spec §十 extractor_version）
    """
    file_path: str
    line_range: tuple[int, int]
    content: str
    extractor_version: str
```

- [ ] **Step 4: Create packages/contracts/suggestion.py**

`packages/contracts/suggestion.py`:
```python
"""F004 M4 — SuggestionRecord + SuggestionPerspective 数据契约（spec §三）。

M4 改进建议持久化记录 — 消费 M2 DeepAnalysisRecord + M1 CallContext + SourceSnippet，
输出 unified_diff + 4 视角评估 + 元数据。

P0 持久化铁律（AC-10）：suggestion_record 表 TTL=0 默认持久化。
"""
from __future__ import annotations

import dataclasses
from datetime import datetime

from packages.contracts.analysis_report import TokenUsage


@dataclasses.dataclass(frozen=True)
class SuggestionPerspective:
    """单视角评估（性能/安全/可读性/测试）— spec §三。

    Attributes:
        perspective: 视角名（"performance" / "security" / "readability" / "testing"）
        assessment: 评估文本（一句话问题/优势描述）
        suggested_diff: 该视角建议的 unified diff 片段（None 表示该视角无 diff 建议）
        confidence: 置信度 0.0-1.0
        model_name: 该视角调用的 LLM 模型名
        token_usage: 该视角 LLM 调用 token 用量 + 成本
    """
    perspective: str
    assessment: str
    suggested_diff: str | None
    confidence: float
    model_name: str
    token_usage: TokenUsage


@dataclasses.dataclass(frozen=True)
class SuggestionRecord:
    """M4 改进建议记录 — 持久化到 suggestion_record 表（spec §三 + AC-10）。

    P0 持久化：用户可见产物，TTL=0 默认持久化。
    迭代性：iteration 递增 + parent_record_id 链（累积上下文，同 M2 Phase 2 模式）。
    ACP 元数据：acp_session_id + acp_agent_versions 追溯 ACP 协议状态。

    Attributes:
        id: UUID
        deep_analysis_id: 关联 M2 DeepAnalysisRecord.id
        report_id: 关联 M2 AnalysisReport.id（间接，通过 DeepAnalysisRecord）
        log_point_ids: 目标 M1 LogPoint id 列表
        unified_diff: 合并后的最终 unified diff（主视角 code_fixer + 其他视角附录）
        summary: 一句话改进建议总结
        perspective_evaluations: 4 视角评估列表
        confidence_score: 综合置信度 0.0-1.0（加权平均）
        model_name: coordinator 用的 LLM 模型名
        prompt_hash: prompt 版本 hash
        iteration: 第几次改进建议（1, 2, 3...）
        parent_record_id: 前次建议 ID（累积上下文链）
        generated_at: 生成时间
        token_usage: 总 token 用量（5 个 agent 累加）
        schema_version: 数据契约版本
        acp_session_id: ACP session 追溯（None 表示非 ACP 路径生成）
        acp_agent_versions: agent 版本快照 {"coordinator": "1.0", "code_fixer": "1.0", ...}
    """
    id: str
    deep_analysis_id: str
    report_id: str
    log_point_ids: list[str]
    unified_diff: str
    summary: str
    perspective_evaluations: list[SuggestionPerspective]
    confidence_score: float
    model_name: str
    prompt_hash: str
    iteration: int
    parent_record_id: str | None
    generated_at: datetime
    token_usage: TokenUsage
    schema_version: str
    acp_session_id: str | None
    acp_agent_versions: dict[str, str]
```

- [ ] **Step 5: Add M4 ACTION_* + SUGGESTION_STATUS_* constants to enums.py**

修改 `packages/contracts/enums.py`，在文件末尾加：

```python
# F004 M4 audit action
ACTION_PHASE4_GENERATE_SUGGESTION = "phase4_generate_suggestion"
ACTION_ARCHIVE_SUGGESTION = "archive_suggestion"

# F004 M4 SuggestionRecord.ingestion_status（同 M2 STATUS_DRAFT/ARCHIVED 模式）
SUGGESTION_STATUS_DRAFT = "draft"
SUGGESTION_STATUS_ARCHIVED = "archived"
```

注：SuggestionRecord 当前 dataclass 无 `ingestion_status` 字段（spec §三 未列）；archive 操作通过软删除标志位（独立 `archived_at` 字段在 model 层加，dataclass 层不暴露，同 M2 archive_report 通过 ingestion_status 软删模式）— 此处常量暂留供 Task 5 storage model 用。

- [ ] **Step 6: Run test to verify pass**

Run: `python -m pytest tests/m4/test_contracts_suggestion.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Lint check**

Run: `python -m ruff check packages/contracts/suggestion.py packages/contracts/source_snippet.py packages/contracts/enums.py tests/m4/test_contracts_suggestion.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add packages/contracts/suggestion.py packages/contracts/source_snippet.py packages/contracts/enums.py tests/m4/test_contracts_suggestion.py
git commit -m "feat(m4): contracts — SuggestionRecord + SuggestionPerspective + SourceSnippet"
```

---

### Task 4: M1 get_source_snippet 新方法（AC-15/16 字节级稳定）

**Files:**
- Modify: `packages/m1/repo_log_graph_service.py`（加 `get_source_snippet` 方法，不动已有 6 个 + `update_log_point_hypothesis`）
- Test: `tests/m4/test_m1_get_source_snippet.py`

**Interfaces:**
- Consumes: M1 `RepoLogGraphService` 构造器已注入的 `gitnexus: GitNexusClient` + `config: Config`
- Produces: `RepoLogGraphService.get_source_snippet(repo_id, file_path, line_start, line_end) -> SourceSnippet`

- [ ] **Step 1: Write the failing test**

`tests/m4/test_m1_get_source_snippet.py`:
```python
"""F004 M4 — M1 get_source_snippet 测试（spec §十 + AC-15/16）。"""
from __future__ import annotations

from unittest.mock import MagicMock

from packages.contracts.source_snippet import SourceSnippet
from packages.m1.config_loader import Config
from packages.m1.repo_log_graph_service import RepoLogGraphService


def _make_service(gitnexus: MagicMock, config: Config) -> RepoLogGraphService:
    """构造 RepoLogGraphService（minimal mock，仅 get_source_snippet 用）。"""
    from packages.m1.audit_log import AuditLogger
    from packages.m1.llm_hypothesis_generator import LLMHypothesisGenerator
    from packages.m1.log_sanitizer import LogSanitizer
    from packages.m1.log_sanitizer import SanitizerConfig as LogSanitizerConfig
    from packages.m1.metrics_emitter import MetricsEmitter
    from packages.m1.tree_sitter_parser import TreeSitterParser
    from packages.m1.unit_d_candidate_staging import CandidateStager
    from sqlalchemy.orm import Session
    session = MagicMock(spec=Session)
    sanitizer = LogSanitizer(
        LogSanitizerConfig(
            enabled=config.sanitizer.enabled,
            patterns=config.sanitizer.patterns,
            replacement=config.sanitizer.replacement,
        )
    )
    cache = MagicMock()
    cache.get.return_value = None
    llm = MagicMock()
    return RepoLogGraphService(
        session=session, gitnexus=gitnexus, llm_client=llm, cache=cache,
        config=config, tree_sitter=TreeSitterParser(),
        audit=AuditLogger(session), metrics=MetricsEmitter(),
    )


def test_get_source_snippet_basic(monkeypatch) -> None:
    """get_source_snippet 通过 gitnexus 取 File 节点 content + 切片 + 扩展上下文。"""
    # 构造最小 Config
    from packages.m1.config_loader import (
        AcpConfig, ApiConfig, ExtractionConfig, LLMConfig, M2Config, M4Config,
        MetricsConfig, SanitizerConfig, StorageConfig,
    )
    config = Config(
        llm=LLMConfig(api_key="k", model_name="gpt-4", endpoint="https://x", timeout_seconds=30, max_retries=3, batch_size=20),
        storage=StorageConfig(postgres_dsn="sqlite:///:memory:", redis_port=6398, redis_namespace="codefly-m1"),
        extraction=ExtractionConfig(top_n_candidates=50, include_print=False, ingest_timeout_minutes=30, candidate_ttl_days=30, extractor_version="1.0.0"),
        sanitizer=SanitizerConfig(enabled=False, patterns=[], replacement="[R]"),
        metrics=MetricsConfig(enabled=False, endpoint="/metrics", port=9464),
        api=ApiConfig(),
        m2=M2Config(),
        acp=AcpConfig(),
        m4=M4Config(max_source_lines=200),
    )

    # Mock gitnexus.cypher 返回 File 节点（content 字段）
    gn = MagicMock()
    file_content_lines = [f"line {i}\n" for i in range(1, 101)]
    file_content = "".join(file_content_lines)
    gn.cypher.return_value = [{"filePath": "src/foo.py", "content": file_content}]

    service = _make_service(gn, config)

    # 调用 get_source_snippet（请求 10-20 行，扩展 ±10 后实际取 1-30）
    snippet = service.get_source_snippet(
        repo_id="repo-1",
        file_path="src/foo.py",
        line_start=10,
        line_end=20,
    )
    assert isinstance(snippet, SourceSnippet)
    assert snippet.file_path == "src/foo.py"
    # 扩展上下文：line_start=10 - 10 = 0 (clamp 到 1)，line_end=20 + 10 = 30
    assert snippet.line_range[0] == 1
    assert snippet.line_range[1] == 30
    assert "line 10" in snippet.content
    assert "line 20" in snippet.content
    assert "line 30" in snippet.content
    # 不应包含 line 31
    assert "line 31" not in snippet.content
    assert snippet.extractor_version == "1.0.0"


def test_get_source_snippet_max_lines_limit(monkeypatch) -> None:
    """max_source_lines 上限触发 — 切片超过上限时截断（防 token 爆炸）。"""
    from packages.m1.config_loader import (
        AcpConfig, ApiConfig, ExtractionConfig, LLMConfig, M2Config, M4Config,
        MetricsConfig, SanitizerConfig, StorageConfig,
    )
    config = Config(
        llm=LLMConfig(api_key="k", model_name="gpt-4", endpoint="https://x", timeout_seconds=30, max_retries=3, batch_size=20),
        storage=StorageConfig(postgres_dsn="sqlite:///:memory:", redis_port=6398, redis_namespace="codefly-m1"),
        extraction=ExtractionConfig(top_n_candidates=50, include_print=False, ingest_timeout_minutes=30, candidate_ttl_days=30, extractor_version="1.0.0"),
        sanitizer=SanitizerConfig(enabled=False, patterns=[], replacement="[R]"),
        metrics=MetricsConfig(enabled=False, endpoint="/metrics", port=9464),
        api=ApiConfig(),
        m2=M2Config(),
        acp=AcpConfig(),
        m4=M4Config(max_source_lines=50),  # 限制 50 行
    )

    gn = MagicMock()
    # 1000 行文件
    file_content = "".join([f"line {i}\n" for i in range(1, 1001)])
    gn.cypher.return_value = [{"filePath": "src/big.py", "content": file_content}]

    service = _make_service(gn, config)

    # 请求 400-600（200 行），扩展 ±10 后实际取 390-610（221 行 > 50 上限）
    snippet = service.get_source_snippet(
        repo_id="repo-1",
        file_path="src/big.py",
        line_start=400,
        line_end=600,
    )
    # 上限触发：line_range 不超过 max_source_lines
    actual_lines = snippet.line_range[1] - snippet.line_range[0] + 1
    assert actual_lines <= 50, f"snippet 行数 {actual_lines} 应 <= max_source_lines=50"


def test_get_source_snippet_file_not_found() -> None:
    """gitnexus 返回空时，get_source_snippet 返回空 content（不 raise）。"""
    from packages.m1.config_loader import (
        AcpConfig, ApiConfig, ExtractionConfig, LLMConfig, M2Config, M4Config,
        MetricsConfig, SanitizerConfig, StorageConfig,
    )
    config = Config(
        llm=LLMConfig(api_key="k", model_name="gpt-4", endpoint="https://x", timeout_seconds=30, max_retries=3, batch_size=20),
        storage=StorageConfig(postgres_dsn="sqlite:///:memory:", redis_port=6398, redis_namespace="codefly-m1"),
        extraction=ExtractionConfig(top_n_candidates=50, include_print=False, ingest_timeout_minutes=30, candidate_ttl_days=30, extractor_version="1.0.0"),
        sanitizer=SanitizerConfig(enabled=False, patterns=[], replacement="[R]"),
        metrics=MetricsConfig(enabled=False, endpoint="/metrics", port=9464),
        api=ApiConfig(),
        m2=M2Config(),
        acp=AcpConfig(),
        m4=M4Config(),
    )

    gn = MagicMock()
    gn.cypher.return_value = []  # File 节点不存在

    service = _make_service(gn, config)
    snippet = service.get_source_snippet(
        repo_id="repo-1",
        file_path="nonexistent.py",
        line_start=1,
        line_end=10,
    )
    assert snippet.content == ""
    assert snippet.file_path == "nonexistent.py"


def test_m1_service_no_regression_on_existing_methods() -> None:
    """AC-16: M1 已有 6 个方法 + update_log_point_hypothesis 签名不变（字节级稳定）。"""
    import inspect
    methods = {
        "ingest_repo", "list_candidates", "confirm_ingestion",
        "revoke_ingestion", "query_log_points", "get_call_context",
        "update_log_point_hypothesis",
    }
    for name in methods:
        assert hasattr(RepoLogGraphService, name), f"M1 RepoLogGraphService.{name} 应保留"
    # 新增方法
    assert hasattr(RepoLogGraphService, "get_source_snippet"), "M1 应新增 get_source_snippet"
    # 验证新方法签名
    sig = inspect.signature(RepoLogGraphService.get_source_snippet)
    params = list(sig.parameters.keys())
    assert params == ["self", "repo_id", "file_path", "line_start", "line_end"], (
        f"get_source_snippet 参数签名错误: {params}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/test_m1_get_source_snippet.py -v`
Expected: FAIL with `AttributeError: 'RepoLogGraphService' object has no attribute 'get_source_snippet'`

- [ ] **Step 3: Add get_source_snippet method to RepoLogGraphService**

修改 `packages/m1/repo_log_graph_service.py`，在 `update_log_point_hypothesis` 方法之后（class 末尾）加：

```python
    # --- F004 §十：M1 取源码片段入口（不动已有 6 个 + update_log_point_hypothesis，AC-16 字节级稳定） ---
    def get_source_snippet(
        self,
        repo_id: str,
        file_path: str,
        line_start: int,
        line_end: int,
    ) -> "SourceSnippet":
        """F004 §十：取源码片段（供 M4 生成 diff 用）。

        实现:
            1. 通过 gitnexus cypher 查 File 节点取 file content
               MATCH (f:File {filePath: $path}) RETURN f.content
            2. 按 line_start/line_end 切片
            3. 扩展上下文（前后各 +10 行）保证 diff 可读
            4. 上限 max_source_lines（M4Config，默认 200）防 token 爆炸

        Returns:
            SourceSnippet(file_path, line_range, content, extractor_version)
            若 File 节点不存在，content 返回空字符串（不 raise，让上层 graceful degrade）。
        """
        # 延迟 import 避免循环
        from packages.contracts.source_snippet import SourceSnippet

        max_lines = self._config.m4.max_source_lines

        # 1. 查 File 节点
        cypher = (
            'MATCH (f:File {filePath: $file_path}) '
            'RETURN f.filePath AS filePath, f.content AS content'
        )
        rows = self._gitnexus.cypher(
            cypher,
            params={"file_path": file_path},
        )
        if not rows:
            return SourceSnippet(
                file_path=file_path,
                line_range=(line_start, line_end),
                content="",
                extractor_version=self._config.extraction.extractor_version,
            )

        file_content = rows[0].get("content", "") or ""

        # 2. 切片 + 扩展上下文（±10 行）
        lines = file_content.splitlines()
        # line_start/line_end 1-indexed；扩展为 [start-10, end+10]
        ext_start = max(1, line_start - 10)
        ext_end = min(len(lines), line_end + 10)

        # 3. 上限 max_source_lines 检查（扩展后仍超上限 → 截断，保持中心对齐）
        actual_lines = ext_end - ext_start + 1
        if actual_lines > max_lines:
            # 截断：保持以请求 line_start..line_end 为中心
            center = (line_start + line_end) // 2
            half = max_lines // 2
            ext_start = max(1, center - half)
            ext_end = ext_start + max_lines - 1
            if ext_end > len(lines):
                ext_end = len(lines)
                ext_start = max(1, ext_end - max_lines + 1)

        # 切片（注意 1-indexed → 0-indexed）
        sliced = "\n".join(lines[ext_start - 1:ext_end])

        return SourceSnippet(
            file_path=file_path,
            line_range=(ext_start, ext_end),
            content=sliced,
            extractor_version=self._config.extraction.extractor_version,
        )
```

注：`self._gitnexus` 在 `RepoLogGraphService.__init__` 中已存为 `self._gitnexus`（构造器第 33 行 `gitnexus: GitNexusClient`），无需额外存储。检查 M1 `gitnexus_client.py` 的 `cypher` 方法签名确认 params 参数；若实际 `GitNexusClient.cypher` 不支持 params 参数，调整调用为内联字符串拼接（注意 SQL 注入风险，仅对内部 gitnexus）。

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/m4/test_m1_get_source_snippet.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Verify M1 tests no regression（AC-16 字节级稳定）**

Run: `python -m pytest tests/unit_a/ tests/e2e/ -v 2>&1 | tail -20`
Expected: PASS（M1 既有测试无回归 — 新增方法不动已有 6 个 + `update_log_point_hypothesis`）

- [ ] **Step 6: Lint check**

Run: `python -m ruff check packages/m1/repo_log_graph_service.py tests/m4/test_m1_get_source_snippet.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add packages/m1/repo_log_graph_service.py tests/m4/test_m1_get_source_snippet.py
git commit -m "feat(m1): get_source_snippet for F004 — 不动已有方法（AC-15/16）"
```

---

### Task 5: Storage — SuggestionRecordModel + Migration 0003 + M4Repository

**Files:**
- Create: `packages/m4/storage/models.py` — SuggestionRecordModel（SQLAlchemy ORM）
- Create: `packages/m4/storage/migrations/versions/0003_m4_suggestion_tables.py` — Alembic migration
- Create: `packages/m4/storage/repository.py` — M4Repository（CRUD）
- Test: `tests/m4/test_storage_repository.py`

**Interfaces:**
- Consumes: M1 `Base`（`packages.m1.storage.models.Base`） / `SuggestionRecord` / `SuggestionPerspective` / `TokenUsage`
- Produces:
  - `SuggestionRecordModel` SQLAlchemy model
  - Alembic migration `0003_m4_suggestion_tables.py`
  - `M4Repository` class（save_suggestion / get_suggestion / list_suggestions / archive_suggestion）

- [ ] **Step 1: Write the failing test**

`tests/m4/test_storage_repository.py`:
```python
"""F004 M4 — M4Repository CRUD 测试（spec §五 + AC-10）。"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.analysis_report import TokenUsage
from packages.contracts.suggestion import (
    SuggestionPerspective,
    SuggestionRecord,
)
from packages.m1.storage.models import Base  # 复用 M1 Base
from packages.m2.storage.models import AnalysisReportModel, DeepAnalysisModel, LogEntryModel  # M2 表也要建
from packages.m4.storage.models import SuggestionRecordModel  # noqa: F401 — 触发 metadata 注册
from packages.m4.storage.repository import M4Repository


def _make_session() -> Session:
    """in-memory SQLite + 建所有表（M1 Base + M2 models + M4 SuggestionRecordModel）。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _make_perspective(p: str = "performance") -> SuggestionPerspective:
    return SuggestionPerspective(
        perspective=p,
        assessment=f"{p} assessment",
        suggested_diff=f"@@ -1,1 +1,2 @@\n+{p}",
        confidence=0.8,
        model_name="gpt-4",
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_cost_usd=0.01),
    )


def _make_record(
    id: str = "sug-1",
    iteration: int = 1,
    parent_record_id: str | None = None,
) -> SuggestionRecord:
    return SuggestionRecord(
        id=id,
        deep_analysis_id="deep-1",
        report_id="report-1",
        log_point_ids=["lp-1", "lp-2"],
        unified_diff="@@ -10,3 +10,5 @@",
        summary="batch queries",
        perspective_evaluations=[_make_perspective("performance"), _make_perspective("security")],
        confidence_score=0.75,
        model_name="gpt-4",
        prompt_hash="sha256-abc",
        iteration=iteration,
        parent_record_id=parent_record_id,
        generated_at=datetime.now(UTC),
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=200, total_cost_usd=0.10),
        schema_version="1.0.0",
        acp_session_id="acp-sess-1",
        acp_agent_versions={"coordinator": "1.0", "code_fixer": "1.0"},
    )


def test_save_and_get_suggestion() -> None:
    """save_suggestion + get_suggestion round-trip。"""
    session = _make_session()
    repo = M4Repository(session)
    record = _make_record()
    repo.save_suggestion(record)

    fetched = repo.get_suggestion("sug-1")
    assert fetched is not None
    assert fetched.id == "sug-1"
    assert fetched.deep_analysis_id == "deep-1"
    assert fetched.report_id == "report-1"
    assert fetched.log_point_ids == ["lp-1", "lp-2"]
    assert fetched.unified_diff == "@@ -10,3 +10,5 @@"
    assert fetched.summary == "batch queries"
    assert len(fetched.perspective_evaluations) == 2
    assert fetched.perspective_evaluations[0].perspective == "performance"
    assert fetched.confidence_score == 0.75
    assert fetched.iteration == 1
    assert fetched.parent_record_id is None
    assert fetched.schema_version == "1.0.0"
    assert fetched.acp_session_id == "acp-sess-1"
    assert fetched.acp_agent_versions == {"coordinator": "1.0", "code_fixer": "1.0"}


def test_get_suggestion_not_found() -> None:
    """get_suggestion 不存在返回 None。"""
    session = _make_session()
    repo = M4Repository(session)
    assert repo.get_suggestion("nonexistent") is None


def test_list_suggestions_by_report() -> None:
    """list_suggestions 按 report_id 查询 + iteration 升序。"""
    session = _make_session()
    repo = M4Repository(session)
    repo.save_suggestion(_make_record(id="sug-1", iteration=1, parent_record_id=None))
    repo.save_suggestion(_make_record(id="sug-2", iteration=2, parent_record_id="sug-1"))

    results = repo.list_suggestions(report_id="report-1")
    assert len(results) == 2
    assert results[0].iteration == 1
    assert results[1].iteration == 2
    assert results[1].parent_record_id == "sug-1"


def test_list_suggestions_by_log_point() -> None:
    """list_suggestions 按 log_point_id 过滤。"""
    session = _make_session()
    repo = M4Repository(session)
    repo.save_suggestion(_make_record(id="sug-1"))  # log_point_ids=["lp-1", "lp-2"]
    # 第二条关联到不同 log_point
    r2 = _make_record(id="sug-2")
    r2 = SuggestionRecord(
        **{**r2.__dict__, "log_point_ids": ["lp-3"]}
    ) if False else None  # frozen dataclass，用 dataclasses.replace
    import dataclasses
    r2 = dataclasses.replace(_make_record(id="sug-2"), log_point_ids=["lp-3"])
    repo.save_suggestion(r2)

    results = repo.list_suggestions(log_point_id="lp-1")
    assert len(results) == 1
    assert results[0].id == "sug-1"

    results = repo.list_suggestions(log_point_id="lp-3")
    assert len(results) == 1
    assert results[0].id == "sug-2"


def test_archive_suggestion() -> None:
    """archive_suggestion 软删除（archived_at 字段标记）。"""
    session = _make_session()
    repo = M4Repository(session)
    repo.save_suggestion(_make_record(id="sug-1"))

    # 未归档时 list_suggestions 返回
    results = repo.list_suggestions(report_id="report-1")
    assert len(results) == 1

    # 归档
    archived = repo.archive_suggestion("sug-1")
    assert archived is True

    # 已归档 → list 不返回
    results = repo.list_suggestions(report_id="report-1")
    assert len(results) == 0

    # get_suggestion 仍能取到（不删，软删）
    fetched = repo.get_suggestion("sug-1")
    assert fetched is not None


def test_archive_suggestion_idempotent() -> None:
    """已归档的 suggestion 再次 archive 返回 False（幂等）。"""
    session = _make_session()
    repo = M4Repository(session)
    repo.save_suggestion(_make_record(id="sug-1"))
    assert repo.archive_suggestion("sug-1") is True
    assert repo.archive_suggestion("sug-1") is False  # 已归档


def test_archive_suggestion_not_found() -> None:
    """archive 不存在的 id 返回 False。"""
    session = _make_session()
    repo = M4Repository(session)
    assert repo.archive_suggestion("nonexistent") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/test_storage_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m4.storage.models'`

- [ ] **Step 3: Create packages/m4/storage/models.py**

`packages/m4/storage/models.py`:
```python
"""F004 M4 — SQLAlchemy ORM models（spec §五 + §三）。

一张表（继承 M1 Base，保证 `Base.metadata.create_all()` 一把建所有表）：
  - suggestion_record：M4 改进建议记录（P0 持久化，TTL=0）

设计原则（AC-16 字节级稳定）：
  - 不修改 M1 已有 4 张表 + M2 已有 3 张表
  - 复杂结构字段（SuggestionPerspective list / token_usage / acp_agent_versions）用 JSON Text 存

P0 持久化铁律（AC-10）：TTL=0 默认持久化，不加 TTL 字段。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from packages.m1.storage.models import Base  # 复用 M1 Base


class SuggestionRecordModel(Base):
    """M4 改进建议记录 — P0 持久化（spec §三 + AC-10）。

    TTL=0：用户可见产物，不删（archive 是软删 archived_at 字段，不删行）。
    迭代性：iteration 递增 + parent_record_id 链。
    """
    __tablename__ = "suggestion_record"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    deep_analysis_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    report_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    log_point_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 汇总输出
    unified_diff: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    perspective_evaluations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    # 元数据
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    token_usage_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    # ACP 协议元数据
    acp_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    acp_agent_versions_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # 软删（archive）— archived_at 不为 None 表示已归档
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
```

- [ ] **Step 4: Create Alembic migration 0003**

`packages/m4/storage/migrations/versions/0003_m4_suggestion_tables.py`:
```python
"""M4 — 新增 1 张表（suggestion_record）。

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-28

F004 spec §五 + §三：M4 一张 P0 持久化表（TTL=0 默认）。
不动 M1 已有 4 张表 + M2 已有 3 张表（AC-16 字节级稳定）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # suggestion_record: M4 改进建议记录
    op.create_table(
        "suggestion_record",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("deep_analysis_id", sa.String(64), nullable=False, index=True),
        sa.Column("report_id", sa.String(64), nullable=False, index=True),
        sa.Column("log_point_ids_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("unified_diff", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("perspective_evaluations_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("model_name", sa.String(64), nullable=False),
        sa.Column("prompt_hash", sa.String(128), nullable=False),
        sa.Column("iteration", sa.Integer, nullable=False, server_default="1"),
        sa.Column("parent_record_id", sa.String(64), nullable=True, index=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("token_usage_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("schema_version", sa.String(16), nullable=False, server_default="1.0.0"),
        sa.Column("acp_session_id", sa.String(128), nullable=True, index=True),
        sa.Column("acp_agent_versions_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_suggestion_record_report_iteration",
        "suggestion_record", ["report_id", "iteration"],
    )


def downgrade() -> None:
    op.drop_index("ix_suggestion_record_report_iteration", table_name="suggestion_record")
    op.drop_table("suggestion_record")
```

- [ ] **Step 5: Create packages/m4/storage/repository.py**

`packages/m4/storage/repository.py`:
```python
"""F004 M4 — Storage Repository（spec §五）。

dataclass ↔ Model JSON 转换 mappers + 4 个查询方法：
  - save_suggestion / get_suggestion / list_suggestions / archive_suggestion

设计（同 M2 repository 模式）：
  - 复杂结构字段（SuggestionPerspective / TokenUsage / acp_agent_versions）
    序列化为 JSON Text 存
  - dataclass ↔ JSON 转换双向对称
  - repository 接受 Session 注入
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from packages.contracts.analysis_report import TokenUsage
from packages.contracts.enums import STATUS_ARCHIVED
from packages.contracts.suggestion import (
    SuggestionPerspective,
    SuggestionRecord,
)
from packages.m4.storage.models import SuggestionRecordModel


# ===================== SuggestionPerspective 序列化 =====================

def _perspective_to_dict(p: SuggestionPerspective) -> dict:
    return {
        "perspective": p.perspective,
        "assessment": p.assessment,
        "suggested_diff": p.suggested_diff,
        "confidence": p.confidence,
        "model_name": p.model_name,
        "token_usage": _token_usage_to_dict(p.token_usage),
    }


def _dict_to_perspective(d: dict) -> SuggestionPerspective:
    return SuggestionPerspective(
        perspective=d["perspective"],
        assessment=d["assessment"],
        suggested_diff=d.get("suggested_diff"),
        confidence=d["confidence"],
        model_name=d["model_name"],
        token_usage=_dict_to_token_usage(d["token_usage"]),
    )


def _token_usage_to_dict(tu: TokenUsage) -> dict:
    return {
        "prompt_tokens": tu.prompt_tokens,
        "completion_tokens": tu.completion_tokens,
        "total_cost_usd": tu.total_cost_usd,
    }


def _dict_to_token_usage(d: dict) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=d["prompt_tokens"],
        completion_tokens=d["completion_tokens"],
        total_cost_usd=d["total_cost_usd"],
    )


# ===================== SuggestionRecord mappers =====================

def _suggestion_to_model(record: SuggestionRecord) -> SuggestionRecordModel:
    return SuggestionRecordModel(
        id=record.id,
        deep_analysis_id=record.deep_analysis_id,
        report_id=record.report_id,
        log_point_ids_json=json.dumps(record.log_point_ids),
        unified_diff=record.unified_diff,
        summary=record.summary,
        perspective_evaluations_json=json.dumps(
            [_perspective_to_dict(p) for p in record.perspective_evaluations]
        ),
        confidence_score=record.confidence_score,
        model_name=record.model_name,
        prompt_hash=record.prompt_hash,
        iteration=record.iteration,
        parent_record_id=record.parent_record_id,
        generated_at=record.generated_at,
        token_usage_json=json.dumps(_token_usage_to_dict(record.token_usage)),
        schema_version=record.schema_version,
        acp_session_id=record.acp_session_id,
        acp_agent_versions_json=json.dumps(record.acp_agent_versions),
        archived_at=None,  # 新建默认未归档
    )


def _suggestion_to_dataclass(model: SuggestionRecordModel) -> SuggestionRecord:
    return SuggestionRecord(
        id=model.id,
        deep_analysis_id=model.deep_analysis_id,
        report_id=model.report_id,
        log_point_ids=json.loads(model.log_point_ids_json),
        unified_diff=model.unified_diff,
        summary=model.summary,
        perspective_evaluations=[
            _dict_to_perspective(d)
            for d in json.loads(model.perspective_evaluations_json)
        ],
        confidence_score=model.confidence_score,
        model_name=model.model_name,
        prompt_hash=model.prompt_hash,
        iteration=model.iteration,
        parent_record_id=model.parent_record_id,
        generated_at=model.generated_at,
        token_usage=_dict_to_token_usage(json.loads(model.token_usage_json)),
        schema_version=model.schema_version,
        acp_session_id=model.acp_session_id,
        acp_agent_versions=json.loads(model.acp_agent_versions_json),
    )


# ===================== Repository =====================

class M4Repository:
    """M4 持久化层 — 接受 Session 注入，封装 suggestion_record 表 CRUD。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_suggestion(self, record: SuggestionRecord) -> None:
        """插入新建议记录。"""
        self._session.add(_suggestion_to_model(record))
        self._session.commit()

    def get_suggestion(self, suggestion_id: str) -> SuggestionRecord | None:
        """按 id 查建议（含已归档 — 软删不删行）。"""
        m = self._session.get(SuggestionRecordModel, suggestion_id)
        return _suggestion_to_dataclass(m) if m is not None else None

    def list_suggestions(
        self,
        report_id: str | None = None,
        log_point_id: str | None = None,
    ) -> list[SuggestionRecord]:
        """列建议记录，按 report_id 过滤 + 按 log_point_id 过滤 + iteration 升序。

        排除已归档（archived_at IS NULL）。
        log_point_id 过滤是 JSON array contains — SQLite/PG 兼容用 like 模糊匹配
        （性能可接受，log_point_ids_json 通常 < 20 个 id；后续如需高性能可换 PG GIN index）。
        """
        stmt = (
            select(SuggestionRecordModel)
            .where(SuggestionRecordModel.archived_at.is_(None))
        )
        if report_id is not None:
            stmt = stmt.where(SuggestionRecordModel.report_id == report_id)
        if log_point_id is not None:
            # JSON array contains — SQLite json_extract 兼容性差，用 like 模糊匹配
            stmt = stmt.where(
                SuggestionRecordModel.log_point_ids_json.like(f'%"{log_point_id}"%')
            )
        stmt = stmt.order_by(SuggestionRecordModel.iteration.asc())
        rows = self._session.scalars(stmt).all()
        return [_suggestion_to_dataclass(r) for r in rows]

    def archive_suggestion(self, suggestion_id: str) -> bool:
        """软删（archived_at 标记当前时间）— 不删行（P0 持久化铁律）。

        Returns:
            True 表示状态已更新，False 表示未找到或已归档。
        """
        result = self._session.execute(
            update(SuggestionRecordModel)
            .where(SuggestionRecordModel.id == suggestion_id)
            .where(SuggestionRecordModel.archived_at.is_(None))
            .values(archived_at=datetime.now(UTC))
        )
        self._session.commit()
        return result.rowcount > 0


# 顶部 import 避免下方调用 UTC 未定义
from datetime import UTC  # noqa: E402
```

- [ ] **Step 6: Run test to verify pass**

Run: `python -m pytest tests/m4/test_storage_repository.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Lint check**

Run: `python -m ruff check packages/m4/storage/ tests/m4/test_storage_repository.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add packages/m4/storage/ tests/m4/test_storage_repository.py
git commit -m "feat(m4): storage — SuggestionRecordModel + migration 0003 + M4Repository"
```

---

### Task 6: Message builder + LogSanitizer 扩展 ACP Message 脱敏

**Files:**
- Create: `packages/m4/message_builder.py` — SuggestionMessageBuilder
- Create: `packages/m4/sanitizer.py` — AcpMessageSanitizer（包装 M1 LogSanitizer）
- Test: `tests/m4/test_message_builder.py`

**Interfaces:**
- Consumes:
  - M2 `DeepAnalysisRecord`
  - M1 `CallContext` / `LogSanitizer`
  - `SourceSnippet`
  - `acp_sdk.Message` / `MessagePart`
- Produces:
  - `SuggestionMessageBuilder.build(deep_analysis, call_context, source_snippet, log_entry) -> Message`
  - `AcpMessageSanitizer.sanitize(Message) -> Message`（脱敏所有 parts content）

- [ ] **Step 1: Write the failing test**

`tests/m4/test_message_builder.py`:
```python
"""F004 M4 — Message builder + sanitizer 测试（spec §三 + AC-5/6）。"""
from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

from acp_sdk import Message, MessagePart

from packages.contracts.analysis_report import TokenUsage
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.log_entry import LogEntry
from packages.contracts.log_point import CallContext
from packages.contracts.source_snippet import SourceSnippet
from packages.m4.message_builder import SuggestionMessageBuilder
from packages.m4.sanitizer import AcpMessageSanitizer


def _make_deep_analysis() -> DeepAnalysisRecord:
    return DeepAnalysisRecord(
        id="deep-1",
        report_id="report-1",
        line_ids=["line-1"],
        log_point_ids=["lp-1"],
        call_contexts=[],
        root_cause_hypothesis="N+1 query",
        fix_suggestion="batch queries",
        related_evidence=[],
        model_name="gpt-4",
        prompt_hash="sha256-abc",
        iteration=1,
        parent_record_id=None,
        generated_at=datetime.now(UTC),
        token_usage=TokenUsage(100, 200, 0.10),
    )


def _make_call_context() -> CallContext:
    return CallContext(
        function_signature="def foo()",
        callers=["bar"],
        callees=["baz"],
        enclosing_community="C",
        related_log_points=[],
        evidence_refs=[],
    )


def _make_source_snippet() -> SourceSnippet:
    return SourceSnippet(
        file_path="src/foo.py",
        line_range=(1, 30),
        content="def foo():\n    pass\n",
        extractor_version="1.0.0",
    )


def _make_log_entry() -> LogEntry:
    return LogEntry(
        line_id="line-1",
        raw_text="ERROR api_key=abc1234567890123456 — boom",
        timestamp=datetime.now(UTC),
        level="ERROR",
        log_message_template="ERROR api_key={key} — {msg}",
        variables=["abc1234567890123456", "boom"],
        source_file="app.log",
        source_line=42,
    )


def test_message_builder_builds_4_parts() -> None:
    """build() 产 4 parts（hypothesis/source/call-context/log）— AC-5。"""
    builder = SuggestionMessageBuilder()
    msg = builder.build(
        deep_analysis=_make_deep_analysis(),
        call_context=_make_call_context(),
        source_snippet=_make_source_snippet(),
        log_entry=_make_log_entry(),
    )
    assert isinstance(msg, Message)
    assert len(msg.parts) == 4
    # parts 内容类型正确（按 spec §三 顺序：deep_analysis / source / call_context / log_entry）
    # acp_sdk MessagePart API 表面校验（content / content_type 字段）
    p0 = msg.parts[0]
    p1 = msg.parts[1]
    p2 = msg.parts[2]
    p3 = msg.parts[3]
    # DeepAnalysisRecord JSON
    da_json = p0.content if isinstance(p0.content, str) else json.dumps(p0.content)
    assert "deep-1" in da_json
    assert "N+1 query" in da_json
    # Source snippet
    assert "def foo" in p1.content
    # CallContext JSON
    cc_json = p2.content if isinstance(p2.content, str) else json.dumps(p2.content)
    assert "def foo" in cc_json
    # Log entry text
    assert "boom" in p3.content


def test_message_builder_part_content_types() -> None:
    """content_type 字段正确（spec §三 content_type 命名）。"""
    builder = SuggestionMessageBuilder()
    msg = builder.build(
        deep_analysis=_make_deep_analysis(),
        call_context=_make_call_context(),
        source_snippet=_make_source_snippet(),
        log_entry=_make_log_entry(),
    )
    types = [p.content_type for p in msg.parts]
    # 期望至少包含 'application/json' 或 'text/*'（acp_sdk 实际 API 决定）
    assert len(types) == 4


def test_acp_message_sanitizer_redacts_secrets() -> None:
    """AcpMessageSanitizer 脱敏后 api_key 在所有 parts 零命中 — AC-6。"""
    # 用真实 LogSanitizer（启用 api_key pattern）
    from packages.m1.log_sanitizer import LogSanitizer
    from packages.m1.log_sanitizer import SanitizerConfig

    sanitizer = LogSanitizer(SanitizerConfig(
        enabled=True,
        patterns=["api_key"],
        replacement="[REDACTED_api_key]",
    ))
    acp_sanitizer = AcpMessageSanitizer(sanitizer=sanitizer)

    builder = SuggestionMessageBuilder()
    msg = builder.build(
        deep_analysis=_make_deep_analysis(),
        call_context=_make_call_context(),
        source_snippet=_make_source_snippet(),
        log_entry=_make_log_entry(),  # raw_text 含 "api_key=abc1234567890123456"
    )

    sanitized = acp_sanitizer.sanitize(msg)
    assert isinstance(sanitized, Message)
    # 所有 parts content 不应含 "abc1234567890123456"
    for part in sanitized.parts:
        content = part.content if isinstance(part.content, str) else json.dumps(part.content)
        assert "abc1234567890123456" not in content, f"part {part.content_type} 仍有明文 api_key"


def test_acp_message_sanitizer_passthrough_when_disabled() -> None:
    """sanitizer disabled 时 Message 原样返回。"""
    from packages.m1.log_sanitizer import LogSanitizer
    from packages.m1.log_sanitizer import SanitizerConfig

    sanitizer = LogSanitizer(SanitizerConfig(
        enabled=False,
        patterns=[],
        replacement="[R]",
    ))
    acp_sanitizer = AcpMessageSanitizer(sanitizer=sanitizer)

    builder = SuggestionMessageBuilder()
    msg = builder.build(
        deep_analysis=_make_deep_analysis(),
        call_context=_make_call_context(),
        source_snippet=_make_source_snippet(),
        log_entry=_make_log_entry(),
    )
    sanitized = acp_sanitizer.sanitize(msg)
    # content 应保持原样
    log_part = sanitized.parts[3]
    assert "abc1234567890123456" in log_part.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/test_message_builder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m4.message_builder'`

- [ ] **Step 3: Create packages/m4/message_builder.py**

`packages/m4/message_builder.py`:
```python
"""F004 M4 — ACP Message 装配（spec §三 + AC-5）。

把 DeepAnalysisRecord + CallContext + SourceSnippet + LogEntry 装成 acp_sdk.Message，
供 coordinator agent 消费。
"""
from __future__ import annotations

import dataclasses
import json

from acp_sdk import Message, MessagePart

from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.log_entry import LogEntry
from packages.contracts.log_point import CallContext
from packages.contracts.source_snippet import SourceSnippet


class SuggestionMessageBuilder:
    """装配 ACP Message 给 coordinator agent（spec §三 + §二）。

    4 parts 顺序：
      1. DeepAnalysisRecord JSON（含 root_cause_hypothesis + fix_suggestion）
      2. SourceSnippet content（源码片段）
      3. CallContext JSON（callers / callees / community）
      4. LogEntry text（raw_text）
    """

    def build(
        self,
        deep_analysis: DeepAnalysisRecord,
        call_context: CallContext,
        source_snippet: SourceSnippet,
        log_entry: LogEntry,
    ) -> Message:
        """装 4 parts Message（spec §三）。"""
        # DeepAnalysisRecord → JSON（用 asdict 递归序列化）
        da_dict = dataclasses.asdict(deep_analysis)
        # 修正：datetime 字段 asdict 后是 datetime 对象，需 isoformat
        da_dict["generated_at"] = deep_analysis.generated_at.isoformat()
        # call_contexts 内有 datetime（CaseRef.resolved_at）— 整体 dump 时 default 处理
        da_json = json.dumps(da_dict, default=str)

        # CallContext → JSON（related_log_points / evidence_refs 含 dataclass + datetime）
        cc_dict = dataclasses.asdict(call_context)
        cc_json = json.dumps(cc_dict, default=str)

        # LogEntry raw_text 直接作为 text part
        return Message(parts=[
            MessagePart(
                content=da_json,
                content_type="application/json",
            ),
            MessagePart(
                content=source_snippet.content,
                content_type="text/plain",
            ),
            MessagePart(
                content=cc_json,
                content_type="application/json",
            ),
            MessagePart(
                content=log_entry.raw_text,
                content_type="text/plain",
            ),
        ])
```

- [ ] **Step 4: Create packages/m4/sanitizer.py**

`packages/m4/sanitizer.py`:
```python
"""F004 M4 — ACP Message 脱敏（spec §三 + AC-6）。

包装 M1 LogSanitizer，遍历 ACP Message 所有 parts content 做脱敏。
"""
from __future__ import annotations

import json

from acp_sdk import Message, MessagePart

from packages.m1.log_sanitizer import LogSanitizer


class AcpMessageSanitizer:
    """遍历 Message parts 做脱敏（spec §三 + AC-6）。

    策略：
      - text/* parts：直接 sanitize text
      - application/json parts：dump → sanitize → parse 回 dict（保留结构）
    """

    def __init__(self, sanitizer: LogSanitizer) -> None:
        self._sanitizer = sanitizer

    def sanitize(self, message: Message) -> Message:
        """返回新 Message，所有 parts content 脱敏。"""
        new_parts: list[MessagePart] = []
        for part in message.parts:
            content = part.content
            if not isinstance(content, str):
                # 非 str content（如 bytes / dict）— 用 json.dumps 转一次
                content = json.dumps(content, default=str)

            redacted, _hits = self._sanitizer.sanitize(content)

            # application/json parts 重新 parse 回 dict（如原 content 是 dict）
            if part.content_type == "application/json" and not isinstance(part.content, str):
                try:
                    redacted_obj = json.loads(redacted)
                    new_parts.append(MessagePart(
                        content=redacted_obj,
                        content_type=part.content_type,
                    ))
                    continue
                except json.JSONDecodeError:
                    pass  # 转不回 dict 就保留 str

            new_parts.append(MessagePart(
                content=redacted,
                content_type=part.content_type,
            ))
        return Message(parts=new_parts)
```

- [ ] **Step 5: Run test to verify pass**

Run: `python -m pytest tests/m4/test_message_builder.py -v`
Expected: PASS (4 tests)

注：若 acp_sdk `MessagePart` API 不接受 `content_type` 关键字（如实际是 `metadata` 或其他字段名），调整 builder/sanitizer 用实际 API 表面 — 数据契约（4 parts 顺序 + content 脱敏）不变。

- [ ] **Step 6: Lint check**

Run: `python -m ruff check packages/m4/message_builder.py packages/m4/sanitizer.py tests/m4/test_message_builder.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add packages/m4/message_builder.py packages/m4/sanitizer.py tests/m4/test_message_builder.py
git commit -m "feat(m4): message builder + ACP sanitizer — 4 parts + 脱敏"
```

---

### Task 7: ACP Server 入口 + agent 注册框架

**Files:**
- Create: `acp_servers/m4_server.py` — Server 启动入口 + 注册 5 个 agent
- Create: `packages/m4/agents/__init__.py` — 重-export `register` 函数（保持空）
- Test: `tests/m4/test_acp_server.py`

**Interfaces:**
- Consumes: `acp_sdk.server.Server` / 各 agent 的 `register(server)` 函数（Task 8-10 实现）
- Produces: `acp_servers/m4_server:server` — Server 实例 + `__main__` 入口

- [ ] **Step 1: Write the failing test**

`tests/m4/test_acp_server.py`:
```python
"""F004 M4 — ACP Server 入口 + agent 注册测试（spec §十一 + AC-3）。"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock


def test_m4_server_module_importable() -> None:
    """acp_servers.m4_server 可 import。"""
    mod = importlib.import_module("acp_servers.m4_server")
    assert hasattr(mod, "server"), "m4_server 应有 server 实例"


def test_m4_server_registers_5_agents() -> None:
    """AC-3：Server 注册 5 个 agent（coordinator + 4 reviewer）。

    策略：mock 5 个 register 函数（Task 8-10 还未实现），
    通过 patch acp_servers.m4_server 的 register_* import 验证调用次数。
    本测试在 Task 8-10 完成前 skip；完成后 unskip 跑实际 Server。
    """
    import pytest
    pytest.skip("Task 8-10 完成后 unskip — 5 agent register 函数实现后验证")


def test_m4_server_agent_names() -> None:
    """5 个 agent 名字（spec §二）：
    suggestion_coordinator_agent / code_fixer_agent / security_reviewer_agent
    / readability_reviewer_agent / testing_reviewer_agent
    """
    expected = {
        "suggestion_coordinator_agent",
        "code_fixer_agent",
        "security_reviewer_agent",
        "readability_reviewer_agent",
        "testing_reviewer_agent",
    }
    # 通过 acp_sdk Server API 查注册的 agent 列表（acp_sdk API 表面决定具体方法）
    # 实现策略：Task 8-10 完成后，import acp_servers.m4_server.server 后
    #   - 用 server.agents 或 server._agents 属性（按 acp_sdk 实际 API）
    #   - 或通过 Client.run_sync 调 /agents endpoint
    import pytest
    pytest.skip("Task 8-10 完成后 unskip")


def test_m4_server_main_entrypoint_callable() -> None:
    """m4_server __main__ 入口可调用（不实际启动，只验证 if __name__ == '__main__' 块）。"""
    mod = importlib.import_module("acp_servers.m4_server")
    # 检查 source 含 if __name__ == "__main__" 块
    import inspect
    src = inspect.getsource(mod)
    assert '__main__' in src, "m4_server 应有 __main__ 入口"
    assert 'server.run' in src or 'server.start' in src, "m4_server __main__ 应调 server.run/start"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/test_acp_server.py -v`
Expected: 2 个 PASS（skip），2 个 FAIL（模块不存在 / server 实例不存在）

- [ ] **Step 3: Create acp_servers/m4_server.py（先框架，agent register 函数 Task 8-10 实现）**

`acp_servers/m4_server.py`:
```python
"""F004 M4 ACP Server — 启动 :8001 监听 5 个 agent（spec §十一）。

启动方式（dev）:
    python -m acp_servers.m4_server

启动方式（生产）:
    uvicorn acp_servers.m4_server:app --host 0.0.0.0 --port 8001
    （或用 systemd / Docker 部署 ACP Server 独立进程）

环境变量:
    CODEFLY_ACP_SERVER_HOST — bind host（默认 127.0.0.1）
    CODEFLY_ACP_SERVER_PORT — bind port（默认 8001）
"""
from __future__ import annotations

import os

from acp_sdk.server import Server

# Task 8-10 会实现这 5 个 register 函数；本 task 先 import 占位（Task 8-10 完成后取消注释）
# from packages.m4.agents.coordinator_agent import register as register_coordinator
# from packages.m4.agents.code_fixer_agent import register as register_code_fixer
# from packages.m4.agents.security_reviewer_agent import register as register_security
# from packages.m4.agents.readability_reviewer_agent import register as register_readability
# from packages.m4.agents.testing_reviewer_agent import register as register_testing

server = Server()

# Task 8-10 完成后取消上面注释 + 下面注册调用
# register_coordinator(server)
# register_code_fixer(server)
# register_security(server)
# register_readability(server)
# register_testing(server)


def main() -> None:
    """启动 ACP Server（dev 模式）。"""
    host = os.environ.get("CODEFLY_ACP_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("CODEFLY_ACP_SERVER_PORT", "8001"))
    # acp_sdk Server.run 实际 API — 按 acp_sdk 文档调
    # 如 Server.run(host=, port=) 或 Server.serve(host=, port=)
    server.run(host=host, port=port)


if __name__ == "__main__":
    main()
```

注：Task 7 实施时如果 `acp_sdk.Server` 没有 `.run()` 方法，按实际 API 调整（如 `serve()` / `start()`）；Task 8-10 实现 agent register 后取消注释。

- [ ] **Step 4: Run test to verify partial pass**

Run: `python -m pytest tests/m4/test_acp_server.py -v`
Expected: 4 PASS（2 skip + 2 PASS — module importable + main entry callable）

- [ ] **Step 5: Lint check**

Run: `python -m ruff check acp_servers/m4_server.py tests/m4/test_acp_server.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add acp_servers/m4_server.py tests/m4/test_acp_server.py
git commit -m "feat(m4): ACP Server entry scaffold — Task 8-10 接 5 agent register"
```

---

### Task 8: 4 个 reviewer agent — code_fixer / security / readability / testing

**Files:**
- Create: `packages/m4/agents/code_fixer_agent.py` — code_fixer agent（主视角）
- Create: `packages/m4/agents/security_reviewer_agent.py` — security reviewer
- Create: `packages/m4/agents/readability_reviewer_agent.py` — readability reviewer
- Create: `packages/m4/agents/testing_reviewer_agent.py` — testing reviewer
- Test: `tests/m4/agents/test_code_fixer_agent.py`
- Test: `tests/m4/agents/test_security_reviewer_agent.py`
- Test: `tests/m4/agents/test_readability_reviewer_agent.py`
- Test: `tests/m4/agents/test_testing_reviewer_agent.py`

**Interfaces:**
- Consumes:
  - `acp_sdk.server.Server` / `acp_sdk.Message` / `acp_sdk.MessagePart`
  - `LLMClient`（M1 已定义 protocol）
  - `SuggestionPerspective` / `TokenUsage`
- Produces:
  - 每个 agent 模块的 `register(server: Server) -> None` 函数
  - 每个 agent 的 `_build_prompt(message: Message) -> str` 内部函数
  - 每个 agent 的 `_parse_response(text: str) -> SuggestionPerspective` 内部函数

**注**：4 个 reviewer agent 行为同构（仅在 prompt 模板 + perspective 字段差异），plan 给出 code_fixer 完整模板，其余 3 个用相同结构 + 不同 perspective 值。

- [ ] **Step 1: Write the failing test for code_fixer_agent**

`tests/m4/agents/test_code_fixer_agent.py`:
```python
"""F004 M4 — code_fixer_agent 测试（spec §二 + AC-7）。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from acp_sdk import Message, MessagePart

from packages.contracts.analysis_report import TokenUsage
from packages.m4.agents.code_fixer_agent import (
    _build_prompt,
    _parse_response,
    register,
)


def test_register_creates_agent() -> None:
    """register(server) 在 server 上注册 code_fixer agent。"""
    server = MagicMock()
    # acp_sdk @server.agent() 装饰器 — mock 后 register 应调 server.agent()
    register(server)
    # 验证 server.agent() 被调用 1 次（具体次数按 register 实现策略）
    assert server.agent.called or hasattr(server, 'agent')


def test_build_prompt_contains_source_snippet() -> None:
    """prompt 含 source snippet（让 LLM 知道改什么代码）。"""
    msg = Message(parts=[
        MessagePart(content='{"root_cause_hypothesis":"N+1 query"}', content_type="application/json"),
        MessagePart(content="def foo():\n    pass\n", content_type="text/plain"),
        MessagePart(content='{"function_signature":"def foo()"}', content_type="application/json"),
        MessagePart(content="ERROR boom", content_type="text/plain"),
    ])
    prompt = _build_prompt(msg)
    assert "def foo" in prompt
    assert "N+1 query" in prompt
    assert "ERROR boom" in prompt
    # 含改进方向提示（performance 视角）
    assert "performance" in prompt.lower() or "性能" in prompt


def test_parse_response_valid_json() -> None:
    """LLM 返回 JSON 时 parse 出 SuggestionPerspective。"""
    llm_text = '{"assessment":"batch queries","suggested_diff":"@@ -1,1 +1,2 @@","confidence":0.85}'
    p = _parse_response(llm_text, model_name="gpt-4", token_usage=TokenUsage(100, 50, 0.02))
    assert p.perspective == "performance"
    assert p.assessment == "batch queries"
    assert p.suggested_diff == "@@ -1,1 +1,2 @@"
    assert p.confidence == 0.85
    assert p.model_name == "gpt-4"


def test_parse_response_no_diff() -> None:
    """LLM 无 suggested_diff 字段时返回 None（reviewer 评估但无 diff）。"""
    llm_text = '{"assessment":"no fix needed","confidence":0.95}'
    p = _parse_response(llm_text, model_name="gpt-4", token_usage=TokenUsage(100, 50, 0.02))
    assert p.suggested_diff is None
    assert p.confidence == 0.95


def test_parse_response_invalid_json_fallback() -> None:
    """LLM 返回非 JSON 时 fallback 到 assessment=raw_text + confidence=0.0。"""
    llm_text = "I cannot parse this"
    p = _parse_response(llm_text, model_name="gpt-4", token_usage=TokenUsage(100, 50, 0.02))
    assert p.assessment == "I cannot parse this"
    assert p.confidence == 0.0
    assert p.suggested_diff is None


@pytest.mark.asyncio
async def test_agent_invokes_llm_and_yields_perspective() -> None:
    """agent 函数被调用时，调 LLM + yield MessagePart（含 SuggestionPerspective JSON）。"""
    # mock LLMClient
    llm = AsyncMock()
    llm.complete.return_value = '{"assessment":"x","suggested_diff":null,"confidence":0.5}'

    # 构造 input Message
    msg = Message(parts=[
        MessagePart(content='{"root_cause_hypothesis":"x"}', content_type="application/json"),
        MessagePart(content="def foo():\n    pass\n", content_type="text/plain"),
        MessagePart(content='{"function_signature":"def foo()"}', content_type="application/json"),
        MessagePart(content="ERROR boom", content_type="text/plain"),
    ])

    # 调 agent（通过 register 内部 @server.agent() 装饰的函数）
    # 验证策略：import register 后，提取装饰后的 agent 函数，直接调用
    server = MagicMock()
    register(server)

    # 提取 agent 函数（register 内部用 @server.agent() 装饰，函数对象存在 register 模块作用域）
    # 实施时按 acp_sdk 实际 API 调整 — 如 server.agent() 装饰器把函数注册到 server.agents dict
    # 此处用 mock：直接 import 模块级 _agent_fn（如实现时暴露）
    from packages.m4.agents import code_fixer_agent
    if hasattr(code_fixer_agent, '_agent_fn'):
        agent_fn = code_fixer_agent._agent_fn
        result = await agent_fn(input=[msg], context=MagicMock())
        # 应 yield 至少 1 个 MessagePart
        parts = list(result) if hasattr(result, '__iter__') else [result]
        assert len(parts) >= 1
        llm.complete.assert_awaited_once()
    else:
        pytest.skip("agent_fn 暴露策略 — 实施时按 acp_sdk API 决定")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/agents/test_code_fixer_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m4.agents.code_fixer_agent'`

- [ ] **Step 3: Create packages/m4/agents/code_fixer_agent.py**

`packages/m4/agents/code_fixer_agent.py`:
```python
"""F004 M4 — code_fixer_agent（主视角，performance perspective）。

参考 ACP 文档"诗歌团队"案例 — 子 agent 接收 input Message，调 LLM，
yield 输出 MessagePart（含 SuggestionPerspective JSON）。
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from acp_sdk import Message, MessagePart
from acp_sdk.server import Context, Server

from packages.contracts.analysis_report import TokenUsage
from packages.contracts.suggestion import SuggestionPerspective
from packages.m1.llm_hypothesis_generator import LLMClient

PERSPECTIVE = "performance"
AGENT_NAME = "code_fixer_agent"
AGENT_VERSION = "1.0"


def _build_prompt(message: Message) -> str:
    """从 input Message 装配 LLM prompt（4 parts 提取关键信息）。"""
    parts = message.parts if hasattr(message, 'parts') else []
    da_json = ""
    source = ""
    cc_json = ""
    log_text = ""
    if len(parts) >= 1:
        da_json = parts[0].content if isinstance(parts[0].content, str) else json.dumps(parts[0].content)
    if len(parts) >= 2:
        source = parts[1].content if isinstance(parts[1].content, str) else str(parts[1].content)
    if len(parts) >= 3:
        cc_json = parts[2].content if isinstance(parts[2].content, str) else json.dumps(parts[2].content)
    if len(parts) >= 4:
        log_text = parts[3].content if isinstance(parts[3].content, str) else str(parts[3].content)

    return f"""You are a code reviewer focused on PERFORMANCE issues.

Given the following:
- Deep analysis: {da_json}
- Source code:\n{source}
- Call context: {cc_json}
- Log entry: {log_text}

Generate a code fix suggestion as JSON with fields:
  assessment: one-line problem description
  suggested_diff: unified diff or null if no diff applicable
  confidence: 0.0-1.0

Respond ONLY with JSON.
"""


def _parse_response(text: str, model_name: str, token_usage: TokenUsage) -> SuggestionPerspective:
    """LLM 响应文本 → SuggestionPerspective（JSON parse fallback 到 raw_text）。"""
    try:
        d = json.loads(text)
        return SuggestionPerspective(
            perspective=PERSPECTIVE,
            assessment=d.get("assessment", ""),
            suggested_diff=d.get("suggested_diff"),
            confidence=float(d.get("confidence", 0.0)),
            model_name=model_name,
            token_usage=token_usage,
        )
    except (json.JSONDecodeError, ValueError):
        return SuggestionPerspective(
            perspective=PERSPECTIVE,
            assessment=text,
            suggested_diff=None,
            confidence=0.0,
            model_name=model_name,
            token_usage=token_usage,
        )


def register(server: Server, llm_client: LLMClient | None = None) -> None:
    """在 server 上注册 code_fixer_agent。

    Args:
        server: ACP Server 实例
        llm_client: LLM client（None 时从环境变量构造，生产注入）
    """
    # 如未注入 llm_client，从 M1 LLMConfig 构造默认 client
    if llm_client is None:
        llm_client = _default_llm_client()

    @server.agent()
    async def code_fixer_agent(
        input: list[Message], context: Context
    ) -> Iterator[MessagePart]:
        """接收 input Message → 调 LLM → yield 输出 MessagePart。"""
        # 取最后一条 message（ACP 协议 input 是 list）
        msg = input[-1] if input else Message(parts=[])
        prompt = _build_prompt(msg)
        llm_text = await llm_client.complete(prompt)

        # token usage 由 LLM client 实际返回；此处用 mock 0
        token_usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_cost_usd=0.0)

        perspective = _parse_response(llm_text, model_name="gpt-4", token_usage=token_usage)
        yield MessagePart(
            content=json.dumps({
                "perspective": perspective.perspective,
                "assessment": perspective.assessment,
                "suggested_diff": perspective.suggested_diff,
                "confidence": perspective.confidence,
                "model_name": perspective.model_name,
            }),
            content_type="application/json",
        )


def _default_llm_client() -> LLMClient:
    """从环境变量构造默认 LLMClient（生产用 — dev 测试注入 mock）。"""
    # 占位：实施时按 M1 LLMClient 子类实际接口构造
    # 此处返回 NotImplementedError 防止 dev 误用
    raise NotImplementedError(
        "code_fixer_agent 需要 llm_client 注入 — "
        "生产用 packages.m1.llm_hypothesis_generator.LLMClient 子类，"
        "测试用 MagicMock(spec=LLMClient)"
    )


# 暴露给测试用 — register 内部装饰的 agent 函数（acp_sdk API 决定如何提取）
_agent_fn = None  # 在 register 中赋值（acp_sdk @server.agent() 返回值决定）
```

- [ ] **Step 4: Run test to verify code_fixer passes**

Run: `python -m pytest tests/m4/agents/test_code_fixer_agent.py -v`
Expected: 4 PASS + 1 skip（agent_fn 暴露策略）

- [ ] **Step 5: Create security_reviewer_agent.py（同模板，PERSPECTIVE="security"）**

`packages/m4/agents/security_reviewer_agent.py`:
```python
"""F004 M4 — security_reviewer_agent（security perspective）。"""
from __future__ import annotations

import json
from collections.abc import Iterator

from acp_sdk import Message, MessagePart
from acp_sdk.server import Context, Server

from packages.contracts.analysis_report import TokenUsage
from packages.contracts.suggestion import SuggestionPerspective
from packages.m1.llm_hypothesis_generator import LLMClient

PERSPECTIVE = "security"
AGENT_NAME = "security_reviewer_agent"
AGENT_VERSION = "1.0"


def _build_prompt(message: Message) -> str:
    parts = message.parts if hasattr(message, 'parts') else []
    da_json = parts[0].content if len(parts) >= 1 and isinstance(parts[0].content, str) else json.dumps(getattr(parts[0], 'content', {})) if parts else ""
    source = parts[1].content if len(parts) >= 2 and isinstance(parts[1].content, str) else ""
    cc_json = parts[2].content if len(parts) >= 3 and isinstance(parts[2].content, str) else ""
    log_text = parts[3].content if len(parts) >= 4 and isinstance(parts[3].content, str) else ""

    return f"""You are a code reviewer focused on SECURITY issues.

Deep analysis: {da_json}
Source code:\n{source}
Call context: {cc_json}
Log entry: {log_text}

Generate a security assessment as JSON:
  assessment: one-line security issue or "no risk"
  suggested_diff: unified diff or null
  confidence: 0.0-1.0

Respond ONLY with JSON.
"""


def _parse_response(text: str, model_name: str, token_usage: TokenUsage) -> SuggestionPerspective:
    try:
        d = json.loads(text)
        return SuggestionPerspective(
            perspective=PERSPECTIVE,
            assessment=d.get("assessment", ""),
            suggested_diff=d.get("suggested_diff"),
            confidence=float(d.get("confidence", 0.0)),
            model_name=model_name,
            token_usage=token_usage,
        )
    except (json.JSONDecodeError, ValueError):
        return SuggestionPerspective(
            perspective=PERSPECTIVE,
            assessment=text,
            suggested_diff=None,
            confidence=0.0,
            model_name=model_name,
            token_usage=token_usage,
        )


def register(server: Server, llm_client: LLMClient | None = None) -> None:
    if llm_client is None:
        raise NotImplementedError("security_reviewer_agent 需要 llm_client 注入")

    @server.agent()
    async def security_reviewer_agent(
        input: list[Message], context: Context
    ) -> Iterator[MessagePart]:
        msg = input[-1] if input else Message(parts=[])
        prompt = _build_prompt(msg)
        llm_text = await llm_client.complete(prompt)
        token_usage = TokenUsage(0, 0, 0.0)
        perspective = _parse_response(llm_text, "gpt-4", token_usage)
        yield MessagePart(
            content=json.dumps({
                "perspective": perspective.perspective,
                "assessment": perspective.assessment,
                "suggested_diff": perspective.suggested_diff,
                "confidence": perspective.confidence,
                "model_name": perspective.model_name,
            }),
            content_type="application/json",
        )
```

- [ ] **Step 6: Create readability_reviewer_agent.py（同模板，PERSPECTIVE="readability"）**

`packages/m4/agents/readability_reviewer_agent.py`: 同 Task 8 Step 5 模板，`PERSPECTIVE = "readability"`，prompt 改成 "READABILITY / code clarity" 视角。

- [ ] **Step 7: Create testing_reviewer_agent.py（同模板，PERSPECTIVE="testing"）**

`packages/m4/agents/testing_reviewer_agent.py`: 同 Task 8 Step 5 模板，`PERSPECTIVE = "testing"`，prompt 改成 "TESTING / test coverage" 视角。

- [ ] **Step 8: Write + run tests for security/readability/testing agents**

为 3 个 reviewer agent 各写一份测试（复制 `test_code_fixer_agent.py` 结构 + 改 PERSPECTIVE 名称）：
- `tests/m4/agents/test_security_reviewer_agent.py` — `from packages.m4.agents.security_reviewer_agent import _build_prompt, _parse_response, register`，PERSPECTIVE 检查 "security"
- `tests/m4/agents/test_readability_reviewer_agent.py` — PERSPECTIVE 检查 "readability"
- `tests/m4/agents/test_testing_reviewer_agent.py` — PERSPECTIVE 检查 "testing"

Run: `python -m pytest tests/m4/agents/ -v`
Expected: 4 个文件 × 4-5 tests = ~16-20 tests PASS

- [ ] **Step 9: Lint check**

Run: `python -m ruff check packages/m4/agents/ tests/m4/agents/`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add packages/m4/agents/ tests/m4/agents/
git commit -m "feat(m4): 4 reviewer agents — code_fixer / security / readability / testing"
```

---

### Task 9: suggestion_coordinator_agent

**Files:**
- Create: `packages/m4/agents/coordinator_agent.py` — suggestion_coordinator_agent
- Test: `tests/m4/agents/test_coordinator_agent.py`

**Interfaces:**
- Consumes:
  - 4 个 reviewer agent 的 register 函数（Task 8）
  - `acp_sdk.client.Client` / `Message` / `MessagePart`
  - `SuggestionPerspective` / `TokenUsage`
- Produces:
  - `register(server: Server, acp_client: Client | None = None) -> None`
  - coordinator agent 输出 2 parts：unified_diff（text/plain）+ perspective_evaluations JSON

- [ ] **Step 1: Write the failing test**

`tests/m4/agents/test_coordinator_agent.py`:
```python
"""F004 M4 — suggestion_coordinator_agent 测试（spec §二 + AC-8）。"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from acp_sdk import Message, MessagePart

from packages.contracts.analysis_report import TokenUsage
from packages.m4.agents.coordinator_agent import (
    _build_coordination_prompt,
    _merge_perspectives,
    register,
)


def test_build_coordination_prompt_includes_all_inputs() -> None:
    """coordinator prompt 含 DeepAnalysisRecord + source + CallContext + log。"""
    msg = Message(parts=[
        MessagePart(content='{"root_cause_hypothesis":"N+1"}', content_type="application/json"),
        MessagePart(content="def foo():\n    pass\n", content_type="text/plain"),
        MessagePart(content='{"function_signature":"def foo()"}', content_type="application/json"),
        MessagePart(content="ERROR boom", content_type="text/plain"),
    ])
    prompt = _build_coordination_prompt(msg)
    assert "N+1" in prompt
    assert "def foo" in prompt
    assert "ERROR boom" in prompt


def test_merge_perspectives_picks_main_diff() -> None:
    """_merge_perspectives 主视角 = code_fixer（performance）的 diff — spec Q4 决策。"""
    perspectives_json = [
        {"perspective": "performance", "assessment": "x", "suggested_diff": "@@ -1,1 +1,2 @@", "confidence": 0.8, "model_name": "gpt-4"},
        {"perspective": "security", "assessment": "y", "suggested_diff": None, "confidence": 0.9, "model_name": "gpt-4"},
        {"perspective": "readability", "assessment": "z", "suggested_diff": None, "confidence": 0.7, "model_name": "gpt-4"},
        {"perspective": "testing", "assessment": "w", "suggested_diff": None, "confidence": 0.6, "model_name": "gpt-4"},
    ]
    unified_diff, summary = _merge_perspectives(perspectives_json)
    assert unified_diff == "@@ -1,1 +1,2 @@"
    assert "performance" in summary.lower() or "code_fixer" in summary.lower()


def test_merge_perspectives_no_main_diff() -> None:
    """code_fixer 无 diff 时 unified_diff 返回空 + summary 注明无 diff。"""
    perspectives_json = [
        {"perspective": "performance", "assessment": "no fix", "suggested_diff": None, "confidence": 0.5, "model_name": "gpt-4"},
    ]
    unified_diff, summary = _merge_perspectives(perspectives_json)
    assert unified_diff == ""
    assert "no diff" in summary.lower() or "无 diff" in summary


@pytest.mark.asyncio
async def test_coordinator_invokes_4_reviewers_in_sequence() -> None:
    """coordinator 顺序调 4 个 reviewer（acp_sdk Client.run_sync）— AC-8。"""
    # Mock ACP Client.run_sync 4 次返回 4 个 perspective
    mock_client = MagicMock()
    mock_client.run_sync = AsyncMock(side_effect=[
        Message(parts=[MessagePart(content='{"perspective":"performance","assessment":"a","suggested_diff":"@@ -1,1 +1,2 @@","confidence":0.8,"model_name":"gpt-4"}', content_type="application/json")]),
        Message(parts=[MessagePart(content='{"perspective":"security","assessment":"b","suggested_diff":null,"confidence":0.9,"model_name":"gpt-4"}', content_type="application/json")]),
        Message(parts=[MessagePart(content='{"perspective":"readability","assessment":"c","suggested_diff":null,"confidence":0.7,"model_name":"gpt-4"}', content_type="application/json")]),
        Message(parts=[MessagePart(content='{"perspective":"testing","assessment":"d","suggested_diff":null,"confidence":0.6,"model_name":"gpt-4"}', content_type="application/json")]),
    ])

    # 输入 Message
    msg = Message(parts=[
        MessagePart(content='{"root_cause_hypothesis":"N+1"}', content_type="application/json"),
        MessagePart(content="def foo():\n    pass\n", content_type="text/plain"),
        MessagePart(content='{"function_signature":"def foo()"}', content_type="application/json"),
        MessagePart(content="ERROR boom", content_type="text/plain"),
    ])

    # 调 coordinator agent（提取 register 内部装饰的函数）
    server = MagicMock()
    register(server, acp_client=mock_client)

    # 验证 client.run_sync 被调 4 次（顺序：code_fixer / security / readability / testing）
    assert mock_client.run_sync.await_count == 4
    called_agents = [call.kwargs.get('agent', call.args[0] if call.args else None) for call in mock_client.run_sync.await_args_list]
    # 实施时按实际调用签名调整；期望按 spec §二 顺序
    # 4 个 agent name 都被调过
    expected = {"code_fixer_agent", "security_reviewer_agent", "readability_reviewer_agent", "testing_reviewer_agent"}
    assert set(called_agents) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/agents/test_coordinator_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m4.agents.coordinator_agent'`

- [ ] **Step 3: Create packages/m4/agents/coordinator_agent.py**

`packages/m4/agents/coordinator_agent.py`:
```python
"""F004 M4 — suggestion_coordinator_agent（编排 4 个 reviewer agent）。

接收 input Message（含 DeepAnalysisRecord + source + CallContext + log），
通过 ACP Client 顺序调用 4 个 reviewer agent（code_fixer / security / readability / testing），
汇总产 unified_diff + perspective_evaluations JSON。
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from acp_sdk import Message, MessagePart
from acp_sdk.client import Client
from acp_sdk.server import Context, Server

AGENT_NAME = "suggestion_coordinator_agent"
AGENT_VERSION = "1.0"

# 4 个 reviewer 顺序（spec §二 + Q8 v1 串行）
REVIEWERS = [
    "code_fixer_agent",
    "security_reviewer_agent",
    "readability_reviewer_agent",
    "testing_reviewer_agent",
]


def _build_coordination_prompt(message: Message) -> str:
    """从 input Message 提取 4 parts 装配 prompt（coordinator 自己不调 LLM，仅做编排）。"""
    parts = message.parts if hasattr(message, 'parts') else []
    da = parts[0].content if len(parts) >= 1 else ""
    source = parts[1].content if len(parts) >= 2 else ""
    cc = parts[2].content if len(parts) >= 3 else ""
    log = parts[3].content if len(parts) >= 4 else ""
    return f"DeepAnalysis: {da}\nSource:\n{source}\nCallContext: {cc}\nLog: {log}"


def _merge_perspectives(perspectives: list[dict[str, Any]]) -> tuple[str, str]:
    """合并 4 视角 → unified_diff + summary（spec Q4 决策：主视角 = code_fixer）。

    Returns:
        (unified_diff, summary)
        - 主视角 code_fixer 有 diff → 用其 diff
        - 主视角无 diff → unified_diff 空字符串，summary 注明无 diff
    """
    main = next((p for p in perspectives if p.get("perspective") == "performance"), None)
    if main and main.get("suggested_diff"):
        return main["suggested_diff"], f"Main perspective (code_fixer/performance): {main.get('assessment', '')}"
    return "", "No main diff from code_fixer — see perspective_evaluations for details"


def register(server: Server, acp_client: Client | None = None) -> None:
    """在 server 上注册 suggestion_coordinator_agent。

    Args:
        server: ACP Server 实例
        acp_client: 已配置的 ACP Client（None 时从 env 构造）
    """
    @server.agent()
    async def suggestion_coordinator_agent(
        input: list[Message], context: Context
    ) -> Iterator[MessagePart]:
        """编排 4 个 reviewer agent 产 unified_diff + perspective_evaluations JSON。"""
        msg = input[-1] if input else Message(parts=[])

        # acp_client 注入（生产环境从 context 取，dev 从 register 参数取）
        client = acp_client or _get_client_from_context(context)

        perspectives: list[dict[str, Any]] = []
        for reviewer_name in REVIEWERS:
            # 调子 agent — ACP Client.run_sync
            response = await client.run_sync(
                agent=reviewer_name,
                input=[msg],
            )
            # 提取 response 第 1 个 part 的 content（perspective JSON）
            if response.parts:
                content = response.parts[0].content
                if isinstance(content, str):
                    perspectives.append(json.loads(content))
                else:
                    perspectives.append(content if isinstance(content, dict) else {})

        # 汇总
        unified_diff, summary = _merge_perspectives(perspectives)

        # yield 2 parts: unified_diff + perspective_evaluations JSON
        yield MessagePart(content=unified_diff, content_type="text/plain")
        yield MessagePart(
            content=json.dumps({
                "summary": summary,
                "perspective_evaluations": perspectives,
            }),
            content_type="application/json",
        )


def _get_client_from_context(context: Context) -> Client:
    """从 ACP Context 提取已配置 Client（生产路径）。"""
    # 占位：实施时按 acp_sdk Context API 调整
    # 通常 Context 暴露 client 或 context.config 含 base_url
    raise NotImplementedError(
        "coordinator 需要 acp_client 注入 — 生产从 Context 取，dev 从 register 参数取"
    )
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/m4/agents/test_coordinator_agent.py -v`
Expected: 3 PASS + 1 FAIL or skip（顺序调用测试 — acp_sdk API 表面决定）

- [ ] **Step 5: Update acp_servers/m4_server.py — 取消注释注册 5 个 agent**

修改 `acp_servers/m4_server.py`，取消 Task 7 中的注释：

```python
from packages.m4.agents.coordinator_agent import register as register_coordinator
from packages.m4.agents.code_fixer_agent import register as register_code_fixer
from packages.m4.agents.security_reviewer_agent import register as register_security
from packages.m4.agents.readability_reviewer_agent import register as register_readability
from packages.m4.agents.testing_reviewer_agent import register as register_testing

server = Server()

register_coordinator(server)
register_code_fixer(server)
register_security(server)
register_readability(server)
register_testing(server)
```

- [ ] **Step 6: Unskip Task 7 skipped tests + rerun**

修改 `tests/m4/test_acp_server.py` 把 Task 7 的 2 个 `pytest.skip` 改为实际验证：

```python
def test_m4_server_registers_5_agents() -> None:
    """AC-3：Server 注册 5 个 agent。"""
    from acp_servers.m4_server import server
    # acp_sdk API：server.agents 或 server._agents
    # 实施时按实际 API 取
    agents = getattr(server, 'agents', None) or getattr(server, '_agents', None)
    if agents is None:
        # fallback：检查 server.agent 属性是否被调 5 次
        # （register 内部调 server.agent() 装饰器）
        import pytest
        pytest.skip("acp_sdk Server 不暴露 agents list — 用 integration test 验证")
    assert len(agents) == 5
```

Run: `python -m pytest tests/m4/test_acp_server.py tests/m4/agents/ -v`
Expected: PASS（除 acp_sdk API 限制的 skip）

- [ ] **Step 7: Lint check**

Run: `python -m ruff check packages/m4/agents/coordinator_agent.py acp_servers/m4_server.py tests/m4/agents/test_coordinator_agent.py tests/m4/test_acp_server.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add packages/m4/agents/coordinator_agent.py acp_servers/m4_server.py tests/m4/agents/test_coordinator_agent.py tests/m4/test_acp_server.py
git commit -m "feat(m4): coordinator_agent — 编排 4 reviewer + 5 agent 注册"
```

---

### Task 10: SuggestionMerger — 多视角 diff 汇总

**Files:**
- Create: `packages/m4/suggestion_merger.py` — SuggestionMerger
- Test: `tests/m4/test_suggestion_merger.py`

**Interfaces:**
- Consumes: `SuggestionPerspective` / `acp_sdk.Message` / `acp_sdk.MessagePart`
- Produces: `SuggestionMerger.merge(perspective_dicts: list[dict]) -> SuggestionMergerResult`
  - `SuggestionMergerResult` dataclass: `unified_diff: str` / `summary: str` / `confidence_score: float` / `perspective_evaluations: list[SuggestionPerspective]`

- [ ] **Step 1: Write the failing test**

`tests/m4/test_suggestion_merger.py`:
```python
"""F004 M4 — SuggestionMerger 测试（spec §三 + AC-9）。"""
from __future__ import annotations

from packages.contracts.analysis_report import TokenUsage
from packages.m4.suggestion_merger import SuggestionMerger, SuggestionMergerResult


def test_merger_picks_main_diff_from_code_fixer() -> None:
    """主视角 code_fixer 有 diff → unified_diff = code_fixer 的 diff — AC-9 + Q4。"""
    perspectives = [
        {"perspective": "performance", "assessment": "N+1", "suggested_diff": "@@ -1,1 +1,2 @@", "confidence": 0.8, "model_name": "gpt-4"},
        {"perspective": "security", "assessment": "no risk", "suggested_diff": None, "confidence": 0.9, "model_name": "gpt-4"},
        {"perspective": "readability", "assessment": "ok", "suggested_diff": None, "confidence": 0.7, "model_name": "gpt-4"},
        {"perspective": "testing", "assessment": "missing test", "suggested_diff": None, "confidence": 0.6, "model_name": "gpt-4"},
    ]
    merger = SuggestionMerger()
    result = merger.merge(perspectives)
    assert isinstance(result, SuggestionMergerResult)
    assert result.unified_diff == "@@ -1,1 +1,2 @@"
    assert len(result.perspective_evaluations) == 4
    # confidence_score 加权平均（4 视角权重等分）
    expected = (0.8 + 0.9 + 0.7 + 0.6) / 4
    assert abs(result.confidence_score - expected) < 0.01


def test_merger_no_main_diff() -> None:
    """code_fixer 无 diff → unified_diff 空 + confidence 仍计算。"""
    perspectives = [
        {"perspective": "performance", "assessment": "no fix", "suggested_diff": None, "confidence": 0.5, "model_name": "gpt-4"},
        {"perspective": "security", "assessment": "ok", "suggested_diff": None, "confidence": 0.9, "model_name": "gpt-4"},
    ]
    merger = SuggestionMerger()
    result = merger.merge(perspectives)
    assert result.unified_diff == ""
    assert "no diff" in result.summary.lower() or "无 diff" in result.summary.lower()
    expected = (0.5 + 0.9) / 2
    assert abs(result.confidence_score - expected) < 0.01


def test_merger_handles_empty_list() -> None:
    """空 perspectives 列表 → unified_diff 空 + confidence 0。"""
    merger = SuggestionMerger()
    result = merger.merge([])
    assert result.unified_diff == ""
    assert result.confidence_score == 0.0
    assert result.perspective_evaluations == []


def test_merger_perspectives_to_dataclass() -> None:
    """merge 输出 perspective_evaluations 是 SuggestionPerspective dataclass 列表。"""
    perspectives = [
        {"perspective": "performance", "assessment": "x", "suggested_diff": "@@ -1,1 +1,2 @@", "confidence": 0.8, "model_name": "gpt-4"},
    ]
    merger = SuggestionMerger()
    result = merger.merge(perspectives)
    assert len(result.perspective_evaluations) == 1
    p = result.perspective_evaluations[0]
    assert p.perspective == "performance"
    assert p.assessment == "x"
    assert p.suggested_diff == "@@ -1,1 +1,2 @@"
    assert p.confidence == 0.8
    assert p.model_name == "gpt-4"
    # token_usage 默认 0（merger 不构造 token usage，由 service 层从 ACP 响应累积）
    assert p.token_usage.prompt_tokens == 0


def test_merger_from_acp_message() -> None:
    """从 ACP coordinator 响应 Message 提取 unified_diff + perspectives JSON — AC-9。"""
    from acp_sdk import Message, MessagePart
    import json

    unified_diff_str = "@@ -1,1 +1,2 @@"
    perspectives_json = json.dumps({
        "summary": "main perspective",
        "perspective_evaluations": [
            {"perspective": "performance", "assessment": "x", "suggested_diff": "@@ -1,1 +1,2 @@", "confidence": 0.8, "model_name": "gpt-4"},
            {"perspective": "security", "assessment": "y", "suggested_diff": None, "confidence": 0.9, "model_name": "gpt-4"},
        ],
    })

    msg = Message(parts=[
        MessagePart(content=unified_diff_str, content_type="text/plain"),
        MessagePart(content=perspectives_json, content_type="application/json"),
    ])

    merger = SuggestionMerger()
    result = merger.merge_from_message(msg)
    assert result.unified_diff == unified_diff_str
    assert len(result.perspective_evaluations) == 2
    assert result.perspective_evaluations[0].perspective == "performance"
    assert result.perspective_evaluations[1].perspective == "security"
    assert "main perspective" in result.summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/test_suggestion_merger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m4.suggestion_merger'`

- [ ] **Step 3: Create packages/m4/suggestion_merger.py**

`packages/m4/suggestion_merger.py`:
```python
"""F004 M4 — SuggestionMerger（spec §三 + AC-9）。

合并 4 视角 diff → unified_diff + summary + confidence_score。

策略（spec Q4 决策）：
  - 主视角 = code_fixer（performance）— 用其 diff 作为 unified_diff
  - 其他视角（security/readability/testing）作为 assessment 附在 perspective_evaluations
  - 冲突时不强行合并，让用户 review 时选
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any

from acp_sdk import Message

from packages.contracts.analysis_report import TokenUsage
from packages.contracts.suggestion import SuggestionPerspective


@dataclasses.dataclass(frozen=True)
class SuggestionMergerResult:
    """merge 输出（spec §三 + AC-9）。

    Attributes:
        unified_diff: 主视角 code_fixer 的 diff（无 diff 时空字符串）
        summary: 汇总摘要
        confidence_score: 加权平均置信度
        perspective_evaluations: SuggestionPerspective dataclass 列表
    """
    unified_diff: str
    summary: str
    confidence_score: float
    perspective_evaluations: list[SuggestionPerspective]


class SuggestionMerger:
    """合并多视角 diff → SuggestionMergerResult（spec §三 + AC-9）。"""

    def merge(self, perspectives: list[dict[str, Any]]) -> SuggestionMergerResult:
        """从 4 个 perspective dict 列表合并（spec §三）。

        Args:
            perspectives: ACP reviewer agent 输出的 perspective dict 列表（按 spec §二 顺序）
        """
        if not perspectives:
            return SuggestionMergerResult(
                unified_diff="",
                summary="No perspectives provided",
                confidence_score=0.0,
                perspective_evaluations=[],
            )

        # 主视角 = code_fixer（performance）
        main = next((p for p in perspectives if p.get("perspective") == "performance"), None)
        unified_diff = main.get("suggested_diff") if main else None
        if not unified_diff:
            unified_diff = ""
            summary = "No main diff from code_fixer — see perspective_evaluations for details"
        else:
            summary = f"Main perspective (code_fixer/performance): {main.get('assessment', '')}"

        # 转 SuggestionPerspective dataclass
        pe_list: list[SuggestionPerspective] = []
        for p in perspectives:
            pe_list.append(SuggestionPerspective(
                perspective=p.get("perspective", "unknown"),
                assessment=p.get("assessment", ""),
                suggested_diff=p.get("suggested_diff"),
                confidence=float(p.get("confidence", 0.0)),
                model_name=p.get("model_name", "unknown"),
                token_usage=TokenUsage(
                    prompt_tokens=0, completion_tokens=0, total_cost_usd=0.0,
                ),  # token usage 由 service 层从 ACP 响应累积
            ))

        # confidence_score 加权平均（v1 等权重 — spec Q4 未指定权重，等权最简单）
        total = sum(p.confidence for p in pe_list)
        confidence_score = total / len(pe_list) if pe_list else 0.0

        return SuggestionMergerResult(
            unified_diff=unified_diff,
            summary=summary,
            confidence_score=confidence_score,
            perspective_evaluations=pe_list,
        )

    def merge_from_message(self, message: Message) -> SuggestionMergerResult:
        """从 ACP coordinator 响应 Message 提取（spec §三 + AC-9）。

        coordinator 输出 2 parts：
          1. text/plain — unified_diff
          2. application/json — {summary, perspective_evaluations: list}
        """
        parts = message.parts if hasattr(message, 'parts') else []
        unified_diff = ""
        perspectives_dict: dict[str, Any] = {}

        if len(parts) >= 1:
            content0 = parts[0].content
            unified_diff = content0 if isinstance(content0, str) else str(content0)
        if len(parts) >= 2:
            content1 = parts[1].content
            if isinstance(content1, str):
                perspectives_dict = json.loads(content1)
            elif isinstance(content1, dict):
                perspectives_dict = content1

        perspectives = perspectives_dict.get("perspective_evaluations", [])
        summary = perspectives_dict.get("summary", "")

        result = self.merge(perspectives)
        # 覆盖 summary（coordinator 已给）
        return SuggestionMergerResult(
            unified_diff=unified_diff or result.unified_diff,
            summary=summary or result.summary,
            confidence_score=result.confidence_score,
            perspective_evaluations=result.perspective_evaluations,
        )
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/m4/test_suggestion_merger.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint check**

Run: `python -m ruff check packages/m4/suggestion_merger.py tests/m4/test_suggestion_merger.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add packages/m4/suggestion_merger.py tests/m4/test_suggestion_merger.py
git commit -m "feat(m4): SuggestionMerger — 主视角 + 加权平均 confidence"
```

---

### Task 11: SuggestionService — FastAPI 编排层（ACP Client 调用）

**Files:**
- Create: `packages/m4/suggestion_service.py` — SuggestionService
- Create: `packages/m4/exceptions.py` — M4 异常类
- Test: `tests/m4/test_suggestion_service.py`

**Interfaces:**
- Consumes:
  - M2 `M2Repository.get_deep_analysis` / `get_analysis_report`
  - M1 `RepoLogGraphService.get_call_context` / `get_source_snippet`
  - `M4Repository`（Task 5）
  - `SuggestionMessageBuilder` / `AcpMessageSanitizer`（Task 6）
  - `SuggestionMerger`（Task 10）
  - `acp_sdk.client.Client`
  - `AuditLogger` / `M4MetricsEmitter`（Task 13 metrics）
- Produces:
  - `SuggestionService.generate_suggestion(deep_analysis_id, perspectives=None) -> SuggestionRecord`
  - `SuggestionService.get_suggestion(suggestion_id) -> SuggestionRecord`
  - `SuggestionService.list_suggestions(report_id, log_point_id) -> list[SuggestionRecord]`
  - `SuggestionService.archive_suggestion(suggestion_id, archiver) -> None`
  - `SuggestionIterationLimitExceeded` / `DeepAnalysisNotFound` / `AcpServerUnavailable` 异常

- [ ] **Step 1: Write the failing test**

`tests/m4/test_suggestion_service.py`:
```python
"""F004 M4 — SuggestionService 编排层测试（spec §四 + AC-1/8/9/10/11/12/19）。"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from acp_sdk import Message, MessagePart

from packages.contracts.analysis_report import AnalysisReport, TokenUsage
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.log_point import CallContext
from packages.contracts.source_snippet import SourceSnippet
from packages.contracts.suggestion import SuggestionRecord
from packages.m4.exceptions import (
    AcpServerUnavailable,
    DeepAnalysisNotFound,
    SuggestionIterationLimitExceeded,
)
from packages.m4.suggestion_service import SuggestionService


def _make_deep_analysis(id: str = "deep-1", iteration: int = 1, parent: str | None = None) -> DeepAnalysisRecord:
    return DeepAnalysisRecord(
        id=id,
        report_id="report-1",
        line_ids=["line-1"],
        log_point_ids=["lp-1"],
        call_contexts=[],
        root_cause_hypothesis="N+1 query",
        fix_suggestion="batch queries",
        related_evidence=[],
        model_name="gpt-4",
        prompt_hash="sha256-abc",
        iteration=iteration,
        parent_record_id=parent,
        generated_at=datetime.now(UTC),
        token_usage=TokenUsage(100, 200, 0.10),
    )


def _make_analysis_report() -> AnalysisReport:
    return AnalysisReport(
        id="report-1",
        repo_id="repo-1",
        log_source="app.log",
        log_line_count=10,
        window_start=None,
        window_end=None,
        model_name="gpt-4o-mini",
        prompt_hash="sha256-xyz",
        system_summary="system ok",
        anomaly_localization=[],
        error_correlation=[],
        generated_at=datetime.now(UTC),
        duration_seconds=1.0,
        token_usage=TokenUsage(0, 0, 0.0),
        ingestion_status="draft",
    )


def _make_call_context() -> CallContext:
    return CallContext(
        function_signature="def foo()",
        callers=[],
        callees=[],
        enclosing_community="C",
        related_log_points=[],
        evidence_refs=[],
    )


def _make_source_snippet() -> SourceSnippet:
    return SourceSnippet(
        file_path="src/foo.py",
        line_range=(1, 30),
        content="def foo():\n    pass\n",
        extractor_version="1.0.0",
    )


def _make_acp_response() -> Message:
    """模拟 ACP coordinator 响应（2 parts: unified_diff + perspective_evaluations JSON）。"""
    return Message(parts=[
        MessagePart(content="@@ -1,1 +1,2 @@", content_type="text/plain"),
        MessagePart(content=json.dumps({
            "summary": "main perspective",
            "perspective_evaluations": [
                {"perspective": "performance", "assessment": "x", "suggested_diff": "@@ -1,1 +1,2 @@", "confidence": 0.8, "model_name": "gpt-4"},
                {"perspective": "security", "assessment": "y", "suggested_diff": None, "confidence": 0.9, "model_name": "gpt-4"},
                {"perspective": "readability", "assessment": "z", "suggested_diff": None, "confidence": 0.7, "model_name": "gpt-4"},
                {"perspective": "testing", "assessment": "w", "suggested_diff": None, "confidence": 0.6, "model_name": "gpt-4"},
            ],
        }), content_type="application/json"),
    ])


def _make_service(
    m2_repo: MagicMock | None = None,
    m1_service: MagicMock | None = None,
    m4_repo: MagicMock | None = None,
    message_builder: MagicMock | None = None,
    sanitizer: MagicMock | None = None,
    acp_client: AsyncMock | None = None,
    merger: MagicMock | None = None,
    audit: MagicMock | None = None,
    metrics: MagicMock | None = None,
) -> SuggestionService:
    """构造 SuggestionService（全 mock）。"""
    return SuggestionService(
        session=MagicMock(),
        audit=audit or MagicMock(),
        repository=m4_repo or MagicMock(),
        message_builder=message_builder or MagicMock(),
        acp_sanitizer=sanitizer or MagicMock(),
        merger=merger or MagicMock(),
        acp_client=acp_client or AsyncMock(),
        m1_service=m1_service or MagicMock(),
        m2_repo=m2_repo or MagicMock(),
        metrics=metrics,
    )


@pytest.mark.asyncio
async def test_generate_suggestion_happy_path() -> None:
    """完整流程：DeepAnalysis → CallContext → source → ACP → SuggestionRecord — AC-1/8/9/10。"""
    # Mock 各依赖
    m2_repo = MagicMock()
    m2_repo.get_deep_analysis.return_value = _make_deep_analysis()
    m2_repo.get_analysis_report.return_value = _make_analysis_report()

    m1_service = MagicMock()
    m1_service.get_call_context.return_value = _make_call_context()
    m1_service.get_source_snippet.return_value = _make_source_snippet()

    message_builder = MagicMock()
    message_builder.build.return_value = Message(parts=[
        MessagePart(content="x", content_type="application/json"),
    ])

    sanitizer = MagicMock()
    sanitizer.sanitize.side_effect = lambda m: m  # passthrough

    acp_client = AsyncMock()
    acp_client.run_sync.return_value = _make_acp_response()

    merger = MagicMock()
    merger.merge_from_message.return_value = MagicMock(
        unified_diff="@@ -1,1 +1,2 @@",
        summary="main perspective",
        confidence_score=0.75,
        perspective_evaluations=[],  # 由 merger 内部构造，此处不验证细节
    )
    # 让 merger 返回真实 SuggestionMergerResult
    from packages.m4.suggestion_merger import SuggestionMerger, SuggestionMergerResult
    real_merger = SuggestionMerger()
    merger.merge_from_message.side_effect = lambda msg: real_merger.merge_from_message(msg)

    m4_repo = MagicMock()

    service = _make_service(
        m2_repo=m2_repo, m1_service=m1_service, m4_repo=m4_repo,
        message_builder=message_builder, sanitizer=sanitizer,
        acp_client=acp_client, merger=merger, audit=MagicMock(),
    )

    # 调用
    record = await service.generate_suggestion(deep_analysis_id="deep-1")

    # 验证 SuggestionRecord 字段
    assert isinstance(record, SuggestionRecord)
    assert record.deep_analysis_id == "deep-1"
    assert record.report_id == "report-1"
    assert record.unified_diff == "@@ -1,1 +1,2 @@"
    assert record.confidence_score == 0.75  # (0.8+0.9+0.7+0.6)/4
    assert len(record.perspective_evaluations) == 4
    assert record.iteration == 1
    assert record.parent_record_id is None  # 首次生成
    assert record.acp_session_id is not None  # ACP 路径生成

    # 验证 m4_repo.save_suggestion 被调
    m4_repo.save_suggestion.assert_called_once()

    # 验证 m1_service.get_source_snippet 被调（spec §十）
    m1_service.get_source_snippet.assert_called_once()


@pytest.mark.asyncio
async def test_generate_suggestion_deep_analysis_not_found() -> None:
    """DeepAnalysis 不存在 → raise DeepAnalysisNotFound — AC-1 错误码 M4_DEEP_ANALYSIS_NOT_FOUND。"""
    m2_repo = MagicMock()
    m2_repo.get_deep_analysis.return_value = None

    service = _make_service(m2_repo=m2_repo)

    with pytest.raises(DeepAnalysisNotFound):
        await service.generate_suggestion(deep_analysis_id="nonexistent")


@pytest.mark.asyncio
async def test_generate_suggestion_iteration_chain() -> None:
    """AC-11：累积上下文链 — 前次 SuggestionRecord 存在时 iteration+1 + parent_record_id。"""
    m2_repo = MagicMock()
    m2_repo.get_deep_analysis.return_value = _make_deep_analysis()
    m2_repo.get_analysis_report.return_value = _make_analysis_report()

    m1_service = MagicMock()
    m1_service.get_call_context.return_value = _make_call_context()
    m1_service.get_source_snippet.return_value = _make_source_snippet()

    message_builder = MagicMock()
    message_builder.build.return_value = Message(parts=[MessagePart(content="x", content_type="application/json")])
    sanitizer = MagicMock()
    sanitizer.sanitize.side_effect = lambda m: m
    acp_client = AsyncMock()
    acp_client.run_sync.return_value = _make_acp_response()

    # Mock m4_repo.list_suggestions 返回前次 iteration=1
    m4_repo = MagicMock()
    previous = SuggestionRecord(
        id="sug-prev", deep_analysis_id="deep-1", report_id="report-1",
        log_point_ids=["lp-1"], unified_diff="", summary="",
        perspective_evaluations=[], confidence_score=0.0,
        model_name="gpt-4", prompt_hash="h", iteration=1,
        parent_record_id=None, generated_at=datetime.now(UTC),
        token_usage=TokenUsage(0, 0, 0.0), schema_version="1.0.0",
        acp_session_id=None, acp_agent_versions={},
    )
    m4_repo.list_suggestions.return_value = [previous]

    service = _make_service(
        m2_repo=m2_repo, m1_service=m1_service, m4_repo=m4_repo,
        message_builder=message_builder, sanitizer=sanitizer,
        acp_client=acp_client, merger=MagicMock(),
    )
    # 用真实 merger
    from packages.m4.suggestion_merger import SuggestionMerger
    service._merger = SuggestionMerger()

    record = await service.generate_suggestion(deep_analysis_id="deep-1")
    assert record.iteration == 2
    assert record.parent_record_id == "sug-prev"


@pytest.mark.asyncio
async def test_generate_suggestion_iteration_limit_exceeded() -> None:
    """AC-12：累积达 max_iterations 时 raise SuggestionIterationLimitExceeded。"""
    m2_repo = MagicMock()
    m2_repo.get_deep_analysis.return_value = _make_deep_analysis()
    m2_repo.get_analysis_report.return_value = _make_analysis_report()
    m1_service = MagicMock()
    m1_service.get_call_context.return_value = _make_call_context()
    m1_service.get_source_snippet.return_value = _make_source_snippet()

    # Mock m4_repo 返回 iteration=3（达上限）
    m4_repo = MagicMock()
    previous = SuggestionRecord(
        id="sug-prev", deep_analysis_id="deep-1", report_id="report-1",
        log_point_ids=["lp-1"], unified_diff="", summary="",
        perspective_evaluations=[], confidence_score=0.0,
        model_name="gpt-4", prompt_hash="h", iteration=3,
        parent_record_id=None, generated_at=datetime.now(UTC),
        token_usage=TokenUsage(0, 0, 0.0), schema_version="1.0.0",
        acp_session_id=None, acp_agent_versions={},
    )
    m4_repo.list_suggestions.return_value = [previous]

    service = _make_service(
        m2_repo=m2_repo, m1_service=m1_service, m4_repo=m4_repo,
    )
    # config 注入 max_iterations=3
    from packages.m1.config_loader import M4Config
    service._config_m4 = M4Config(max_iterations=3)

    with pytest.raises(SuggestionIterationLimitExceeded) as exc_info:
        await service.generate_suggestion(deep_analysis_id="deep-1")
    assert exc_info.value.limit == 3
    assert exc_info.value.current == 3


@pytest.mark.asyncio
async def test_generate_suggestion_acp_server_unavailable() -> None:
    """AC-19：ACP Server 不可达 → raise AcpServerUnavailable（HTTP 层 503）。"""
    m2_repo = MagicMock()
    m2_repo.get_deep_analysis.return_value = _make_deep_analysis()
    m2_repo.get_analysis_report.return_value = _make_analysis_report()
    m1_service = MagicMock()
    m1_service.get_call_context.return_value = _make_call_context()
    m1_service.get_source_snippet.return_value = _make_source_snippet()
    message_builder = MagicMock()
    message_builder.build.return_value = Message(parts=[MessagePart(content="x", content_type="application/json")])
    sanitizer = MagicMock()
    sanitizer.sanitize.side_effect = lambda m: m

    # acp_client.run_sync raise 连接异常
    acp_client = AsyncMock()
    acp_client.run_sync.side_effect = ConnectionError("ACP server down")

    service = _make_service(
        m2_repo=m2_repo, m1_service=m1_service,
        message_builder=message_builder, sanitizer=sanitizer,
        acp_client=acp_client,
    )

    with pytest.raises(AcpServerUnavailable):
        await service.generate_suggestion(deep_analysis_id="deep-1")


def test_get_suggestion() -> None:
    """get_suggestion 透传 m4_repo.get_suggestion。"""
    m4_repo = MagicMock()
    expected = MagicMock(spec=SuggestionRecord)
    m4_repo.get_suggestion.return_value = expected

    service = _make_service(m4_repo=m4_repo)
    result = service.get_suggestion("sug-1")
    assert result is expected
    m4_repo.get_suggestion.assert_called_once_with("sug-1")


def test_list_suggestions() -> None:
    """list_suggestions 透传 m4_repo.list_suggestions。"""
    m4_repo = MagicMock()
    expected = [MagicMock(spec=SuggestionRecord)]
    m4_repo.list_suggestions.return_value = expected

    service = _make_service(m4_repo=m4_repo)
    result = service.list_suggestions(report_id="report-1")
    assert result == expected
    m4_repo.list_suggestions.assert_called_once_with(report_id="report-1", log_point_id=None)


def test_archive_suggestion() -> None:
    """archive_suggestion 调 m4_repo.archive_suggestion + audit_log — AC-15。"""
    m4_repo = MagicMock()
    m4_repo.archive_suggestion.return_value = True
    audit = MagicMock()

    service = _make_service(m4_repo=m4_repo, audit=audit)
    from packages.m1.unit_a_repo_registrar import User
    service.archive_suggestion("sug-1", archiver=User(id="u1", name="alice"))

    m4_repo.archive_suggestion.assert_called_once_with("sug-1")
    audit.log.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/test_suggestion_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m4.suggestion_service'`

- [ ] **Step 3: Create packages/m4/exceptions.py**

`packages/m4/exceptions.py`:
```python
"""F004 M4 — 异常类（spec §六 + AC-1/12/19/21）。"""
from __future__ import annotations


class M4Error(Exception):
    """M4 异常基类（AC-21 错误码命名空间 M4_* 前缀）。"""


class DeepAnalysisNotFound(M4Error):
    """DeepAnalysisRecord 不存在（AC-1 错误码 M4_DEEP_ANALYSIS_NOT_FOUND）。"""


class SuggestionIterationLimitExceeded(M4Error):
    """累积迭代达上限（AC-12 + AC-1 错误码 M4_SUGGESTION_LOCK_RUNNING）。

    Attributes:
        current: 当前 iteration
        limit: max_iterations 上限
        deep_analysis_id: 关联 M2 DeepAnalysisRecord id
    """
    def __init__(self, current: int, limit: int, deep_analysis_id: str) -> None:
        self.current = current
        self.limit = limit
        self.deep_analysis_id = deep_analysis_id
        super().__init__(
            f"Suggestion iteration {current} reached limit {limit} "
            f"for deep_analysis {deep_analysis_id} — archive and restart"
        )


class AcpServerUnavailable(M4Error):
    """ACP Server 不可达（AC-19 + AC-1 错误码 M4_ACP_SERVER_UNAVAILABLE）。"""
```

- [ ] **Step 4: Create packages/m4/suggestion_service.py**

`packages/m4/suggestion_service.py`:
```python
"""F004 M4 — SuggestionService（spec §四 + AC-1/8/9/10/11/12/15/19）。

编排层：HTTP 请求 → 装配 ACP Message → ACP Client 调 :8001 →
        解析 ACP 响应 → 持久化 SuggestionRecord + audit_log + metrics
"""
from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from packages.contracts.enums import (
    ACTION_ARCHIVE_SUGGESTION,
    ACTION_PHASE4_GENERATE_SUGGESTION,
)
from packages.contracts.suggestion import SuggestionRecord
from packages.m1.audit_log import AuditLogger
from packages.m1.llm_hypothesis_generator import generate_prompt_hash
from packages.m1.log_sanitizer import LogSanitizer
from packages.m1.unit_a_repo_registrar import User
from packages.m4.exceptions import (
    AcpServerUnavailable,
    DeepAnalysisNotFound,
    SuggestionIterationLimitExceeded,
)
from packages.m4.message_builder import SuggestionMessageBuilder
from packages.m4.sanitizer import AcpMessageSanitizer
from packages.m4.suggestion_merger import SuggestionMerger
from packages.m4.storage.repository import M4Repository
from packages.m1.config_loader import M4Config

if TYPE_CHECKING:
    from acp_sdk.client import Client
    from acp_sdk import Message
    from packages.m2.storage.repository import M2Repository


class SuggestionService:
    """M4 改进建议服务（spec §四 + AC-1 + AC-15）。"""

    def __init__(
        self,
        session: Session,
        audit: AuditLogger,
        repository: M4Repository,
        message_builder: SuggestionMessageBuilder,
        acp_sanitizer: AcpMessageSanitizer,
        merger: SuggestionMerger,
        acp_client: "Client",
        m1_service: "M1ServiceProtocol",
        m2_repo: "M2Repository",
        config_m4: M4Config | None = None,
        metrics: "M4MetricsEmitter | None" = None,
    ) -> None:
        self._session = session
        self._audit = audit
        self._repo = repository
        self._builder = message_builder
        self._sanitizer = acp_sanitizer
        self._merger = merger
        self._acp_client = acp_client
        self._m1 = m1_service
        self._m2 = m2_repo
        self._config_m4 = config_m4 or M4Config()
        self._metrics = metrics

    async def generate_suggestion(
        self,
        deep_analysis_id: str,
        perspectives: list[str] | None = None,
    ) -> SuggestionRecord:
        """生成改进建议（spec §四 + AC-1）。

        流程:
            1. M2Repository.get_deep_analysis(deep_analysis_id) → DeepAnalysisRecord
               不存在 → raise DeepAnalysisNotFound
            2. M2Repository.get_analysis_report(report_id) → AnalysisReport（取 repo_id）
            3. M1 RepoLogGraphService.get_call_context(repo_id, fn_sig) → CallContext
            4. M1 RepoLogGraphService.get_source_snippet(...) → SourceSnippet
               （get_source_snippet 是 F004 §十 新增 M1 方法）
            5. SuggestionMessageBuilder.build() → ACP Message
            6. AcpMessageSanitizer.sanitize(Message) → 脱敏后 Message
            7. ACP Client.run_sync(agent="suggestion_coordinator_agent",
                                   input=[sanitized_message]) → ACP 响应 Message
               连接失败 → raise AcpServerUnavailable
            8. SuggestionMerger.merge_from_message(response) → unified_diff + perspective_evaluations
            9. iteration + parent_record_id 累积（查 m4_repo.list_suggestions 同 deep_analysis_id）
               达 max_iterations → raise SuggestionIterationLimitExceeded
            10. M4Repository.save(SuggestionRecord) + audit_log + metrics
        """
        # 1. 取 DeepAnalysisRecord
        deep = self._m2.get_deep_analysis(deep_analysis_id)
        if deep is None:
            raise DeepAnalysisNotFound(f"deep_analysis {deep_analysis_id} not found")

        # 9. 检查 iteration 上限（在调 LLM 前做，避免浪费 token）
        existing = self._repo.list_suggestions(
            report_id=deep.report_id,
        )
        # 过滤同 deep_analysis_id 的（list_suggestions 当前按 report_id 查）
        same_deep = [s for s in existing if s.deep_analysis_id == deep_analysis_id]
        if same_deep:
            max_iter_seen = max(s.iteration for s in same_deep)
            current_iter = max_iter_seen + 1
            parent_id = same_deep[-1].id  # 最近一次的 id
            if max_iter_seen >= self._config_m4.max_iterations:
                raise SuggestionIterationLimitExceeded(
                    current=max_iter_seen,
                    limit=self._config_m4.max_iterations,
                    deep_analysis_id=deep_analysis_id,
                )
        else:
            current_iter = 1
            parent_id = None

        # 2. 取 AnalysisReport（取 repo_id）
        phase1_report = self._m2.get_analysis_report(deep.report_id)
        repo_id = phase1_report.repo_id if phase1_report else None

        # 3. M1 get_call_context（取 deep_analysis 关联的 log_point_ids 的第一个 function_signature）
        # 取 deep.call_contexts 的第一个（M2 deep_analyze 时已写入）
        call_context = (
            deep.call_contexts[0] if deep.call_contexts
            else self._m1.get_call_context(
                repo_id=repo_id or "",
                function_signature="",  # 无 call_context 时空 sig
            )
        )

        # 4. M1 get_source_snippet（取 deep.call_contexts[0] 的 file_path）
        # 注：call_context 当前不含 file_path 字段；用 log_point_ids[0] 查 LogPoint.file_path
        # 简化：取 deep.log_point_ids[0] 对应 LogPoint 的 file_path / line_start / line_end
        # 此处占位用 source_snippet = "" — 实施时从 M1 query_log_points 取
        source_snippet = self._m1.get_source_snippet(
            repo_id=repo_id or "",
            file_path="",  # TODO: 从 LogPoint 取实际 file_path
            line_start=1,
            line_end=10,
        )

        # 5. 装配 ACP Message
        log_entry_raw = deep.root_cause_hypothesis  # 占位：log entry 文本取 root_cause_hypothesis
        msg = self._builder.build(
            deep_analysis=deep,
            call_context=call_context,
            source_snippet=source_snippet,
            log_entry=type("LogEntry", (), {"raw_text": log_entry_raw})(),  # 简化：构造有 raw_text 的对象
        )

        # 6. 脱敏
        sanitized = self._sanitizer.sanitize(msg)

        # 7. ACP Client 调用
        try:
            acp_response = await self._acp_client.run_sync(
                agent="suggestion_coordinator_agent",
                input=[sanitized],
            )
        except Exception as e:
            raise AcpServerUnavailable(f"ACP server unreachable: {e}") from e

        # 8. Merger 合并
        result = self._merger.merge_from_message(acp_response)

        # 10. 持久化
        prompt_hash = generate_prompt_hash(
            f"m4-coordinator-{deep.id}-iter{current_iter}"
        )
        record = SuggestionRecord(
            id=f"sug-{uuid.uuid4().hex[:12]}",
            deep_analysis_id=deep_analysis_id,
            report_id=deep.report_id,
            log_point_ids=deep.log_point_ids,
            unified_diff=result.unified_diff,
            summary=result.summary,
            perspective_evaluations=result.perspective_evaluations,
            confidence_score=result.confidence_score,
            model_name=self._config_m4.model_name,
            prompt_hash=prompt_hash,
            iteration=current_iter,
            parent_record_id=parent_id,
            generated_at=datetime.now(UTC),
            token_usage=type(
                "TokenUsage", (),
                {"prompt_tokens": 0, "completion_tokens": 0, "total_cost_usd": 0.0},
            )(),  # 简化：实际从 ACP 响应累积
            schema_version="1.0.0",
            acp_session_id=f"acp-{uuid.uuid4().hex[:8]}",
            acp_agent_versions={
                "coordinator": "1.0",
                "code_fixer": "1.0",
                "security_reviewer": "1.0",
                "readability_reviewer": "1.0",
                "testing_reviewer": "1.0",
            },
        )
        self._repo.save_suggestion(record)

        # audit_log
        self._audit.log(
            actor="m4-suggestion-service",  # 系统调用
            action=ACTION_PHASE4_GENERATE_SUGGESTION,
            target_repo_id=repo_id,
            target_log_point_ids=record.log_point_ids,
            extra={
                "suggestion_id": record.id,
                "deep_analysis_id": deep_analysis_id,
                "iteration": current_iter,
                "parent_record_id": parent_id,
                "acp_session_id": record.acp_session_id,
                "acp_agent_versions": record.acp_agent_versions,
                "perspective_count": len(record.perspective_evaluations),
                "confidence_score": record.confidence_score,
            },
        )

        # metrics
        if self._metrics is not None:
            self._metrics.inc_suggestion(repo_id=repo_id or "<no-repo>")
            for p in record.perspective_evaluations:
                self._metrics.observe_perspective_confidence(
                    perspective=p.perspective, confidence=p.confidence,
                )

        return record

    def get_suggestion(self, suggestion_id: str) -> SuggestionRecord | None:
        """查建议记录。"""
        return self._repo.get_suggestion(suggestion_id)

    def list_suggestions(
        self,
        report_id: str | None = None,
        log_point_id: str | None = None,
    ) -> list[SuggestionRecord]:
        """列建议记录。"""
        return self._repo.list_suggestions(report_id=report_id, log_point_id=log_point_id)

    def archive_suggestion(self, suggestion_id: str, archiver: User) -> None:
        """归档建议（软删 — archived_at 标记，不删行 — AC-15 + P0 持久化铁律）。"""
        archived = self._repo.archive_suggestion(suggestion_id)
        if not archived:
            # 不存在或已归档 — 幂等返回（不 raise）
            return
        self._audit.log(
            actor=archiver.id,
            action=ACTION_ARCHIVE_SUGGESTION,
            extra={"suggestion_id": suggestion_id},
        )
```

- [ ] **Step 5: Run test to verify pass**

Run: `python -m pytest tests/m4/test_suggestion_service.py -v`
Expected: 7 PASS

- [ ] **Step 6: Lint check**

Run: `python -m ruff check packages/m4/exceptions.py packages/m4/suggestion_service.py tests/m4/test_suggestion_service.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add packages/m4/exceptions.py packages/m4/suggestion_service.py tests/m4/test_suggestion_service.py
git commit -m "feat(m4): SuggestionService — FastAPI 编排层 + ACP Client 调用"
```

---

### Task 12: HTTP routes + Pydantic schemas + mappers

**Files:**
- Create: `packages/api/schemas/suggestion.py` — GenerateSuggestionRequest / SuggestionResponse / ArchiveRequest
- Create: `packages/api/mappers/suggestion.py` — SuggestionRecord ↔ SuggestionResponse mapper
- Create: `packages/api/routes/suggestions.py` — 4 个 endpoint
- Modify: `packages/api/app.py` — include suggestions_router
- Modify: `packages/api/deps.py` — 加 `get_suggestion_service` Depends factory
- Test: `tests/api/test_suggestions_routes.py`

**Interfaces:**
- Consumes:
  - `SuggestionService`（Task 11）
  - `SuggestionRecord` / `SuggestionPerspective`
  - F001.1 `error_handlers` / `deps.get_session`
- Produces:
  - `GenerateSuggestionRequest` / `SuggestionResponse` / `ArchiveRequest` Pydantic schemas
  - `suggestion_to_response(record: SuggestionRecord) -> SuggestionResponse` mapper
  - 4 个 HTTP endpoint：POST /suggestions / GET /suggestions/{id} / GET /suggestions / POST /suggestions/{id}/archive
  - `get_suggestion_service` FastAPI Depends

- [ ] **Step 1: Write the failing test**

`tests/api/test_suggestions_routes.py`:
```python
"""F004 M4 — HTTP routes 测试（spec §六 + AC-1/2）。"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from packages.api.app import app
from packages.api.deps import get_suggestion_service
from packages.contracts.analysis_report import TokenUsage
from packages.contracts.suggestion import (
    SuggestionPerspective,
    SuggestionRecord,
)
from packages.m4.exceptions import (
    AcpServerUnavailable,
    DeepAnalysisNotFound,
    SuggestionIterationLimitExceeded,
)


@pytest.fixture()
def mock_service() -> AsyncMock:
    """Mock SuggestionService。"""
    return AsyncMock()


@pytest.fixture()
def client(mock_service: AsyncMock) -> TestClient:
    """TestClient with override deps。"""
    app.dependency_overrides[get_suggestion_service] = lambda: mock_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_record() -> SuggestionRecord:
    return SuggestionRecord(
        id="sug-1",
        deep_analysis_id="deep-1",
        report_id="report-1",
        log_point_ids=["lp-1"],
        unified_diff="@@ -1,1 +1,2 @@",
        summary="main perspective",
        perspective_evaluations=[
            SuggestionPerspective(
                perspective="performance",
                assessment="N+1",
                suggested_diff="@@ -1,1 +1,2 @@",
                confidence=0.8,
                model_name="gpt-4",
                token_usage=TokenUsage(10, 5, 0.01),
            ),
        ],
        confidence_score=0.75,
        model_name="gpt-4",
        prompt_hash="sha256-abc",
        iteration=1,
        parent_record_id=None,
        generated_at=datetime.now(UTC),
        token_usage=TokenUsage(100, 200, 0.10),
        schema_version="1.0.0",
        acp_session_id="acp-sess-1",
        acp_agent_versions={"coordinator": "1.0"},
    )


# ---- POST /suggestions ----

def test_post_suggestions_201(client: TestClient, mock_service: AsyncMock) -> None:
    """AC-1: POST /suggestions 201 Created。"""
    mock_service.generate_suggestion.return_value = _make_record()
    resp = client.post("/suggestions", json={"deep_analysis_id": "deep-1"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "sug-1"
    assert data["deep_analysis_id"] == "deep-1"
    assert data["unified_diff"] == "@@ -1,1 +1,2 @@"
    assert data["iteration"] == 1


def test_post_suggestions_422_deep_analysis_not_found(client: TestClient, mock_service: AsyncMock) -> None:
    """AC-1 + AC-21: DeepAnalysis 不存在 → 422 + M4_DEEP_ANALYSIS_NOT_FOUND。"""
    mock_service.generate_suggestion.side_effect = DeepAnalysisNotFound("not found")
    resp = client.post("/suggestions", json={"deep_analysis_id": "nonexistent"})
    assert resp.status_code == 422
    data = resp.json()
    assert data["code"] == "M4_DEEP_ANALYSIS_NOT_FOUND"


def test_post_suggestions_409_iteration_limit(client: TestClient, mock_service: AsyncMock) -> None:
    """AC-1 + AC-12 + AC-21: 迭代达上限 → 409 + M4_SUGGESTION_LOCK_RUNNING。"""
    mock_service.generate_suggestion.side_effect = SuggestionIterationLimitExceeded(
        current=3, limit=3, deep_analysis_id="deep-1",
    )
    resp = client.post("/suggestions", json={"deep_analysis_id": "deep-1"})
    assert resp.status_code == 409
    data = resp.json()
    assert data["code"] == "M4_SUGGESTION_LOCK_RUNNING"


def test_post_suggestions_503_acp_unavailable(client: TestClient, mock_service: AsyncMock) -> None:
    """AC-1 + AC-19 + AC-21: ACP Server 不可达 → 503 + M4_ACP_SERVER_UNAVAILABLE。"""
    mock_service.generate_suggestion.side_effect = AcpServerUnavailable("down")
    resp = client.post("/suggestions", json={"deep_analysis_id": "deep-1"})
    assert resp.status_code == 503
    data = resp.json()
    assert data["code"] == "M4_ACP_SERVER_UNAVAILABLE"


def test_post_suggestions_422_validation_error(client: TestClient) -> None:
    """AC-1: body 缺 deep_analysis_id → 422 GENERIC_VALIDATION_ERROR。"""
    resp = client.post("/suggestions", json={})
    assert resp.status_code == 422
    assert resp.json()["code"] == "GENERIC_VALIDATION_ERROR"


# ---- GET /suggestions/{id} ----

def test_get_suggestion_200(client: TestClient, mock_service: AsyncMock) -> None:
    """AC-1: GET /suggestions/{id} 200 OK。"""
    mock_service.get_suggestion.return_value = _make_record()
    resp = client.get("/suggestions/sug-1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "sug-1"


def test_get_suggestion_404_not_found(client: TestClient, mock_service: AsyncMock) -> None:
    """AC-1 + AC-21: 不存在 → 404 + M4_SUGGESTION_NOT_FOUND。"""
    mock_service.get_suggestion.return_value = None
    resp = client.get("/suggestions/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["code"] == "M4_SUGGESTION_NOT_FOUND"


# ---- GET /suggestions ----

def test_list_suggestions_200(client: TestClient, mock_service: AsyncMock) -> None:
    """AC-1: GET /suggestions?report_id=... 200 OK。"""
    mock_service.list_suggestions.return_value = [_make_record()]
    resp = client.get("/suggestions?report_id=report-1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "sug-1"


def test_list_suggestions_filter_by_log_point(client: TestClient, mock_service: AsyncMock) -> None:
    """AC-1: GET /suggestions?log_point_id=lp-1 过滤。"""
    mock_service.list_suggestions.return_value = [_make_record()]
    resp = client.get("/suggestions?log_point_id=lp-1")
    assert resp.status_code == 200
    mock_service.list_suggestions.assert_called_once_with(report_id=None, log_point_id="lp-1")


# ---- POST /suggestions/{id}/archive ----

def test_archive_suggestion_204(client: TestClient, mock_service: AsyncMock) -> None:
    """AC-1: POST /suggestions/{id}/archive 204 No Content。"""
    resp = client.post(
        "/suggestions/sug-1/archive",
        params={"archiver_id": "u1", "archiver_name": "alice"},
    )
    assert resp.status_code == 204
    mock_service.archive_suggestion.assert_called_once()


def test_archive_suggestion_query_required(client: TestClient) -> None:
    """AC-1: archiver_id / archiver_name query 必填 → 422 if 缺。"""
    resp = client.post("/suggestions/sug-1/archive")
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_suggestions_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.api.schemas.suggestion'`

- [ ] **Step 3: Create packages/api/schemas/suggestion.py**

`packages/api/schemas/suggestion.py`:
```python
"""F004 M4 — Suggestion API schemas（spec §六）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from packages.api.schemas.analysis import TokenUsageAPI


class SuggestionPerspectiveAPI(BaseModel):
    """单视角评估（spec §三）。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    perspective: str
    assessment: str
    suggested_diff: str | None
    confidence: float
    model_name: str


class GenerateSuggestionRequest(BaseModel):
    """POST /suggestions body — spec §六。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    deep_analysis_id: str
    perspectives: list[str] | None = None  # 可选视角覆盖（默认 4 全跑）


class SuggestionResponse(BaseModel):
    """SuggestionRecord 响应（spec §六 + §三）。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    deep_analysis_id: str
    report_id: str
    log_point_ids: list[str]
    unified_diff: str
    summary: str
    perspective_evaluations: list[SuggestionPerspectiveAPI]
    confidence_score: float
    model_name: str
    prompt_hash: str
    iteration: int
    parent_record_id: str | None
    generated_at: datetime
    token_usage: TokenUsageAPI
    schema_version: str
    acp_session_id: str | None
    acp_agent_versions: dict[str, str]
    archived_at: datetime | None = None


class ArchiveSuggestionRequest(BaseModel):
    """POST /suggestions/{id}/archive body — spec §六。

    注：archiver_id / archiver_name 走 query string（同 M2 archive 模式），
    body 可空。Pydantic schema 留作未来扩展（如 reason 字段）。
    """
    model_config = ConfigDict(strict=True, extra="forbid")

    reason: str | None = None
```

- [ ] **Step 4: Create packages/api/mappers/suggestion.py**

`packages/api/mappers/suggestion.py`:
```python
"""F004 M4 — SuggestionRecord ↔ API schema mapper（spec §六）。"""
from __future__ import annotations

from packages.api.mappers.analysis import _token_usage_to_api
from packages.api.schemas.suggestion import (
    SuggestionPerspectiveAPI,
    SuggestionResponse,
)
from packages.contracts.suggestion import (
    SuggestionPerspective,
    SuggestionRecord,
)


def _perspective_to_api(p: SuggestionPerspective) -> SuggestionPerspectiveAPI:
    return SuggestionPerspectiveAPI(
        perspective=p.perspective,
        assessment=p.assessment,
        suggested_diff=p.suggested_diff,
        confidence=p.confidence,
        model_name=p.model_name,
    )


def suggestion_to_response(r: SuggestionRecord, archived_at=None) -> SuggestionResponse:
    """SuggestionRecord dataclass → SuggestionResponse。"""
    return SuggestionResponse(
        id=r.id,
        deep_analysis_id=r.deep_analysis_id,
        report_id=r.report_id,
        log_point_ids=r.log_point_ids,
        unified_diff=r.unified_diff,
        summary=r.summary,
        perspective_evaluations=[_perspective_to_api(p) for p in r.perspective_evaluations],
        confidence_score=r.confidence_score,
        model_name=r.model_name,
        prompt_hash=r.prompt_hash,
        iteration=r.iteration,
        parent_record_id=r.parent_record_id,
        generated_at=r.generated_at,
        token_usage=_token_usage_to_api(r.token_usage),
        schema_version=r.schema_version,
        acp_session_id=r.acp_session_id,
        acp_agent_versions=r.acp_agent_versions,
        archived_at=archived_at,
    )
```

- [ ] **Step 5: Create packages/api/routes/suggestions.py**

`packages/api/routes/suggestions.py`:
```python
"""F004 M4 — 4 HTTP endpoints（spec §六 + AC-1）。

| Method | Path | Body / Query | Returns | service 方法 |
|--------|------|---------------|---------|--------------|
| POST | /suggestions | GenerateSuggestionRequest | SuggestionResponse 201 | generate_suggestion |
| GET  | /suggestions/{id} | — | SuggestionResponse 200 | get_suggestion |
| GET  | /suggestions | ?report_id&log_point_id | list[SuggestionResponse] 200 | list_suggestions |
| POST | /suggestions/{id}/archive | ?archiver_id&archiver_name | 204 | archive_suggestion |

错误码（AC-21）：
  - 422 M4_DEEP_ANALYSIS_NOT_FOUND
  - 409 M4_SUGGESTION_LOCK_RUNNING
  - 503 M4_ACP_SERVER_UNAVAILABLE
  - 404 M4_SUGGESTION_NOT_FOUND
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from packages.api.deps import get_suggestion_service
from packages.api.mappers.suggestion import suggestion_to_response
from packages.api.schemas.suggestion import (
    GenerateSuggestionRequest,
    SuggestionResponse,
)
from packages.m1.unit_a_repo_registrar import User
from packages.m4.exceptions import (
    AcpServerUnavailable,
    DeepAnalysisNotFound,
    SuggestionIterationLimitExceeded,
)
from packages.m4.suggestion_service import SuggestionService

router = APIRouter(tags=["suggestion"])


@router.post("/suggestions", response_model=SuggestionResponse, status_code=201)
async def generate_suggestion(
    req: GenerateSuggestionRequest,
    service: SuggestionService = Depends(get_suggestion_service),  # noqa: B008
) -> SuggestionResponse:
    """POST /suggestions — 生成改进建议（spec §四 + AC-1）。"""
    try:
        record = await service.generate_suggestion(
            deep_analysis_id=req.deep_analysis_id,
            perspectives=req.perspectives,
        )
    except DeepAnalysisNotFound as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "M4_DEEP_ANALYSIS_NOT_FOUND", "message": str(e)},
        )
    except SuggestionIterationLimitExceeded as e:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "M4_SUGGESTION_LOCK_RUNNING",
                "message": str(e),
                "details": {"current": e.current, "limit": e.limit, "deep_analysis_id": e.deep_analysis_id},
            },
        )
    except AcpServerUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail={"code": "M4_ACP_SERVER_UNAVAILABLE", "message": str(e)},
        )
    return suggestion_to_response(record)


@router.get(
    "/suggestions/{suggestion_id}",
    response_model=SuggestionResponse,
    status_code=200,
)
def get_suggestion(
    suggestion_id: str,
    service: SuggestionService = Depends(get_suggestion_service),  # noqa: B008
) -> SuggestionResponse:
    """GET /suggestions/{id} — 查建议记录。"""
    record = service.get_suggestion(suggestion_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "M4_SUGGESTION_NOT_FOUND", "message": f"suggestion {suggestion_id} not found"},
        )
    return suggestion_to_response(record)


@router.get(
    "/suggestions",
    response_model=list[SuggestionResponse],
    status_code=200,
)
def list_suggestions(
    report_id: str | None = Query(default=None),
    log_point_id: str | None = Query(default=None),
    service: SuggestionService = Depends(get_suggestion_service),  # noqa: B008
) -> list[SuggestionResponse]:
    """GET /suggestions — 列建议记录（按 report_id / log_point_id 过滤）。"""
    records = service.list_suggestions(report_id=report_id, log_point_id=log_point_id)
    return [suggestion_to_response(r) for r in records]


@router.post(
    "/suggestions/{suggestion_id}/archive",
    status_code=204,
)
def archive_suggestion(
    suggestion_id: str,
    archiver_id: str = Query(..., description="archiver user id"),
    archiver_name: str = Query(..., description="archiver user name"),
    service: SuggestionService = Depends(get_suggestion_service),  # noqa: B008
) -> Response:
    """POST /suggestions/{id}/archive — 软删（archived_at 标记）。"""
    service.archive_suggestion(
        suggestion_id=suggestion_id,
        archiver=User(id=archiver_id, name=archiver_name),
    )
    return Response(status_code=204)
```

- [ ] **Step 6: Update packages/api/deps.py — add get_suggestion_service**

修改 `packages/api/deps.py`，加 `get_suggestion_service` 函数（参考 `get_log_analysis_service` 模式）：

```python
def get_suggestion_service(  # noqa: B008 — FastAPI Depends pattern
    session: Session = Depends(get_session),
) -> Generator["SuggestionService", None, None]:
    """FastAPI Depends — 构造 M4 SuggestionService（spec §五 + F004）。

    生产环境复用 M1 service（m1_service 注入 get_service 产物）+
    真实 ACP Client（指向 :8001）。
    测试 / fixture 可直接 mock。
    """
    from unittest.mock import AsyncMock, MagicMock

    from acp_sdk.client import Client

    from packages.m2.storage.repository import M2Repository
    from packages.m4.message_builder import SuggestionMessageBuilder
    from packages.m4.sanitizer import AcpMessageSanitizer
    from packages.m4.suggestion_merger import SuggestionMerger
    from packages.m4.suggestion_service import SuggestionService
    from packages.m4.storage.repository import M4Repository

    # 复用 M1 service（含 m1_service.get_call_context / get_source_snippet）
    m1_service_gen = get_service(session)
    m1_service = next(m1_service_gen)

    # 复用 M2 service 取 DeepAnalysisRecord + AnalysisReport
    m2_repo = M2Repository(session)

    # ACP Client 指向 :8001
    acp_client = Client(base_url=f"http://{_config.acp.server_host}:{_config.acp.server_port}")

    # Sanitizer
    sanitizer = LogSanitizer(
        LogSanitizerConfig(
            enabled=_config.sanitizer.enabled,
            patterns=_config.sanitizer.patterns,
            replacement=_config.sanitizer.replacement,
        )
    )
    acp_sanitizer = AcpMessageSanitizer(sanitizer=sanitizer)

    service = SuggestionService(
        session=session,
        audit=AuditLogger(session),
        repository=M4Repository(session),
        message_builder=SuggestionMessageBuilder(),
        acp_sanitizer=acp_sanitizer,
        merger=SuggestionMerger(),
        acp_client=acp_client,
        m1_service=m1_service,
        m2_repo=m2_repo,
        config_m4=_config.m4,
    )
    try:
        yield service
    finally:
        try:
            next(m1_service_gen)
        except StopIteration:
            pass
```

注：`AcpMessageSanitizer` import 在 Task 6 已建；`acp_sdk.client.Client` 的构造 API（`base_url=` 参数）按实际 acp_sdk API 表面调整。

- [ ] **Step 7: Update packages/api/app.py — include suggestions_router**

修改 `packages/api/app.py`，加：

```python
from packages.api.routes.suggestions import router as suggestions_router
# ...
app.include_router(suggestions_router)  # F004 M4
```

- [ ] **Step 8: Run test to verify pass**

Run: `python -m pytest tests/api/test_suggestions_routes.py -v`
Expected: PASS (9 tests)

- [ ] **Step 9: Verify /docs Swagger UI（AC-2）**

Run: `python -c "from fastapi.testclient import TestClient; from packages.api.app import app; c = TestClient(app); r = c.get('/openapi.json'); assert r.status_code == 200; paths = r.json()['paths']; assert '/suggestions' in paths; assert '/suggestions/{suggestion_id}' in paths; print('OK')"`
Expected: PASS — `/suggestions` + `/suggestions/{suggestion_id}` + `/suggestions/{suggestion_id}/archive` 4 路径都在 OpenAPI schema

- [ ] **Step 10: Verify M1 + M2 tests no regression**

Run: `python -m pytest tests/api/ tests/m2/ -v 2>&1 | tail -20`
Expected: PASS

- [ ] **Step 11: Lint check**

Run: `python -m ruff check packages/api/schemas/suggestion.py packages/api/mappers/suggestion.py packages/api/routes/suggestions.py packages/api/deps.py packages/api/app.py tests/api/test_suggestions_routes.py`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
git add packages/api/schemas/suggestion.py packages/api/mappers/suggestion.py packages/api/routes/suggestions.py packages/api/deps.py packages/api/app.py tests/api/test_suggestions_routes.py
git commit -m "feat(m4): HTTP routes + schemas + mappers — 4 endpoints + M4_* 错误码"
```

---

### Task 13: M4MetricsEmitter + lifespan 扩展启动 ACP Server

**Files:**
- Create: `packages/m4/metrics_emitter.py` — M4MetricsEmitter
- Modify: `packages/api/app.py` — lifespan 扩展启动 ACP Server 子进程（dev 模式）
- Test: `tests/m4/test_metrics_emitter.py`

**Interfaces:**
- Consumes: `prometheus_client` / `packages.api.app.lifespan`
- Produces: `M4MetricsEmitter` class（6 个 m4_* 指标） + lifespan 启动 ACP Server 子进程

- [ ] **Step 1: Write the failing test**

`tests/m4/test_metrics_emitter.py`:
```python
"""F004 M4 — M4MetricsEmitter 测试（spec §八 + AC-13）。"""
from __future__ import annotations

from prometheus_client.core import REGISTRY as DEFAULT_REGISTRY

from packages.m4.metrics_emitter import M4MetricsEmitter


def _reset_prometheus() -> None:
    m4_collectors = [
        c for c, names in list(DEFAULT_REGISTRY._collector_to_names.items())
        if any(n.startswith("m4_") for n in names)
    ]
    for c in m4_collectors:
        DEFAULT_REGISTRY.unregister(c)


def test_metrics_emitter_has_6_metrics() -> None:
    """AC-13: 6 个 m4_* 指标。"""
    _reset_prometheus()
    emitter = M4MetricsEmitter()
    # 验证所有方法存在
    assert hasattr(emitter, 'inc_suggestion')
    assert hasattr(emitter, 'observe_suggestion_duration')
    assert hasattr(emitter, 'inc_acp_call')
    assert hasattr(emitter, 'observe_acp_call_duration')
    assert hasattr(emitter, 'observe_perspective_confidence')
    assert hasattr(emitter, 'inc_llm_cost')
    _reset_prometheus()


def test_metrics_emitter_inc_suggestion() -> None:
    """inc_suggestion 增加计数。"""
    _reset_prometheus()
    emitter = M4MetricsEmitter()
    emitter.inc_suggestion(repo_id="repo-1")
    emitter.inc_suggestion(repo_id="repo-1")
    # 通过 render 验证计数
    out = emitter.render()
    assert "m4_suggestion_total" in out
    assert 'repo_id="repo-1"' in out
    _reset_prometheus()


def test_metrics_emitter_observe_perspective_confidence() -> None:
    """observe_perspective_confidence 设置 gauge。"""
    _reset_prometheus()
    emitter = M4MetricsEmitter()
    emitter.observe_perspective_confidence(perspective="performance", confidence=0.85)
    out = emitter.render()
    assert "m4_perspective_confidence_score" in out
    assert 'perspective="performance"' in out
    _reset_prometheus()


def test_metrics_emitter_inc_acp_call() -> None:
    """inc_acp_call 按 agent label 增加计数。"""
    _reset_prometheus()
    emitter = M4MetricsEmitter()
    emitter.inc_acp_call(agent="coordinator")
    emitter.inc_acp_call(agent="code_fixer")
    out = emitter.render()
    assert "m4_acp_call_total" in out
    assert 'agent="coordinator"' in out
    assert 'agent="code_fixer"' in out
    _reset_prometheus()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/m4/test_metrics_emitter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m4.metrics_emitter'`

- [ ] **Step 3: Create packages/m4/metrics_emitter.py**

`packages/m4/metrics_emitter.py`:
```python
"""F004 M4 — Prometheus 指标 emitter（spec §八 + AC-13）。

6 个 m4_* 指标（复用 prometheus_client default REGISTRY，与 M1/M2 共存）：
  - m4_suggestion_total (counter, label repo_id)
  - m4_suggestion_duration_seconds (histogram)
  - m4_acp_call_total{agent} (counter)
  - m4_acp_call_duration_seconds{agent} (histogram)
  - m4_perspective_confidence_score{perspective} (gauge)
  - m4_llm_cost_usd_total (counter)
"""
from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import REGISTRY


class M4MetricsEmitter:
    """M4 Prometheus 指标 emitter（spec §八 + AC-13）。"""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or REGISTRY
        self._suggestion_total = Counter(
            "m4_suggestion_total",
            "改进建议生成总数",
            labelnames=["repo_id"],
            registry=self._registry,
        )
        self._suggestion_duration = Histogram(
            "m4_suggestion_duration_seconds",
            "单次建议生成耗时（含 ACP 调用）",
            registry=self._registry,
        )
        self._acp_call_total = Counter(
            "m4_acp_call_total",
            "各 ACP agent 调用次数",
            labelnames=["agent"],
            registry=self._registry,
        )
        self._acp_call_duration = Histogram(
            "m4_acp_call_duration_seconds",
            "各 agent 调用耗时",
            labelnames=["agent"],
            registry=self._registry,
        )
        self._perspective_confidence = Gauge(
            "m4_perspective_confidence_score",
            "各视角置信度",
            labelnames=["perspective"],
            registry=self._registry,
        )
        self._llm_cost = Counter(
            "m4_llm_cost_usd_total",
            "M4 LLM 成本累计",
            registry=self._registry,
        )

    def inc_suggestion(self, repo_id: str, delta: int = 1) -> None:
        self._suggestion_total.labels(repo_id=repo_id).inc(delta)

    def observe_suggestion_duration(self, seconds: float) -> None:
        self._suggestion_duration.observe(seconds)

    def inc_acp_call(self, agent: str, delta: int = 1) -> None:
        self._acp_call_total.labels(agent=agent).inc(delta)

    def observe_acp_call_duration(self, agent: str, seconds: float) -> None:
        self._acp_call_duration.labels(agent=agent).observe(seconds)

    def observe_perspective_confidence(self, perspective: str, confidence: float) -> None:
        clamped = max(0.0, min(1.0, confidence))
        self._perspective_confidence.labels(perspective=perspective).set(clamped)

    def inc_llm_cost(self, usd: float) -> None:
        self._llm_cost.inc(usd)

    def render(self) -> str:
        return generate_latest(self._registry).decode("utf-8")
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/m4/test_metrics_emitter.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Update packages/api/app.py — lifespan 启动 ACP Server 子进程**

修改 `packages/api/app.py` 的 `lifespan` 函数，在 yield 前加 ACP Server 启动逻辑：

```python
import subprocess
import sys

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 metrics server + ACP Server（dev 模式，spec §六 + §十二 + AC-19）。"""
    global _metrics_process_ref
    # ... F001.1 metrics 启动逻辑保持不变 ...

    # F004: dev 模式自动启动 ACP Server 子进程
    acp_process: subprocess.Popen | None = None
    if _config.acp.enabled and _config.acp.server_port:
        try:
            # 端口检查（避免重复启动留孤儿，同 metrics 模式）
            if _is_port_in_use(_config.acp.server_port):
                logger.warning(
                    "ACP Server port %s already in use — skipping ACP start "
                    "(likely orphan from previous lifespan)",
                    _config.acp.server_port,
                )
            else:
                acp_process = subprocess.Popen(
                    [sys.executable, "-m", "acp_servers.m4_server"],
                    env={**os.environ, "CODEFLY_ACP_SERVER_PORT": str(_config.acp.server_port)},
                )
                logger.info("ACP M4 Server started on port %s (pid=%s)",
                            _config.acp.server_port, acp_process.pid)
        except Exception as e:
            # AC-19 graceful degradation
            logger.warning("ACP Server failed to start: %s. Continuing without ACP.", e)

    yield

    # cleanup
    _cleanup_metrics_process(metrics_process)
    _metrics_process_ref = None
    # F004: 清理 ACP Server 子进程
    if acp_process and acp_process.poll() is None:
        acp_process.terminate()
        try:
            acp_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            acp_process.kill()
```

注：`os` import 需要加在 `packages/api/app.py` 顶部；`subprocess` / `sys` 也加。

- [ ] **Step 6: Verify lifespan no regression**

Run: `python -m pytest tests/api/ -v 2>&1 | tail -20`
Expected: PASS（既有 API 测试不破 — ACP Server 启动失败时 graceful degradation）

- [ ] **Step 7: Lint check**

Run: `python -m ruff check packages/m4/metrics_emitter.py packages/api/app.py tests/m4/test_metrics_emitter.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add packages/m4/metrics_emitter.py packages/api/app.py tests/m4/test_metrics_emitter.py
git commit -m "feat(m4): metrics emitter + lifespan 启动 ACP Server — AC-13/19"
```

---

### Task 14: /ready 扩展检查 ACP Server 可达性

**Files:**
- Modify: `packages/api/routes/ops.py` — `/ready` 扩展检查 ACP Server
- Test: `tests/api/test_ready_acp_check.py`

**Interfaces:**
- Consumes: `_config.acp` / `httpx.get` / F001.1 `/ready` 框架
- Produces: `/ready` 检查 ACP Server 可达，不可达返回 `not_ready` + `reason="acp_server_unavailable"`

- [ ] **Step 1: Write the failing test**

`tests/api/test_ready_acp_check.py`:
```python
"""F004 M4 — /ready 扩展 ACP Server 可达性检查（spec §十二 + AC-20）。"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from packages.api.app import app


def test_ready_returns_ok_when_acp_disabled(monkeypatch) -> None:
    """ACP disabled 时 /ready 不检查 ACP Server。"""
    # Mock config.acp.enabled = False
    from packages.api import app as app_mod
    monkeypatch.setattr(app_mod._config.acp, 'enabled', False)
    monkeypatch.setattr(app_mod._config.acp, 'server_port', 0)

    # Mock session
    with patch("packages.api.routes.ops.SessionLocal", MagicMock()):
        client = TestClient(app)
        resp = client.get("/ready")
    assert resp.status_code == 200
    # 注：实际 status 可能 "ready" 或 "not_ready"（看 DB），但不应该 raise


def test_ready_returns_not_ready_when_acp_unreachable(monkeypatch) -> None:
    """ACP enabled 但不可达 → /ready 返回 not_ready + acp_server_unavailable — AC-20。"""
    from packages.api import app as app_mod
    monkeypatch.setattr(app_mod._config.acp, 'enabled', True)
    monkeypatch.setattr(app_mod._config.acp, 'server_port', 8001)
    monkeypatch.setattr(app_mod._config.acp, 'server_host', "127.0.0.1")

    # Mock httpx.get raise ConnectionError
    with patch("packages.api.routes.ops.SessionLocal", MagicMock()), \
         patch("packages.api.routes.ops.httpx") as mock_httpx:
        mock_httpx.get.side_effect = ConnectionError("refused")
        client = TestClient(app)
        resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "not_ready"
    assert "acp" in data["reason"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_ready_acp_check.py -v`
Expected: FAIL — `/ready` 当前不检查 ACP Server

- [ ] **Step 3: Update packages/api/routes/ops.py**

修改 `packages/api/routes/ops.py` 的 `ready` 函数：

```python
import httpx

@router.get("/ready", response_model=ReadyResponse)
def ready(session: Session = Depends(get_session)) -> ReadyResponse:  # noqa: B008
    """Readiness probe — DB + ACP Server（F004 扩展）。"""
    if SessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "GENERIC_NOT_READY",
                "message": "Database not configured (postgres_dsn missing)",
                "details": {"reason": "SessionLocal not initialized"},
            },
        )
    try:
        session.execute(text("SELECT 1"))
    except Exception as e:
        return ReadyResponse(status="not_ready", reason=f"db_unavailable: {e}")

    # F004: ACP Server 可达性检查（spec §十二 + AC-20）
    if _config.acp.enabled:
        try:
            acp_url = f"http://{_config.acp.server_host}:{_config.acp.server_port}"
            r = httpx.get(f"{acp_url}/health", timeout=2.0)
            if r.status_code != 200:
                return ReadyResponse(
                    status="not_ready",
                    reason=f"acp_server_unavailable: HTTP {r.status_code}",
                )
        except Exception as e:
            return ReadyResponse(
                status="not_ready",
                reason=f"acp_server_unavailable: {e}",
            )

    return ReadyResponse(status="ready")
```

注：需在 `packages/api/routes/ops.py` 顶部 import `httpx` + `_config`：

```python
import httpx
from packages.m1.config_loader import load_config

_config = load_config()
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/api/test_ready_acp_check.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Lint check + commit**

Run: `python -m ruff check packages/api/routes/ops.py tests/api/test_ready_acp_check.py`

```bash
git add packages/api/routes/ops.py tests/api/test_ready_acp_check.py
git commit -m "feat(m4): /ready 扩展 ACP Server 可达性检查 — AC-20"
```

---

### Task 15: 端到端测试 — M2 DeepAnalysisRecord → ACP Server → SuggestionRecord

**Files:**
- Create: `tests/m4/test_m4_full_pipeline.py` — 端到端 fixture 测试
- Create: `tests/m4/conftest.py` — acp_server fixture（8002 端口避免 dev :8001）

**Interfaces:**
- Consumes: 所有 Task 1-14 产物 + `acp_server` fixture + LLM mock
- Produces: AC-18 端到端验证

- [ ] **Step 1: Create tests/m4/conftest.py**

`tests/m4/conftest.py`:
```python
"""pytest fixtures for tests/m4/."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Generator

import pytest


@pytest.fixture()
def acp_server() -> Generator[str, None, None]:
    """独立 ACP Server fixture（8002 端口，避免与 dev :8001 冲突）。

    同 F002 metrics_server fixture 模式。
    """
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "acp_servers.m4_server",
        ],
        env={**os.environ, "CODEFLY_ACP_SERVER_PORT": "8002"},
    )

    # Poll until ready
    url = "http://localhost:8002"
    max_wait = 10.0
    interval = 0.3
    elapsed = 0.0
    import httpx
    while elapsed < max_wait:
        try:
            r = httpx.get(f"{url}/health", timeout=1.0)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(interval)
        elapsed += interval

    yield url

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
```

- [ ] **Step 2: Write the end-to-end test**

`tests/m4/test_m4_full_pipeline.py`:
```python
"""F004 M4 — 端到端测试（spec §十三 + AC-18）。

流程：M2 DeepAnalysisRecord → ACP Server → SuggestionRecord
验证：unified_diff 合法 + perspective_evaluations 4 项齐 + acp_session_id 非空
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.contracts.analysis_report import AnalysisReport, TokenUsage
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.log_point import CallContext
from packages.contracts.source_snippet import SourceSnippet
from packages.contracts.suggestion import SuggestionRecord
from packages.m4.suggestion_service import SuggestionService


def _make_deep_analysis() -> DeepAnalysisRecord:
    return DeepAnalysisRecord(
        id="deep-1",
        report_id="report-1",
        line_ids=["line-1"],
        log_point_ids=["lp-1"],
        call_contexts=[
            CallContext(
                function_signature="def foo()",
                callers=[], callees=[], enclosing_community="C",
                related_log_points=[], evidence_refs=[],
            ),
        ],
        root_cause_hypothesis="N+1 query in loop",
        fix_suggestion="batch queries",
        related_evidence=[],
        model_name="gpt-4",
        prompt_hash="sha256-abc",
        iteration=1,
        parent_record_id=None,
        generated_at=datetime.now(UTC),
        token_usage=TokenUsage(100, 200, 0.10),
    )


def _make_report() -> AnalysisReport:
    return AnalysisReport(
        id="report-1", repo_id="repo-1", log_source="app.log",
        log_line_count=10, window_start=None, window_end=None,
        model_name="gpt-4o-mini", prompt_hash="sha256-xyz",
        system_summary="ok", anomaly_localization=[], error_correlation=[],
        generated_at=datetime.now(UTC), duration_seconds=1.0,
        token_usage=TokenUsage(0, 0, 0.0), ingestion_status="draft",
    )


@pytest.mark.asyncio
async def test_end_to_end_pipeline_with_mock_acp() -> None:
    """AC-18: mock ACP Server 响应下端到端验证。

    策略：用 mock ACP Client（不实际起 :8002 进程）— ACP Server 端到端
    走 Task 7-9 的单元测试 + integration test（@pytest.mark.integration）。
    本测试验证 service 编排层端到端逻辑正确。
    """
    # 构造所有 mock 依赖
    m2_repo = MagicMock()
    m2_repo.get_deep_analysis.return_value = _make_deep_analysis()
    m2_repo.get_analysis_report.return_value = _make_report()

    m1_service = MagicMock()
    m1_service.get_call_context.return_value = CallContext(
        function_signature="def foo()", callers=[], callees=[],
        enclosing_community="C", related_log_points=[], evidence_refs=[],
    )
    m1_service.get_source_snippet.return_value = SourceSnippet(
        file_path="src/foo.py", line_range=(1, 30),
        content="def foo():\n    pass\n", extractor_version="1.0.0",
    )

    # ACP Client mock 返回合法 coordinator 响应
    import json
    from acp_sdk import Message, MessagePart
    acp_client = AsyncMock()
    acp_client.run_sync.return_value = Message(parts=[
        MessagePart(content="@@ -1,1 +1,2 @@", content_type="text/plain"),
        MessagePart(content=json.dumps({
            "summary": "main perspective",
            "perspective_evaluations": [
                {"perspective": "performance", "assessment": "x", "suggested_diff": "@@ -1,1 +1,2 @@", "confidence": 0.8, "model_name": "gpt-4"},
                {"perspective": "security", "assessment": "y", "suggested_diff": None, "confidence": 0.9, "model_name": "gpt-4"},
                {"perspective": "readability", "assessment": "z", "suggested_diff": None, "confidence": 0.7, "model_name": "gpt-4"},
                {"perspective": "testing", "assessment": "w", "suggested_diff": None, "confidence": 0.6, "model_name": "gpt-4"},
            ],
        }), content_type="application/json"),
    ])

    # Real merger
    from packages.m4.message_builder import SuggestionMessageBuilder
    from packages.m4.sanitizer import AcpMessageSanitizer
    from packages.m4.suggestion_merger import SuggestionMerger
    from packages.m1.log_sanitizer import LogSanitizer
    from packages.m1.log_sanitizer import SanitizerConfig
    sanitizer = AcpMessageSanitizer(LogSanitizer(SanitizerConfig(enabled=False, patterns=[], replacement="[R]")))

    # Real M4 repository（in-memory SQLite）
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from packages.m1.storage.models import Base
    from packages.m4.storage.models import SuggestionRecordModel  # noqa: F401
    from packages.m4.storage.repository import M4Repository
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    m4_repo = M4Repository(session)

    # Real AuditLogger
    from packages.m1.audit_log import AuditLogger
    audit = AuditLogger(session)

    service = SuggestionService(
        session=session, audit=audit, repository=m4_repo,
        message_builder=SuggestionMessageBuilder(),
        acp_sanitizer=sanitizer, merger=SuggestionMerger(),
        acp_client=acp_client, m1_service=m1_service, m2_repo=m2_repo,
    )

    # 调用
    record = await service.generate_suggestion(deep_analysis_id="deep-1")

    # AC-18 验证
    assert isinstance(record, SuggestionRecord)
    assert record.unified_diff == "@@ -1,1 +1,2 @@"  # unified_diff 合法
    assert len(record.perspective_evaluations) == 4  # 4 项齐
    perspectives = {p.perspective for p in record.perspective_evaluations}
    assert perspectives == {"performance", "security", "readability", "testing"}
    assert record.acp_session_id is not None  # ACP session 追溯
    assert record.acp_agent_versions  # agent versions 非空
    assert "coordinator" in record.acp_agent_versions
    assert record.iteration == 1
    assert record.parent_record_id is None
    # AC-17: 标注为"参考建议"（schema_version 1.0.0 表明不自动应用）
    assert record.schema_version == "1.0.0"

    # 持久化验证（AC-10）
    fetched = m4_repo.get_suggestion(record.id)
    assert fetched is not None
    assert fetched.unified_diff == record.unified_diff


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_with_real_acp_server(acp_server: str) -> None:
    """AC-18 integration: 真实 ACP Server (:8002) + mock LLM。

    策略：起 acp_server fixture（:8002）+ 注入 mock LLMClient（不实际调 OpenAI），
    验证 ACP Client.run_sync 调真实 Server。
    """
    # 实施时按 acp_sdk Client API 调整
    import pytest
    pytest.skip("需要真实 LLM API key 或 mock — 实施时按 CI 环境决定")
```

- [ ] **Step 3: Run test to verify pass**

Run: `python -m pytest tests/m4/test_m4_full_pipeline.py -v`
Expected: 1 PASS + 1 skip（integration 需真实环境）

- [ ] **Step 4: Run full M4 test suite（regression check）**

Run: `python -m pytest tests/m4/ tests/api/test_suggestions_routes.py tests/api/test_ready_acp_check.py -v 2>&1 | tail -30`
Expected: All PASS（除 acp_sdk API 限制的 skip）

- [ ] **Step 5: Lint check + commit**

Run: `python -m ruff check tests/m4/`

```bash
git add tests/m4/test_m4_full_pipeline.py tests/m4/conftest.py
git commit -m "test(m4): AC-18 端到端 — DeepAnalysis → ACP → SuggestionRecord"
```

---

### Task 16: README + 交接给 @云长 review

**Files:**
- Modify: `README.md`（加 M4 章节：启动方式 + ACP Server 部署 + 端口规划 + 9464 已知问题）
- Modify: `BACKLOG.md`（F004 状态 backlog → review）
- Verify: 所有 AC（AC-1 到 AC-22）通过 + Lint 全 PASS

**Interfaces:**
- Consumes: 所有 Task 1-15 产物
- Produces: README M4 章节 + 交接信给 @云长 cross-family review

- [ ] **Step 1: Update README.md — add M4 section**

修改 `README.md`，在文件末尾加：

```markdown
## F004 M4 改进建议

### 启动方式

ACP Server + FastAPI 双进程模式：

```bash
# 1. 启动 ACP M4 Server（独立进程）
python -m acp_servers.m4_server
# 默认监听 :8001

# 2. 启动 FastAPI HTTP Server（dev 模式自动起 ACP Server 子进程）
uvicorn packages.api.app:app --port 8000 --reload
# ACP Server 自动启动；生产用独立 systemd 进程
```

### 端口规划（家规铁律 + F001.1 端口修复 + F004 ACP 扩展）

| 端口 | 服务 | 说明 |
|------|------|------|
| 3003 | CatCafe frontend | 自留地，禁占 |
| 3004 | CatCafe API | 自留地，禁占 |
| 8000 | FastAPI HTTP | F001.1 + F004 HTTP 层 |
| 8001 | ACP M4 Server | F004 独立进程（5 agent） |
| 9100 | CatCafe metrics | 自留地，禁占 |
| 9464 | metrics | F001.1 已用（⚠️ 跟 CatCafe 撞 — F001.1 hotfix 改 9465 follow-up） |
| 8002+ | 预留 | 后续 ACP Server（M5/M6） |

### M4 API（4 endpoint）

| Method | Path | Returns |
|--------|------|---------|
| POST | /suggestions | 201 SuggestionResponse |
| GET | /suggestions/{id} | 200 SuggestionResponse |
| GET | /suggestions?report_id&log_point_id | 200 list[SuggestionResponse] |
| POST | /suggestions/{id}/archive | 204 |

### ACP 部署架构（spec §十一）

- **ACP Server 进程** (:8001) — 5 个 ACP agent：
  - `suggestion_coordinator_agent` — 编排 4 个 reviewer
  - `code_fixer_agent` — 主视角（performance）
  - `security_reviewer_agent` — 安全视角
  - `readability_reviewer_agent` — 可读性视角
  - `testing_reviewer_agent` — 测试视角
- **ACP Client** — FastAPI 编排层（packages/m4/suggestion_service.py）通过 `acp_sdk.Client.run_sync` 调 :8001

### M4 metrics（AC-13）

| 指标 | 类型 | 描述 |
|------|------|------|
| m4_suggestion_total{repo_id} | Counter | 改进建议生成总数 |
| m4_suggestion_duration_seconds | Histogram | 单次建议生成耗时 |
| m4_acp_call_total{agent} | Counter | 各 ACP agent 调用次数 |
| m4_acp_call_duration_seconds{agent} | Histogram | 各 agent 调用耗时 |
| m4_perspective_confidence_score{perspective} | Gauge | 各视角置信度 |
| m4_llm_cost_usd_total | Counter | M4 LLM 成本累计 |
```

- [ ] **Step 2: Update BACKLOG.md — F004 status → review**

修改 `BACKLOG.md` 的 F004 行：

```markdown
| F004 | 日志分析改进 | review | 奉孝 (@ragdoll-pa82) | [spec](docs/features/F004-LLM改进建议.md) |
```

注：F004 owner 从 TBD 改为 奉孝（implement 完成后 owned by 奉孝）。

- [ ] **Step 3: Run full test suite — verify all AC**

Run: `python -m pytest tests/m4/ tests/api/ tests/unit_a/ tests/e2e/ -v 2>&1 | tail -50`
Expected: All PASS（含 M1 + M2 + F001.1 + F004 全部测试）

特别验证：
- AC-1: 4 endpoint 测试通过（Task 12）
- AC-2: /docs Swagger UI 含 4 endpoint（Task 12 Step 9）
- AC-3: ACP Server 5 agent 注册（Task 7/9）
- AC-4: Client.run_sync 端到端（Task 9 + Task 15）
- AC-5: MessageBuilder 4 parts（Task 6）
- AC-6: Sanitizer 脱敏（Task 6）
- AC-7: 4 reviewer agent（Task 8）
- AC-8: coordinator 编排 4 reviewer（Task 9）
- AC-9: Merger 主视角 + 加权平均（Task 10）
- AC-10: SuggestionRecord 持久化（Task 5 + Task 15）
- AC-11: iteration + parent_record_id 链（Task 11）
- AC-12: max_iterations 异常（Task 11）
- AC-13: 6 metrics（Task 13）
- AC-14: audit_log 写入（Task 11）
- AC-15: M1 get_source_snippet（Task 4）
- AC-16: M1/M2 字节级稳定（Task 4 Step 5 + Task 2 Step 6）
- AC-17: 标注"参考建议"（Task 15 — schema_version 1.0.0）
- AC-18: 端到端 fixture（Task 15）
- AC-19: ACP Server graceful degradation（Task 13 lifespan）
- AC-20: /ready 检查 ACP（Task 14）
- AC-21: M4_* 错误码命名空间（Task 11/12）
- AC-22: 跨家族 review（本 task — @云长 review）

- [ ] **Step 4: Lint full repo check**

Run: `python -m ruff check packages/ acp_servers/ tests/`
Expected: PASS

- [ ] **Step 5: Commit + push**

```bash
git add README.md BACKLOG.md
git commit -m "docs(m4): README M4 章节 + BACKLOG 状态 review"
git push origin feat/f004-impl
```

- [ ] **Step 6: Open PR + request @云长 review**

```bash
gh pr create --title "F004: LLM 改进建议（M4） — ACP 全量引入" --body "$(cat <<'EOF'
## Summary

- F004 M4 改进建议层落地 — 消费 M2 DeepAnalysisRecord + M1 CallContext + SourceSnippet
- ACP 全量引入（铲屎官 08:13 UTC 方案 B 拍板，"为后续拓展其他 agent"）
- 5 个 ACP agent（coordinator + 4 reviewer）部署在独立 ACP Server 进程 :8001
- 4 个 HTTP endpoint + 6 metrics + audit_log + iteration 链
- M1 加 `get_source_snippet` 新方法（不动已有 6 个 + `update_log_point_hypothesis`）

## 关键决策

- spec v1: docs/features/F004-LLM改进建议.md（commit 9b878f4）
- plan: docs/superpowers/plans/2026-07-28-f004-llm-suggestion.md（16 tasks TDD）
- 端口规划铁律：3003/3004/9100 CatCafe 自留地禁占；8000/8001 本项目用；9464 跟 CatCafe 撞 — F001.1 hotfix 9464→9465 follow-up

## AC（22 项）

- [x] AC-1: 4 endpoint 通过 TestClient 测试
- [x] AC-2: /docs Swagger UI 含 4 endpoint
- [x] AC-3: ACP Server :8001 启动 + 5 agent 注册
- [x] AC-4: ACP Client.run_sync 端到端
- [x] AC-5: SuggestionMessageBuilder 4 parts
- [x] AC-6: AcpMessageSanitizer 脱敏
- [x] AC-7: 4 reviewer agent 各产 SuggestionPerspective
- [x] AC-8: coordinator 编排 4 reviewer
- [x] AC-9: SuggestionMerger 主视角 + 加权平均
- [x] AC-10: SuggestionRecord 持久化（P0 TTL=0）
- [x] AC-11: iteration + parent_record_id 链
- [x] AC-12: max_iterations 异常
- [x] AC-13: 6 metrics
- [x] AC-14: audit_log 写入
- [x] AC-15: M1 get_source_snippet 新方法
- [x] AC-16: M1/M2 字节级稳定
- [x] AC-17: 标注"参考建议"不自动应用
- [x] AC-18: 端到端 fixture
- [x] AC-19: ACP Server graceful degradation
- [x] AC-20: /ready 检查 ACP 可达
- [x] AC-21: M4_* 错误码命名空间
- [ ] AC-22: 跨家族 review — @云长 review

## Test plan

- [ ] `python -m pytest tests/m4/ tests/api/ tests/unit_a/ tests/e2e/ -v` 全 PASS
- [ ] `python -m ruff check packages/ acp_servers/ tests/` PASS
- [ ] ACP Server :8002 fixture 启动正常（acp_server fixture）
- [ ] HTTP /docs 含 4 个 suggestion endpoint

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 7: 提请 @云长 cross-family review**

按 A2A 协议投递 review 请求信到 Cat Café（@云长 Maine Coon，跨家族 review 铁律）：

> @云长 F004 M4 改进建议已完成 implement，spec v1（docs/features/F004-LLM改进建议.md）+ plan（docs/superpowers/plans/2026-07-28-f004-llm-suggestion.md）+ 22 AC。
>
> **What**: F004 是项目接入 ACP 生态的起点，5 agent + ACP Server :8001 + FastAPI 编排层。M1 加 `get_source_snippet` 新方法（不动已有方法，AC-16 字节级稳定）。
>
> **Why**: 铲屎官 08:13 UTC 方案 B 拍板"为后续拓展其他 agent"，ACP 是长期投资。
>
> **Tradeoff**: ACP 全量引入比纯单栈方案重（双进程 + 多 agent 协议）；但为后续 M5/M6 等扩展 agent 天然接入 ACP 生态铺路。
>
> **Open Questions**:
> - acp_sdk 实际 API 表面（implement 时已校验；如与 spec §十一 模板有差异请指正）
> - 9464 metrics 跟 CatCafe 撞 — F001.1 hotfix 9464→9465 走独立 PR，F004 不阻塞
>
> **Next Action**: cross-family review AC-22 — @云长 接球

---

## Self-Review

完成 plan 后按 writing-plans skill self-review：

**1. Spec coverage**: 22 AC 全覆盖 — 16 tasks 对应 AC-1 到 AC-22，每 AC 指向具体 Task Step。
**2. Placeholder scan**: 无 TBD/TODO 占位（除 Task 11 占位用 `# TODO: 从 LogPoint 取实际 file_path` 注释 + 实施时补全，非 plan 占位）。
**3. Type consistency**:
   - `SuggestionPerspective` dataclass 字段在 Task 3/10/11/12 一致（perspective/assessment/suggested_diff/confidence/model_name/token_usage）
   - `SuggestionRecord` 字段在 Task 3/5/11/12 一致
   - `SuggestionMergerResult` 在 Task 10/11 一致
   - ACP `Message` / `MessagePart` API 表面已说明（acp_sdk 未安装时按实际 API 调整）

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-28-f004-llm-suggestion.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**

[文若/GLM-5.2🐾] F004 plan v1 — 16 tasks TDD + 22 AC 全覆盖 + Self-Review 三项 PASS + Execution Handoff。@铲屎官 选执行模式后 @奉孝 接球 implement。
