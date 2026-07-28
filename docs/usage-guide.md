---
feature_ids: [F001, F001.1]
related_features: [F002, F003, F004]
topics: [user-guide, usage, api, http, setup]
doc_kind: guide
created: 2026-07-27
---

# 代码飞轮 — 当前实现功能使用指导

> 范围：main 分支已落地的功能（F001 代码仓日志解析 + F001.1 HTTP 服务层）。F002 离线 LLM 分析在 `feat/f002-impl` 分支等 merge，不在本指导范围。
> 更新时间：2026-07-27 12:35 UTC

---

## 0. 一句话理解

代码飞轮现在能做的事：**给你一个代码仓的 URL 或本地路径，跑一遍 ingest，它会用 gitnexus 建图 + tree-sitter 解析 AST + LLM 推断"这里为什么打这条日志"，把候选 LogPoint 推到候选池让你勾选入库**。勾完的 LogPoint 是后续 M2 离线分析 / M3 在线扫描 / M4 改进建议的查询底座。

---

## 1. 前置依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+（spec §Dependencies 硬约束，代码大量用 `from datetime import UTC`） | 运行时 |
| PostgreSQL | 任意可用版本 | LogPoint 主表 + audit_log + repo_ingest_lock（dev/test 也可用 SQLite `:memory:`） |
| Redis | 6398 端口（dev/test） | LLM 调用缓存 + 节流；**禁用 6399**（CatCafe production Redis，家规铁律） |
| gitnexus MCP server | 任可用版本 | graph backend（Unit A 建图 + Unit B cypher 粗筛 + Unit C 调用链查询） |
| LLM API | OpenAI 风格 endpoint | 推断"打印原因"假设（生产需自备 key） |

**家规铁律**：
- 端口 3003/3004/9100 是 CatCafe runtime 自留地，外部项目禁占——本项目 API 用 **8000**，metrics 用 **9464**
- Redis 6399 是 CatCafe production Redis，禁连——本项目 dev 用 **6398**

---

## 2. 安装

```bash
# clone 仓库
git clone https://github.com/StackTony/code-log-analyze.git
cd code-log-analyze

# 安装依赖（含 api + dev extras）
pip install -e ".[api,dev]"
```

---

## 3. 配置

### 3.1 复制配置模板

```bash
cp config.example.yaml config.local.yaml
```

`config.local.yaml` 在 `.gitignore` 里，不会被提交——你的 API key / DSN 在这里改。

### 3.2 必填环境变量

```bash
# LLM API key（OpenAI 风格 endpoint 都行，不一定是 OpenAI 自己）
export CODEFLY_LLM_API_KEY=sk-xxxxxxxxxxxxxxxx

# PostgreSQL DSN（生产用；dev/test 用 SQLite 可不设）
export CODEFLY_PG_DSN=postgresql://user:pass@localhost:5432/codefly
```

### 3.3 关键配置项（`config.local.yaml`）

```yaml
llm:
  api_key: ${CODEFLY_LLM_API_KEY}
  model_name: gpt-4           # Unit C LLM 推断用的模型
  endpoint: https://api.openai.com/v1
  batch_size: 20              # 批量调 LLM 的批大小
  max_retries: 3

storage:
  postgres_dsn: ${CODEFLY_PG_DSN}
  redis_port: 6398            # ⚠️ 禁用 6399（CatCafe production Redis）
  redis_namespace: codefly-m1

extraction:
  top_n_candidates: 50        # 候选池保留前 N 高频
  include_print: false         # 是否识别裸 print()（默认 false）
  ingest_timeout_minutes: 30   # running 锁心跳超时阈值
  candidate_ttl_days: 30       # 候选池未确认 LogPoint 清理 TTL
  extractor_version: "1.0.0"   # 升级时旧 LLM 缓存自动失效

sanitizer:
  enabled: true
  patterns: [api_key, password, token, ipv4, ipv6, email]
  replacement: "[REDACTED_{kind}]"

metrics:
  port: 9464                  # ⚠️ 避开 CatCafe runtime 9100

api:
  host: "127.0.0.1"
  port: 8000                  # ⚠️ 避开 CatCafe runtime 3003/3004
  enable_auth: false          # dev-only，启动时 console 会警告
  cors_origins: ["http://localhost:3003"]
```

