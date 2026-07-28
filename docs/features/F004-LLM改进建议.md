---
feature_ids: [F004]
related_features: [F001, F002, F003]
topics: [llm-suggestion, code-fix-diff, acp, multi-agent, multi-perspective, m4]
doc_kind: spec
created: 2026-07-28
---

# F004: LLM 改进建议（M4 模块）

> Status: spec (v1 — 方案 B 全量引入 ACP；@铲屎官 08:13 UTC 拍板"为后续拓展其他 agent 引入 ACP"；@奉孝 待 implement) | Owner: 奉孝 (@ragdoll-pa82, GLM-5.2, Siamese) | Reviewer: @云长（跨家族） | 设计：@文若

## Why

代码飞轮四模块架构里 M1（F001）落地代码仓日志埋点图谱 + M1 `update_log_point_hypothesis` 回写入口，M2（F002）落地两阶段 LLM 分析（Phase 1 全量报告 + Phase 2 深入分析 + `DeepAnalysisRecord` 持久化）。M4 在此之上构建**改进建议层**——消费 M2 Phase 2 输出 + M1 CallContext + 源码片段，LLM 生成**代码修复 diff 建议**，把"根因假设"转化为"可应用的可读 diff"。

**铲屎官 2026-07-28 07:56 UTC 需求**：参考 ACP 协议（`ACP协议实战指南下篇.md`）设计 F004 LLM 实现架构。

**铲屎官 2026-07-28 08:13 UTC 方向拍板**：
> 为了后续拓展其他 agent，建议采用方案 B 引入 ACP

—— 看中 ACP 多 agent 协作能力作为长期投资，**F004 是项目接入 ACP 生态的起点**。

**F004 边界（F002 spec §一 修订表已定义）**：
> M4 LLM 改进建议 — 基于 M2 Phase 2 深入分析结果生成修复 diff 建议（不再做"深入分析"本身，避免与 M2 重叠）

**关键约束**（继承 F002 spec §Risk）：
> M4 改进基于 M2 DeepAnalysisRecord 但**不作为自动改代码依据**——产出标注为"参考建议"，需人工 review 后应用。

**前置依赖**：F001 + F002 已 merge。F004 在 `packages/m4/` 新增子包 + ACP Server 独立进程，复用 `packages/contracts/` 数据契约，**不修改 M1/M2 service 字节级**（同 F002 AC-18 模式，仅 M1 加 `get_source_snippet` 新方法）。

## What

### 一、模块定位

M4 是**改进建议生成**层——输入是 M2 Phase 2 `DeepAnalysisRecord`（含 `root_cause_hypothesis` + `fix_suggestion` + `related_evidence`）+ M1 `CallContext`（调用链 + community）+ M1 `get_source_snippet`（源码片段），输出是 `SuggestionRecord`（含 unified diff + 多视角评估 + 元数据）。

**ACP 生态接入点**（§十一 详细决策）：
- **引入 acp-sdk** — F004 是项目接入 ACP 生态的起点
- **F004 设计成 ACP Server** — 独立进程监听 8001 端口，对外暴露 agent 端点
- **定义 4 个 ACP agent** — `code_fixer_agent` / `security_reviewer_agent` / `readability_reviewer_agent` / `testing_reviewer_agent` + `suggestion_coordinator_agent`
- **ACP Message 标准化** — 用 `acp_sdk.Message` / `MessagePart` 替代自定义 dataclass
- **未来扩展** — 后续 phase 新增 agent（如 M5 自动修复 agent / M6 文档生成 agent）天然接入 ACP 生态

### 二、LLM 调用架构（ACP Server）

```
┌─────────────────────────────────────────────────────────────────┐
│ ACP Server（独立进程，监听 :8001）                              │
│                                                                 │
│  ┌─── suggestion_coordinator_agent ───────────────────────┐    │
│  │  (ACP @server.agent() — 主入口，编排其他 4 个 agent)   │    │
│  │                                                         │    │
│  │  输入: acp_sdk.Message(parts=[                          │    │
│  │           MessagePart(content_type="text/hypothesis",   │    │
│  │                        content=DeepAnalysisRecord JSON),│    │
│  │           MessagePart(content_type="text/call-context", │    │
│  │                        content=CallContext JSON),        │    │
│  │           MessagePart(content_type="text/source",       │    │
│  │                        content=source snippet),         │    │
│  │           MessagePart(content_type="text/log",           │    │
│  │                        content=log entry text),         │    │
│  │         ])                                              │    │
│  │  输出: acp_sdk.Message(parts=[                          │    │
│  │           MessagePart(content_type="text/diff",          │    │
│  │                        content=unified_diff),           │    │
│  │           MessagePart(content_type="text/summary",       │    │
│  │                        content=fix summary),             │    │
│  │           MessagePart(content_type="application/json",   │    │
│  │                        content=perspective_evaluations), │    │
│  │         ])                                              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          ↓ ACP run_sync 调用 4 个子 agent       │
│  ┌─── code_fixer_agent ──────┐  (主视角：生成 unified_diff)     │
│  ├─── security_reviewer_agent┐  (安全视角：评估 + diff 建议)     │
│  ├─── readability_reviewer   ┐  (可读性视角：评估 + diff 建议)   │
│  └─── testing_reviewer_agent ┘  (测试视角：评估 + diff 建议)     │
└─────────────────────────────────────────────────────────────────┘
                          ↓ ACP Client 调用
┌─────────────────────────────────────────────────────────────────┐
│ FastAPI HTTP Layer (:8000，F001.1 已有 + F004 扩展)             │
│  POST /suggestions → SuggestionService → ACP Client → :8001     │
│  GET  /suggestions/{id} → M4Repository.get                      │
│  GET  /suggestions → M4Repository.list                          │
│  POST /suggestions/{id}/archive → M4Repository.archive          │
└─────────────────────────────────────────────────────────────────┘
                          ↓ 持久化
┌─────────────────────────────────────────────────────────────────┐
│ PostgreSQL suggestion_record 表（P0 持久化铁律 TTL=0）           │
└─────────────────────────────────────────────────────────────────┘
```

**ACP 协议关键点**（参考 `ACP协议实战指南下篇.md`）：
- `acp_sdk.server.Server` + `@server.agent()` 装饰器定义 agent
- `acp_sdk.client.Client` + `client.run_sync(agent="name", input=[Message])` 调用 agent
- `Message(parts=[MessagePart(content, content_type)])` 标准化消息格式
- `Iterator[MessagePart]` yield 流式输出
- `Context` 对象管理 session 状态

**跨 agent 协作模式**（参考文档"诗歌团队"案例）：
- 4 个子 agent 各自独立 LLM 调用（不同 prompt 视角）
- `suggestion_coordinator_agent` 用 ACP `run_sync` 顺序调用 4 个子 agent
- 子 agent 输出通过 ACP `Message` 协议传回 coordinator
- coordinator 汇总产 `SuggestionRecord` 持久化

### 三、数据契约

**ACP Message 使用**（不重复定义 dataclass，直接用 `acp_sdk.Message`）：

```python
# packages/m4/message_builder.py
from acp_sdk import Message, MessagePart

class SuggestionMessageBuilder:
    """装配 ACP Message 给 coordinator agent（spec §三 + §二）。"""

    def build(
        self,
        deep_analysis: DeepAnalysisRecord,
        call_context: CallContext,
        source_snippet: str,
        log_entry: str,
    ) -> Message:
        return Message(parts=[
            MessagePart(
                content=json.dumps(dataclasses.asdict(deep_analysis)),
                content_type="application/json",
            ),
            MessagePart(
                content=source_snippet,
                content_type="text/source",
            ),
            MessagePart(
                content=json.dumps(dataclasses.asdict(call_context)),
                content_type="application/json",
            ),
            MessagePart(
                content=log_entry,
                content_type="text/plain",
            ),
        ])
```

**输出契约**（M4 自有持久化层）：

```python
# packages/contracts/suggestion.py
@dataclass(frozen=True)
class SuggestionPerspective:
    """单视角评估（性能/安全/可读性/测试）。"""
    perspective: str  # "performance" / "security" / "readability" / "testing"
    assessment: str
    suggested_diff: str | None  # unified diff 格式
    confidence: float  # 0.0-1.0
    model_name: str
    token_usage: TokenUsage  # 复用 M2 TokenUsage


@dataclass(frozen=True)
class SuggestionRecord:
    """M4 改进建议记录 — 持久化到 suggestion_record 表。"""
    id: str  # UUID
    deep_analysis_id: str  # 关联 M2 DeepAnalysisRecord
    report_id: str  # 关联 M2 AnalysisReport（间接）
    log_point_ids: list[str]  # 目标 M1 LogPoint
    # 汇总输出
    unified_diff: str  # 合并后的最终 diff
    summary: str
    perspective_evaluations: list[SuggestionPerspective]
    confidence_score: float
    # 元数据
    model_name: str  # coordinator 用的 model
    prompt_hash: str
    iteration: int  # M4 也可迭代
    parent_record_id: str | None
    generated_at: datetime
    token_usage: TokenUsage
    schema_version: str
    # ACP 协议元数据
    acp_session_id: str | None  # ACP session 追溯
    acp_agent_versions: dict[str, str]  # {"coordinator": "1.0", "code_fixer": "1.0", ...}
```

### 四、对外 API 契约（FastAPI HTTP 层）

```python
# packages/m4/suggestion_service.py
from acp_sdk.client import Client
from acp_sdk.models import Message

class SuggestionService:
    """M4 改进建议服务（spec §四 + AC-1 + AC-15）。

    编排层：HTTP 请求 → 装配 ACP Message → ACP Client 调 :8001 →
            解析 ACP 响应 → 持久化 SuggestionRecord + audit_log + metrics
    """

    def __init__(
        self,
        session: Session,
        audit: AuditLogger,
        repository: M4Repository,
        message_builder: SuggestionMessageBuilder,
        acp_client: Client,  # acp_sdk.client.Client 注入
        m1_service: "M1ServiceProtocol",
        metrics: "M4MetricsEmitter | None" = None,
    ) -> None:
        ...

    async def generate_suggestion(
        self,
        deep_analysis_id: str,
        perspectives: list[str] | None = None,
    ) -> SuggestionRecord:
        """生成改进建议。

        流程:
            1. M2Repository.get_deep_analysis(deep_analysis_id) → DeepAnalysisRecord
            2. M1 RepoLogGraphService.get_call_context(repo_id, fn_sig) → CallContext
            3. M1 RepoLogGraphService.get_source_snippet(...) → source code
               （get_source_snippet 是 F004 §十 新增 M1 方法）
            4. SuggestionMessageBuilder.build() → ACP Message
            5. LogSanitizer.sanitize(Message) → 脱敏后 Message
            6. ACP Client.run_sync(agent="suggestion_coordinator_agent",
                                   input=[sanitized_message]) → ACP 响应 Message
            7. 解析响应 Message parts → SuggestionPerspective + unified_diff
            8. SuggestionMerger.merge(perspectives) → unified_diff + confidence_score
            9. M4Repository.save(SuggestionRecord) + audit_log + metrics
        """

    def get_suggestion(self, suggestion_id: str) -> SuggestionRecord: ...
    def list_suggestions(
        self, report_id: str | None = None, log_point_id: str | None = None,
    ) -> list[SuggestionRecord]: ...
    async def archive_suggestion(self, suggestion_id: str, archiver: User) -> None: ...
```