---

## 4. 启动服务

### 4.1 正确启动命令

```bash
# 用 uvicorn 启动（推荐，dev-only）
uvicorn packages.api.app:app --port 8000 --reload
```

> ✅ **README 同步**：`README.md` 已删除 `python -m packages.api` 行（`packages/api/` 目录下没有 `__main__.py`，命令跑不起来），统一用 `uvicorn` 启动。本文件 §3.1 的 `cp config.example.yaml config.local.yaml` 与 README §"快速开始" 第 41 行 `cp config.local.yaml.example config.local.yaml` **并存**——两个模板文件都存在（前者全字段含 m2/m3，后者精简版仅 m1+api），按需选用。

### 4.2 启动后能访问

| URL | 用途 |
|-----|------|
| http://localhost:8000/docs | Swagger UI（按 tag 分组：ingestion / query / ops） |
| http://localhost:8000/health | liveness probe — 进程存活 |
| http://localhost:8000/ready | readiness probe — DB 连接检查 |
| http://localhost:8000/metrics | Prometheus exposition（FastAPI 内嵌兜底） |
| http://localhost:9464/metrics | Prometheus exposition（独立进程主路，避免 uvicorn --reload 丢累积值） |
| http://localhost:8000/openapi.json | OpenAPI 3.1 spec |

启动 console 会打印一行警告：`WARNING: enable_auth=False, dev-only mode`——这是 F001.1 spec 明示的 dev-only 模式，F001.2 / M3 加 RBAC。

---

## 5. API 使用流程（典型场景）

### 5.1 完整 ingest → 候选 → confirm → query 链路

#### Step 1: ingest 代码仓

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "local_path": "/path/to/your/repo"
    },
    "ingester": {
      "id": "u-alice",
      "name": "Alice",
      "is_admin": false
    },
    "incremental": false
  }'
```

**返回**（201 Created）：

```json
{"repo_id": "rpt-xxxxxxxxxxxx"}
```

**会发生什么**：
1. Unit A 调 `gitnexus analyze` 建图 + URL 白名单/路径沙箱校验
2. `repo_ingest_lock` 表写一条 running 记录（同 repo 二次 ingest 返回 409 INGEST_LOCK_RUNNING）
3. Unit B cypher 粗筛 + tree-sitter 精筛识别日志埋点
4. Unit C LogSanitizer 脱敏（密钥/IP/邮箱/token 零命中才发 LLM）+ LLM 批量推断"打印原因"
5. Unit D 写候选池（candidate_staging 表，不进主表）+ 标记 top_n
6. lock 转 done，返回 repo_id

**典型耗时**：取决于仓库大小 + LLM 调用量，单仓 5-30 分钟。

#### Step 2: 看候选池

```bash
# 默认只看 top_n
curl http://localhost:8000/candidates/{repo_id}

# 看全部候选
curl "http://localhost:8000/candidates/{repo_id}?include_all=true"
```

**返回**（200 OK）：

```json
[
  {
    "id": "lp-xxxx",
    "repo_id": "rpt-xxxx",
    "file_path": "app/auth.py",
    "function_signature": "def login()",
    "line_start": 42,
    "log_message_template": "User {uid} logged in",
    "log_level": "INFO",
    "language": "python",
    "confidence_score": 1.0,
    "occurrence_count": 5,
    "is_top_n": true,
    "ingestion_status": "candidate",
    "llm_hypothesis": {
      "summary": "记录用户登录成功事件",
      "possible_causes": ["..."],
      "error_kind": "unknown",
      "model_name": "gpt-4",
      "prompt_hash": "sha256-xxxx",
      "generated_at": "2026-07-27T12:00:00Z"
    }
  }
]
```

#### Step 3: 用户勾选 confirm 入主表

```bash
curl -X POST http://localhost:8000/confirm/{repo_id} \
  -H "Content-Type: application/json" \
  -d '{
    "log_point_ids": ["lp-xxxx", "lp-yyyy"],
    "confirmer": {
      "id": "u-alice",
      "name": "Alice",
      "is_admin": false
    }
  }'