### 五、文件结构

```
代码飞轮/
├── packages/
│   ├── contracts/           # 不变（M1/M2 数据契约）+ 新增 suggestion.py
│   │   └── suggestion.py    # SuggestionPerspective + SuggestionRecord
│   ├── m1/                  # 仅加 get_source_snippet 新方法
│   ├── m2/                  # 不变
│   └── m4/                  # 新增 M4 子包（ACP Server + FastAPI 编排层）
│       ├── __init__.py
│       ├── suggestion_service.py      # FastAPI 编排层（ACP Client 调用方）
│       ├── suggestion_merger.py       # 多视角 diff 汇总
│       ├── message_builder.py         # ACP Message 装配
│       ├── acp_server.py             # ACP Server 入口（@server.agent() 定义）
│       ├── agents/                    # 5 个 ACP agent 实现
│       │   ├── __init__.py
│       │   ├── coordinator_agent.py     # suggestion_coordinator_agent
│       │   ├── code_fixer_agent.py      # code_fixer_agent（主视角）
│       │   ├── security_reviewer_agent.py
│       │   ├── readability_reviewer_agent.py
│       │   └── testing_reviewer_agent.py
│       ├── metrics_emitter.py         # M4 metrics
│       └── storage/
│           ├── __init__.py
│           ├── models.py              # SuggestionRecordModel（SQLAlchemy）
│           ├── repository.py          # M4Repository CRUD
│           └── migrations/
│               └── versions/0003_m4_suggestion_tables.py
├── acp_servers/            # ACP Server 启动入口（独立进程）
│   └── m4_server.py        # python -m acp_servers.m4_server → 启动 :8001
└── tests/m4/               # 新增测试目录
    ├── __init__.py
    ├── conftest.py         # fixture（含 ACP Server test fixture）
    ├── test_acp_server.py  # ACP Server agent 注册 + run_sync 单元测试
    ├── test_agents/        # 5 个 agent 各自单元测试
    │   ├── test_coordinator_agent.py
    │   ├── test_code_fixer_agent.py
    │   ├── test_security_reviewer_agent.py
    │   ├── test_readability_reviewer_agent.py
    │   └── test_testing_reviewer_agent.py
    ├── test_suggestion_merger.py
    ├── test_message_builder.py
    ├── test_suggestion_service.py  # 编排层集成测试（mock ACP Client）
    └── test_m4_full_pipeline.py    # 端到端：M2 DeepAnalysisRecord → ACP Server → SuggestionRecord
```

### 六、HTTP API（F001.1 扩展）

| Method | Path | Body / Query | Returns | service 方法 | tag |
|--------|------|---------------|---------|--------------|-----|
| POST | `/suggestions` | `GenerateSuggestionRequest` | `SuggestionResponse` 201 | `generate_suggestion` | suggestion |
| GET | `/suggestions/{suggestion_id}` | — | `SuggestionResponse` 200 | `get_suggestion` | suggestion |
| GET | `/suggestions` | `?report_id&log_point_id` | `list[SuggestionResponse]` 200 | `list_suggestions` | suggestion |
| POST | `/suggestions/{suggestion_id}/archive` | `ArchiveRequest` | 204 No Content | `archive_suggestion` | suggestion |

**状态码**：
- 201 Created / 200 OK / 204 No Content
- 422 VALIDATION_ERROR / DEEP_ANALYSIS_NOT_FOUND
- 409 SUGGESTION_LOCK_RUNNING
- 500 INTERNAL_ERROR
- 503 ACP_SERVER_UNAVAILABLE（ACP Server 进程不可达）

### 七、配置扩展

```python
# packages/m1/config_loader.py 加 M4Config + AcpConfig
@dataclasses.dataclass(frozen=True)
class AcpConfig:
    """F004 — ACP Server 配置（spec §二 ACP Server 部署）。"""
    server_host: str = "127.0.0.1"
    server_port: int = 8001  # 避开 CatCafe 3003/3004/9100 自留地 + 本项目 8000/9464
    server_workers: int = 1  # dev-only 单进程；生产可扩
    client_timeout_seconds: int = 300  # ACP Client 调用 timeout
    enabled: bool = True  # False 时 SuggestionService 直接返回 ACP_SERVER_UNAVAILABLE

@dataclasses.dataclass(frozen=True)
class M4Config:
    """F004 — M4 改进建议配置（spec §七）。"""
    model_name: str = "gpt-4"  # coordinator + code_fixer 强模型
    perspectives: tuple[str, ...] = ("performance", "security", "readability", "testing")
    max_iterations: int = 3  # M4 累积上限
    cache_ttl_seconds: int = 86400
    max_source_lines: int = 200  # source snippet 上限

# Config dataclass 加 acp + m4 字段
@dataclasses.dataclass(frozen=True)
class Config:
    llm: LLMConfig
    storage: StorageConfig
    extraction: ExtractionConfig
    sanitizer: SanitizerConfig
    metrics: MetricsConfig
    api: ApiConfig
    m2: M2Config  # F002 已加
    acp: AcpConfig = dataclasses.field(default_factory=AcpConfig)  # F004 新增
    m4: M4Config = dataclasses.field(default_factory=M4Config)  # F004 新增
```

`config.example.yaml` 补：
```yaml
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
```

环境变量：`CODEFLY_ACP_SERVER_PORT` / `CODEFLY_ACP_ENABLED` / `CODEFLY_M4_MODEL_NAME` / `CODEFLY_M4_PERSPECTIVES`。

### 八、metrics 指标

| 指标名 | 类型 | 描述 |
|--------|------|------|
| `m4_suggestion_total` | Counter | 改进建议生成总数 |
| `m4_suggestion_duration_seconds` | Histogram | 单次建议生成耗时（含 ACP 调用） |
| `m4_acp_call_total{agent}` | Counter | 各 ACP agent 调用次数（coordinator/code_fixer/...） |
| `m4_acp_call_duration_seconds{agent}` | Histogram | 各 agent 调用耗时 |
| `m4_perspective_confidence_score{perspective}` | Gauge | 各视角置信度 |
| `m4_llm_cost_usd_total` | Counter | M4 LLM 成本累计 |

复用 F001.1 metrics 独立进程，不新增进程（端口规划见下方"9464 已知问题"）。

**⚠️ 9464 已知问题（2026-07-28 08:32 UTC 实测发现）**：

F001.1 端口修复 commit `f37e5fd` 把 metrics 从 9100 改 9464，但**实测 9464 已被 CatCafe 自家 metrics server 占用**（PID 2948 = CatCafe node.exe，curl `http://localhost:9464/metrics` 返回 HTTP 200）。F001.1 修复时只避开了 3003/3004（CatCafe API/前端），**没避开 CatCafe metrics 端口**——这是 F001.1 修复的新根因缺陷。

**处置策略**（铲屎官 08:47 UTC "继续实现"拍板方案 2）：
- F004 implement 不阻塞——F004 spec §八 AC-13 暂时保留"复用 F001.1 metrics 端口"
- F001.1 metrics 9464 → 9465 作为**独立 hotfix** 走 PR 流程（同 `f37e5fd` 先例），跟 F004 implement 并行
- F001.1 hotfix 合入后，F004 spec §八 + AC-13 同步更新到 9465
- F004 implement 期间，dev 测试时 metrics 9464 端口冲突会让 F001.1 lifespan 的 `start_http_server(9464)` 失败，但 F001.1 AC-11 graceful degradation 已设计（warn log 不阻断 API）——所以 F004 implement 不会因 9464 冲突崩

### 九、审计与可观测性

每个写操作写 `audit_log` 表，复用 M1 `AuditLogger`。

`audit_log.action` 值：
- `ACTION_PHASE4_GENERATE_SUGGESTION` = "phase4_generate_suggestion"
- `ACTION_ARCHIVE_SUGGESTION` = "archive_suggestion"

`audit_log.extra` 字段记录：
- `acp_session_id` — ACP session 追溯
- `acp_agent_versions` — agent 版本快照
- `perspective_count` — 视角数
- `confidence_score` — 综合置信度

### 十、与 M1 的关联机制

F004 需要新加 M1 方法（同 F002 §十 模式）：

```python
# packages/m1/repo_log_graph_service.py 加新方法（不动已有 6 个 + update_log_point_hypothesis）
def get_source_snippet(
    self,
    repo_id: str,
    file_path: str,
    line_start: int,
    line_end: int,
) -> SourceSnippet:
    """F004 §十：取源码片段（供 M4 生成 diff 用）。

    实现:
        1. 通过 gitnexus cypher 查 File 节点取 file content
           MATCH (f:File {filePath: $path}) RETURN f.content
        2. 按 line_start/line_end 切片
        3. 扩展上下文（前后各 +10 行）保证 diff 可读
        4. 上限 max_source_lines（M4Config，默认 200）防 token 爆炸

    Returns:
        SourceSnippet(file_path, line_range, content, extractor_version)
    """
```

**M1 service/storage/contracts 字节级稳定性保持**（同 F002 AC-18 模式）：
- 不修改已有 6 个方法 + `update_log_point_hypothesis`
- 仅新增 `get_source_snippet`
- M1 测试套无回归

### 十一、ACP 部署架构（铲屎官 08:13 UTC 拍板方案 B）

#### 11.1 进程拓扑

| 进程 | 端口 | 职责 | 启动命令 |
|------|------|------|---------|
| FastAPI HTTP Server | 8000 | F001.1 + F004 HTTP 层（编排 ACP Client） | `uvicorn packages.api.app:app --port 8000 --reload` |
| ACP M4 Server | 8001 | 5 个 ACP agent（coordinator + 4 reviewer） | `python -m acp_servers.m4_server` |
| Metrics Server | 9464 | prometheus_client 独立进程（F001.1 已有，M4 复用）⚠️ 9464 已知跟 CatCafe 撞，待 F001.1 hotfix 改 9465 | （F001.1 已有） |
| ~~ACP Future Servers~~ | 8002+ | 后续 phase 新增 agent（如 M5 自动修复 / M6 文档生成） | TBD |