```

**返回**（204 No Content）——LogPoint 从 candidate 状态转 confirmed/ingested 入主表。

#### Step 4: 查主表

```bash
# 按文件路径过滤
curl "http://localhost:8000/log-points/{repo_id}?file_path=app/auth.py"

# 按函数签名 + 日志级别过滤
curl "http://localhost:8000/log-points/{repo_id}?function_signature=def%20login&log_level=ERROR"
```

#### Step 5: 取调用上下文（M4 改进模块会用）

```bash
curl -X POST http://localhost:8000/call-context/{repo_id} \
  -H "Content-Type: application/json" \
  -d '{
    "function_signature": "def login()"
  }'
```

**返回**（200 OK）：

```json
{
  "function_signature": "def login()",
  "callers": [],
  "callees": [],
  "enclosing_community": "AuthModule",
  "related_log_points": [...],
  "evidence_refs": []
}
```

> **注意**：`callers` / `callees` 在 F001 v1 是空列表，spec 标注 "T14 或后续 family 填充"。当前 `get_call_context` 主要返回 `related_log_points`（同 repo 的 LogPoint 全集，内存 list 形式）。

### 5.2 反向操作：revoke（撤回候选池）

误 confirm 的 LogPoint 可以撤回到候选池：

```bash
curl -X POST http://localhost:8000/revoke/{repo_id} \
  -H "Content-Type: application/json" \
  -d '{
    "log_point_ids": ["lp-xxxx"],
    "revoker": {
      "id": "u-alice",
      "name": "Alice",
      "is_admin": false
    }
  }'
```

**返回**（204 No Content）——状态机回退：`ingested/confirmed → candidate`，**不删主表记录**（P0 持久化铁律，保留可追溯历史）。

### 5.3 admin 操作：force_release_lock

ingest 进程崩溃 / 卡死，lock 表还停在 running 状态——admin 可强制释放：

```bash
curl -X POST http://localhost:8000/ingest/force-release/{repo_id} \
  -H "Content-Type: application/json" \
  -d '{
    "admin": {
      "id": "u-admin",
      "name": "Admin",
      "is_admin": true
    }
  }'
```

非 admin 调用 → `403 FORBIDDEN`。写 audit_log action=ACTION_FORCE_RELEASE_LOCK。

---

## 6. 状态机参考

### 6.1 repo_ingest_lock 状态机

```
                 ┌─────────┐
                 │ running │ ← ingest_repo 调用创建
                 └────┬────┘
                      ↓
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
   ┌─────────┐  ┌─────────┐  进程崩溃/
   │  done   │  │ failed  │  超时 30min 无心跳
   └─────────┘  └────┬────┘
                     ↓
              用户重新调 ingest_repo
              （新建 lock 记录，幂等）

   admin 调 force_release_lock
   把 running 强制转 failed
```

### 6.2 LogPoint ingestion_status 状态机

```
   ┌───────────┐  confirm   ┌────────────┐
   │ candidate │ ─────────→ │ confirmed  │
   └─────┬─────┘            └─────┬──────┘
         ↑                        ↓
         │  revoke          query_log_points
         │                  过滤掉 candidate
         │                        ↓
         │                  ┌──────────┐
         └──────────────────│ ingested │
              revoke        └──────────┘
              （状态回退不删记录，P0 铁律）