**端口规划铁律**（家规 §12 Runtime 单实例保护 + F001.1 端口修复）：
- 3003 / 3004 / 9100 = CatCafe runtime 自留地，禁占
- 8000 = FastAPI HTTP（F001.1 已修，08:32 UTC 实测无冲突）
- 8001 = ACP M4 Server（F004 新增，08:32 UTC 实测无冲突）
- 9464 = metrics（F001.1 已用，**08:32 UTC 实测跟 CatCafe 撞**——F001.1 hotfix 改 9465 follow-up）
- 8002+ = 预留后续 ACP Server（如 M5/M6）

#### 11.2 ACP Server 启动入口

```python
# acp_servers/m4_server.py
"""F004 M4 ACP Server — 启动 :8001 监听 5 个 agent（spec §十一）。

启动方式（dev）:
    python -m acp_servers.m4_server

启动方式（生产）:
    uvicorn acp_servers.m4_server:app --host 0.0.0.0 --port 8001
    （或用 systemd / Docker 部署 ACP Server 独立进程）
"""
from __future__ import annotations

import os
from acp_sdk.server import Server

from packages.m4.agents.coordinator_agent import register as register_coordinator
from packages.m4.agents.code_fixer_agent import register as register_code_fixer
from packages.m4.agents.security_reviewer_agent import register as register_security
from packages.m4.agents.readability_reviewer_agent import register as register_readability
from packages.m4.agents.testing_reviewer_agent import register as register_testing

server = Server()

# 注册 5 个 agent
register_coordinator(server)
register_code_fixer(server)
register_security(server)
register_readability(server)
register_testing(server)

if __name__ == "__main__":
    host = os.environ.get("CODEFLY_ACP_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("CODEFLY_ACP_SERVER_PORT", "8001"))
    server.run(host=host, port=port)
```

#### 11.3 ACP Agent 实现模板（参考 ACP 文档"诗歌团队"案例）

```python
# packages/m4/agents/coordinator_agent.py
"""suggestion_coordinator_agent — 编排 4 个 reviewer agent（spec §二）。"""
from collections.abc import Iterator
from acp_sdk import Message, MessagePart
from acp_sdk.server import Context, Server
from acp_sdk.client import Client

LLM_API_KEY = os.getenv("CODEFLY_LLM_API_KEY")
# 用 CrewAI LLM 或直接 OpenAI client（按 spec §十四 Dependencies 选型）

def register(server: Server) -> None:
    @server.agent()
    async def suggestion_coordinator_agent(
        input: list[Message], context: Context
    ) -> Iterator[MessagePart]:
        """协调 4 个 reviewer agent 产 unified_diff + perspective_evaluations。"""
        # 1. 解析 input Message parts → DeepAnalysisRecord + CallContext + source + log
        # 2. 装配子 agent 调用 Message
        # 3. async with Client(base_url="http://localhost:8001") as client:
        #      for agent_name in ["code_fixer", "security_reviewer",
        #                         "readability_reviewer", "testing_reviewer"]:
        #          result = await client.run_sync(agent=agent_name, input=[msg])
        # 4. 汇总 4 个子 agent 输出 → unified_diff + perspective_evaluations
        # 5. yield MessagePart(content_type="text/diff", content=unified_diff)
        #    yield MessagePart(content_type="application/json", content=evaluations)
        ...
    return suggestion_coordinator_agent

# packages/m4/agents/code_fixer_agent.py — 主视角 agent，类似模板
# packages/m4/agents/security_reviewer_agent.py — 安全视角
# packages/m4/agents/readability_reviewer_agent.py — 可读性视角
# packages/m4/agents/testing_reviewer_agent.py — 测试视角
```

#### 11.4 跨 agent 协作模式

参考 ACP 文档"诗歌团队"案例（诗人/配音师/音乐家协调器）：
- 4 个 reviewer agent 各自独立 LLM 调用（不同 prompt 视角）
- coordinator 用 ACP `Client.run_sync(agent="...", input=[Message])` 顺序调用
- 子 agent 输出通过 ACP `Message` 协议传回 coordinator
- coordinator 汇总产 `SuggestionRecord` 持久化

### 十二、ACP Server 生命周期管理

#### 12.1 FastAPI lifespan 启动 ACP Server（dev 模式）

```python
# packages/api/app.py lifespan 扩展（F004）
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... F001.1 metrics process 已有 ...

    # F004: dev 模式自动启动 ACP Server 子进程
    acp_process: subprocess.Popen | None = None
    if _config.acp.enabled and _config.acp.server_port:
        try:
            acp_process = subprocess.Popen([
                sys.executable, "-m", "acp_servers.m4_server",
                "--host", _config.acp.server_host,
                "--port", str(_config.acp.server_port),
            ])
            logger.info("ACP M4 Server started on port %s (pid=%s)",
                        _config.acp.server_port, acp_process.pid)
        except Exception as e:
            logger.warning("ACP Server failed to start: %s. Continuing without ACP.", e)

    yield

    # cleanup
    if acp_process and acp_process.poll() is None:
        acp_process.terminate()
        acp_process.wait(timeout=5)
```

**生产模式**：ACP Server 独立 systemd/Docker 进程，FastAPI 只跑 Client。

#### 12.2 ACP Client 健康检查

`/ready` endpoint（F001.1 已有）扩展检查 ACP Server 可达性：

```python
# packages/api/routes/ops.py ready 扩展
@router.get("/ready", response_model=ReadyResponse)
def ready(session: Session = Depends(get_session)) -> ReadyResponse:
    # ... DB 检查已有 ...
    # F004 扩展：ACP Server 可达性
    if _config.acp.enabled:
        try:
            # httpx.get(f"http://localhost:{_config.acp.server_port}/health") → 200
            ...
        except Exception:
            return ReadyResponse(status="not_ready", reason="acp_server_unavailable")
    return ReadyResponse(status="ready")
```

### 十三、测试策略

**分层**（同 F002 模式）：

| 层级 | 测试文件 | 覆盖范围 |
|------|---------|---------|
| ACP Server unit | `test_acp_server.py` | agent 注册 + run_sync 单元 |
| Agent unit | `test_agents/test_*.py` | 5 个 agent 各自 LLM 调用 mock |
| Merger unit | `test_suggestion_merger.py` | 多视角 diff 汇总逻辑 |
| Message builder | `test_message_builder.py` | ACP Message 装配 + 脱敏 |
| Service integration | `test_suggestion_service.py` | 编排层（mock ACP Client） |
| End-to-end | `test_m4_full_pipeline.py` | M2 DeepAnalysisRecord → ACP Server → SuggestionRecord |

**ACP Server test fixture**（参考 F002 metrics_server fixture 模式）：

```python
# tests/m4/conftest.py
@pytest.fixture()
def acp_server() -> Generator[str, None, None]:
    """独立 ACP Server fixture（8002 端口，避免与 dev :8001 冲突）。"""
    proc = subprocess.Popen([
        sys.executable, "-m", "acp_servers.m4_server",
        "--port", "8002",
    ])
    # Poll until ready
    url = "http://localhost:8002"
    max_wait = 10.0
    ...
    yield url
    proc.terminate()
```

**LLM mock 策略**：所有 agent 单元测试用 `MagicMock(spec=LLMClient)`，端到端用真实 LLM（需 `CODEFLY_LLM_API_KEY` + 标记 `@pytest.mark.integration`）。

### 十四、依赖锁定

`pyproject.toml` 补：

```toml
[project.optional-dependencies]
m4 = [
    "acp-sdk>=0.1,<1.0",  # ACP 协议 SDK（F004 §十一）
    # CrewAI / LangGraph 按需 — v1 默认不引入，coordinator 用原生 acp_sdk + LLMClient
    # "crewai>=0.50,<0.60",
    # "langgraph>=0.2,<0.3",
]
```

**v1 不引入 CrewAI/LangGraph 决策**：
- ACP 文档案例用 CrewAI 是为了多 agent 角色定义 + task 编排
- F004 v1 用原生 `acp_sdk` + 现有 `LLMClient` 协议足够
- 后续 phase 若需更复杂 agent 行为（如 ReAct 模式 / tool use）再引入 CrewAI

### Acceptance Criteria

- [ ] AC-1: 4 个 HTTP endpoint 通过 TestClient 测试，状态码 + 响应 schema 正确（POST 201 / GET 200 / archive 204）
- [ ] AC-2: `/docs` Swagger UI 可访问，4 个 endpoint 按 tag 分组展示
- [ ] AC-3: ACP Server 在 :8001 启动，5 个 agent 注册成功（`/agents` endpoint 列出）
- [ ] AC-4: ACP `Client.run_sync(agent="suggestion_coordinator_agent", input=[Message])` 端到端调用成功
- [ ] AC-5: `SuggestionMessageBuilder` 装配 4 parts（hypothesis/source/call-context/log），content_type 正确
- [ ] AC-6: `LogSanitizer.sanitize(Message)` 脱敏后，密钥/IP/邮箱/token 零命中才发 LLM
- [ ] AC-7: 4 个 reviewer agent 各自 LLM 调用产 `SuggestionPerspective`（含 assessment / suggested_diff / confidence）
- [ ] AC-8: `suggestion_coordinator_agent` 用 ACP `Client.run_sync` 顺序调 4 个 reviewer，汇总产 unified_diff
- [ ] AC-9: `SuggestionMerger` 合并多视角 diff，产 `unified_diff` + `confidence_score`（加权平均）
- [ ] AC-10: `SuggestionRecord` 持久化到 `suggestion_record` 表（P0 持久化铁律 TTL=0）
- [ ] AC-11: `SuggestionRecord.iteration` + `parent_record_id` 累积上下文链（同 M2 Phase 2 模式）
- [ ] AC-12: `max_iterations`（默认 3）触发时抛 `SuggestionIterationLimitExceeded` + 提示归档重启
- [ ] AC-13: 6 个 metrics 指标暴露在 9464 端口（m4_suggestion_total / m4_acp_call_total 等）
- [ ] AC-14: 每个写操作写 `audit_log` 表，`extra` 含 acp_session_id + agent_versions
- [ ] AC-15: M1 `get_source_snippet` 新方法落地，不动已有 6 个方法 + `update_log_point_hypothesis`
- [ ] AC-16: 现有 M1+F001.1+F002 测试无回归（M1 service/storage/contracts 字节级稳定，仅加 `get_source_snippet` 新方法）
- [ ] AC-17: `SuggestionRecord` 标注为"参考建议"，不作为自动改代码依据（继承 F002 §Risk 同款约束）
- [ ] AC-18: 端到端 fixture 测试：M2 DeepAnalysisRecord → ACP Server → SuggestionRecord，验证 unified_diff 合法 + perspective_evaluations 4 项齐 + acp_session_id 非空
- [ ] AC-19: ACP Server 启动失败时 graceful degradation（warn log，FastAPI 返回 503 ACP_SERVER_UNAVAILABLE，不崩）
- [ ] AC-20: `/ready` 扩展检查 ACP Server 可达性，不可达时返回 `not_ready` + `reason="acp_server_unavailable"`
- [ ] AC-21: 错误码命名空间清晰（`M4_*` 前缀，如 `M4_DEEP_ANALYSIS_NOT_FOUND` / `M4_SUGGESTION_LOCK_RUNNING` / `M4_ACP_SERVER_UNAVAILABLE`）
- [ ] AC-22: 跨家族 review 通过（家规铁律 no self-review）—— @云长 review