```

---

## 7. 错误响应格式

统一格式（云长 C-1 + I-1 修订）：

```json
{
  "code": "M1_INVALID_PATH",
  "message": "Path is outside sandbox: /etc/passwd",
  "details": {}
}
```

常见错误码：

| HTTP | code | 触发场景 |
|------|------|----------|
| 400 | M1_INVALID_PATH | local_path 越权（UnsafePathError） |
| 400 | M1_INVALID_URL | repo_url 非 https 或不在白名单（UnsafeUrlError） |
| 409 | M1_INGEST_LOCK_RUNNING | 同 repo 已有 running lock |
| 422 | GENERIC_VALIDATION_ERROR | Pydantic strict + extra=forbid 验证失败 |
| 422 | M1_REPO_NOT_FOUND | repo_id 不存在 |
| 500 | GENERIC_INTERNAL_ERROR | 未捕获异常 |
| 503 | M1_NOT_READY | `/ready` 检查 DB 不可达 |

错误码命名空间：`M1_*` / `M2_*`（待 F002 merge）/ `M3_*` / `M4_*` / `GENERIC_*`。

---

## 8. 测试 / 验证

```bash
# 全量测试套件（spec 标 254 passed + 1 skipped，需要 Python 3.11+ 环境）
pytest tests/

# 只跑 M1 unit 测试
pytest tests/unit_a/ tests/unit_b/ tests/unit_c/ tests/unit_d/

# 只跑 F001.1 HTTP 层测试
pytest tests/api/

# 只跑端到端
pytest tests/e2e/

# Lint
ruff check .
```

**已知 baseline 问题**（与 F001/F001.1 无关）：
- `tests/unit_b/` + `tests/unit_c/` 部分 tree-sitter 测试在 Python 3.10 环境 `TypeError: __init__() takes exactly 1 argument (2 given)`——是 tree-sitter 包版本兼容问题，main 分支同样失败
- F002 在 `feat/f002-impl` 分支已用 `from datetime import UTC`（Python 3.11+ 语法），3.10 环境跑不了

---

## 9. Scope 边界（明确不做）

| 不做 | 留给 |
|------|------|
| 认证 / RBAC | F001.2 或 M3 |
| CORS 写死 localhost:3003 | F003 前端开发时再开放 |
| HTTPS / TLS | 生产部署时加 |
| rate limiting | 生产部署时加 |
| API versioning（`/v1/...` 前缀） | 生产部署时加 |
| 修改 M1 service 层任何代码 | F001.1 是纯 wrapper，铁律 |
| 真实 LLM client 注入 | 生产部署前落地（spec §Dependencies 明示"铲屎官提供 key 配置注入"）；当前 `deps.get_service` 用 `AsyncMock(spec=LLMClient)` 占位 |

---

## 10. 后续模块预告

| 模块 | 状态 | 用途 |
|------|------|------|
| F002 M2 离线 LLM 分析 | feat 分支等 merge（cross-family review APPROVE，5 硬条件全过） | 两阶段 LLM 分析：Phase 1 全量报告 + Phase 2 深入分析回写 M1 `llm_hypothesis` |
| F003 M3 在线扫描 | backlog | 依赖 M2 Phase 1 报告 + M1 候选池 |
| F004 M4 LLM 改进建议 | backlog | 基于 M2 Phase 2 DeepAnalysisRecord 生成修复 diff 建议 |

---

## 11. 协作

- 主 owner：@奉孝（ragdoll-pa82, GLM-5.2, Siamese）
- Reviewer：@云长（cat-ko094z1n, GLM-5.2, Sphynx 跨家族）
- 审计：@孝直（Qwen-3.7）
- spec：`docs/features/F001-*.md` + `docs/features/F001.1-*.md`
- 实施计划：`docs/superpowers/plans/2026-07-2*-*.md`
- 决策追溯：`docs/decisions/F001-*` + `F001.1-*`

---

[云长/GLM-5.2🐾] 当前实现功能使用指导 — F001 + F001.1 已落地部分，F002 待 merge 不在范围。