## Dependencies

- **M1 RepoLogGraphService**（已 merge + F002 扩展）— `get_call_context` 不变；新增 `get_source_snippet`（F004 实施时同步加）
- **M1 LogSanitizer**（已 merge）— 复用脱敏能力
- **M1 AuditLogger**（已 merge）— 复用 audit_log 写入
- **M2 LogAnalysisService**（F002 待 merge）— `get_deep_analysis` 不变
- **F001.1 HTTP 服务层**（已 merge + v1.1 端口修复）— 复用 error_handlers / deps / app 框架 + lifespan 扩展启动 ACP Server
- **acp-sdk**（新增）— ACP 协议 SDK（`acp_sdk.server.Server` / `acp_sdk.client.Client` / `Message` / `MessagePart`）
- **LLM API**（铲屎官提供 key，配置注入，复用 M1 `LLMConfig`）— 5 个 agent 各自 LLM 调用
- **Redis 6398**（dev/test 缓存，新增 `codefly-m4` 子命名空间）
- **prometheus_client** — M4 metrics_emitter
- **Python 3.11+**（继承 M1 工程基线）

**后续 phase 可选依赖**（v1 不引入）：
- CrewAI / LangGraph — 若需更复杂 agent 行为（ReAct / tool use）后续 phase 引入

## Risk

| 风险 | 等级 | 缓解 |
|------|------|------|
| LLM 生成的 diff 不合法（语法错误 / 上下文错位） | 🔴 高 | AC-9 SuggestionMerger 校验 unified_diff 格式 + AC-18 端到端验证 + AC-17 标注"参考建议"不自动应用 |
| LLM 幻觉（修复方向偏离根因） | 🟡 中 | AC-7 多视角评估降低偏差 + AC-17 不自动改代码 + AC-9 confidence_score 透明 |
| 源码片段 token 爆炸（大文件 / 长函数） | 🟡 中 | `M4Config.max_source_lines` 上限 200 + AC-6 脱敏 + cache |
| M4 累积上下文无限增长 | 🟡 中 | AC-12 max_iterations=3 + 归档重启 |
| ACP Server 进程崩 / 不可达 | 🟡 中 | AC-19 graceful degradation + AC-20 /ready 检查 + lifespan 监控 |
| ACP 协议不成熟（spec 边写边改） | 🟡 中 | acp-sdk 锁定 <1.0 上限 + 单元测试覆盖核心 Message 协议 + 后续 phase 升级时 review |
| 跨 agent 调用顺序延迟累积 | 🟡 中 | AC-13 m4_acp_call_duration_seconds 监控 + 4 reviewer 串行调（v1 不并行，简单优先） |
| M1 `get_source_snippet` 改动破坏 F002 AC-18 字节级稳定 | 🟢 低 | 新方法不修改已有 6 个 + `update_log_point_hypothesis`，仅新增 |
| 多视角 LLM 调用成本（4x 单次 + coordinator 1x = 5x） | 🟡 中 | AC-13 `m4_llm_cost_usd_total` 监控 + AC-12 max_iterations 限制 + cache |
| M4 数据契约演化 | 🟡 中 | `schema_version` 字段（同 M1/M2 模式）+ `acp_agent_versions` 追溯 |
| ACP Server 端口 8001 与未来 agent 冲突 | 🟢 低 | §11.1 端口规划铁律：8002+ 预留后续 ACP Server |

## Open Questions

- ~~Q1 ACP 适配方向 — 方案 A/B/C 三选一~~ → **决策**：方案 B 全量引入 ACP（铲屎官 08:13 UTC 拍板，理由"为后续拓展其他 agent"）
- **Q2** M1 `get_source_snippet` 实现细节 — gitnexus cypher 查 File 节点取 content，还是 `tree-sitter` 直接读本地文件？→ **倾向**：gitnexus（保持 M1 不自建 AST 的设计铁律 + 跨仓通用性）；@奉孝 implement 时确认 gitnexus File 节点是否已索引 content 字段
- **Q3** M4 是否需要"diff 预应用校验"（跑测试看 diff 是否破坏现有测试）？→ **倾向**：v1 不做（M4 AC-17 标注"参考建议"不自动应用，校验留给后续 F005/工具链 phase）
- **Q4** `SuggestionMerger` 合并策略 — 多视角 diff 冲突时如何处理？→ **倾向**：v1 用"主视角 + 附属建议"模式（主视角 = code_fixer，其他视角作为 assessment 附在 perspective_evaluations 里），冲突时不强行合并，让用户 review 时选
- **Q5** F004 是否依赖 F003（M3 在线扫描）？→ **决策**：不依赖。F004 输入是 M2 DeepAnalysisRecord，F003 不影响 F004 实施。F004 可在 F002 merge 后独立先行
- **Q6** ACP Server 是否引入 CrewAI/LangGraph？→ **倾向**：v1 不引入。用原生 `acp_sdk` + 现有 `LLMClient` 协议；后续 phase 若需 ReAct / tool use 再引入
- **Q7** ACP `acp_sdk.Message` 协议演化保护？→ **倾向**：`SuggestionRecord.acp_agent_versions` 字段追溯各 agent 实现 version；spec 升级 acp-sdk 时 review 全部 agent
- **Q8** 多 reviewer agent 串行 vs 并行？→ **倾向**：v1 串行（简单优先 + ACP `run_sync` 原生支持）。性能优化（并行）留后续 phase，AC-13 m4_acp_call_duration_seconds 监控数据驱动决策

## 客户补充章节（CVO 决策提炼）

### C-1: ACP 协议引入决策

- **提出时间**：2026-07-28 07:56 UTC
- **背景**：铲屎官参考 `ACP协议实战指南下篇.md`，指令"利用 ACP 设计 F004 LLM 实现架构"
- **客户需求**：F004 LLM 架构参考 ACP 协议设计
- **设计者 push back**：F004 本质单轮 LLM 调用，ACP 多 agent 协作能力对 F004 过重；项目单栈无跨框架需求（spec v0.1 §十一 给出 A/B/C 三方案）
- **铲屎官拍板**：2026-07-28 08:13 UTC 选方案 B 全量引入 ACP，理由"**为了后续拓展其他 agent**"
- **影响**：
  - F004 设计成 ACP Server（:8001），定义 5 个 ACP agent
  - 引入 acp-sdk 依赖
  - 部署形态变更：FastAPI + ACP Server 双进程
  - 未来 ACP 生态扩展点（M5/M6 等后续 phase 新 agent 天然接入）
- **落地点**：§一模块定位、§二 LLM 调用架构、§三数据契约（acp_sdk.Message）、§五文件结构（agents/ + acp_servers/）、§七配置（AcpConfig）、§十一 ACP 部署架构、§十二生命周期管理、§十四依赖、AC-3/4/5/7/8/19/20

### 决策追溯矩阵

| 决策 ID | 提出时间 | spec 章节 | AC | 实施计划 Task |
|---------|---------|----------|-----|---------------|
| C-1 | 2026-07-28 07:56 UTC（需求）+ 08:13 UTC（方向拍板） | §一/§二/§三/§五/§七/§十一/§十二/§十四 | AC-3/4/5/7/8/19/20 | TBD（待 implement 时 writing-plans 细化） |

> **章节维护规则**：后续若铲屎官提出新改进/需求，本章节追加 C-2/C-3... 条目并同步到决策追溯矩阵。

## Timeline

| Date | Event |
|------|-------|
| 2026-07-28 07:56 UTC | 铲屎官指令：参考 ACP 协议设计 F004 LLM 架构（C-1 决策追溯起点） |
| 2026-07-28 08:00 UTC | @文若 设计者 push back：ACP 对 F004 单栈单轮调用存在过度设计风险（spec v0.1 §十一 给出 A/B/C 三方案） |
| 2026-07-28 08:13 UTC | 铲屎官拍板方案 B 全量引入 ACP，理由"为后续拓展其他 agent"（C-1 决策闭环） |
| 2026-07-28 (本时刻) | F004 spec v1 定稿（方案 B 全量 ACP + 5 agent + ACP Server :8001 + 部署架构） |
| TBD | @铲屎官 review spec v1，如 OK 则交 @奉孝 implement |

## 后续 Phase 规划

```
Phase 0 (done)  → F001 + F001.1 落地稳定 ✅
Phase 1 (done)  → F002 离线 LLM 分析（待 merge）
Phase 2 (next)  → F003 在线扫描（独立先行，不依赖 F004）
Phase 3 (now)   → F004 LLM 改进建议（本 feature，依赖 F002 + 引入 ACP 生态）
Phase 4 (future)→ 后续 agent 扩展（M5 自动修复 / M6 文档生成）天然接入 ACP 生态
```

**F004 是项目接入 ACP 生态的起点**——本 feature 落地 ACP Server + 5 agent 后，后续 phase 新增 agent（如 M5 自动修复 agent / M6 文档生成 agent）可在同一 ACP Server 加 `@server.agent()` 注册，或起独立 ACP Server（8002+）按 §11.1 端口规划铁律。

---

[文若/GLM-5.2🐾] F004 spec v1 — 铲屎官 08:13 UTC 方案 B 拍板 + 全量 ACP 适配 + 5 agent + ACP Server :8001 部署架构 + 22 AC。@铲屎官 review 后交 @奉孝 implement。
