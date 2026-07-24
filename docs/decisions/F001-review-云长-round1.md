---
feature_ids: [F001]
related_features: [F002, F003, F004]
topics: [review, cross-family, spec-review, plan-review]
doc_kind: decision
created: 2026-07-24
---

# F001 跨家族 Review — 云长 Round-1

> Reviewer: 云长 (@cat-ko094z1n, GLM-5.1, Maine Coon/quality 族)
> Author: 奉孝 (@ragdoll-pa82, GLM-5.2, Siamese/创意族)
> Review-Target-ID: `f001`
> Status: **通过（附 4 条 Must-Fix + 5 条 Should-Fix + 5 条 Nits）**
> Date: 2026-07-24

---

## Review 范围

| 文件 | 行数 | 审查重点 |
|------|------|----------|
| `docs/features/F001-代码仓日志解析.md` | 539 | spec v4 — 8 章 + 21 AC + CVO 8 项决策 |
| `docs/superpowers/plans/2026-07-24-f001-code-repo-log-parse.md` | 4340 | 15 个 TDD task 覆盖 21 AC |
| `docs/decisions/F001-review-handoff.md` | 233 | 交接卡 — 5 维度审查指引 |

---

## 维度 1: 愿景验证（对照 CVO 原话）

铲屎官原话 4 条逐一对照客户补充章节 C-1 ~ C-8：

| 原话 | 覆盖决策 | 结论 |
|------|----------|------|
| 1 "你是核心组织者，充分调用特长" | C-1~C-8 全覆盖 + 团队分工表 | ✅ 全覆盖 |
| 2 "企业内部平台；v1 支持 C 和 Python；用 gitnexus；LLM 推断打印原因；高频用户决定后入库" | C-1/C-2/C-3/C-4/C-5 全覆盖 | ✅ 全覆盖 |
| 3 "LLM key 通过配置文件注入；Q2 选 A + Top N 配置指定" | C-6/C-7 全覆盖 | ✅ 全覆盖 |
| 4 "按照推荐的来" | 推荐路径已执行（先 review 再 worktree） | ✅ 已执行 |

**愿景验证结论**：✅ CVO 4 条原话在 C-1~C-8 全覆盖，无遗漏、无偏离。客户补充章节的三重锚定（spec 章节 + AC + task 编号）追溯链完整。

---

## 维度 2: Schema 闭环

### 6 个 dataclass 逐一审查

| Dataclass | 字段完整性 | 类型一致性 | 发现的问题 |
|-----------|-----------|-----------|-----------|
| LogPoint | 20 字段全在 spec §三 → T3 实现 | ✅ 一致 | 见 Must-Fix 1 |
| LLMHypothesis | 7 字段全在 spec §三 → T3 实现 | ✅ 一致 | 无 |
| CaseRef | 8 字段全在 spec §三 → T3 实现 | ✅ 一致 | 无 |
| CallContext | 6 字段全在 spec §三 → T3 实现 | ✅ 一致 | 见 Should-Fix 2 |
| RepoIngestLock | 6 字段全在 spec §三 → T3 实现 | ✅ 一致 | 见 Should-Fix 3 |
| AuditLog | 6 字段全在 spec §七 → T3 实现 | ✅ 一致 | 无 |

### 状态机审查

**`ingestion_status` 状态机**：`candidate → confirmed → ingested`；`revoke_ingestion` 可从 `ingested` 退回 `candidate`。

- ✅ 状态转换逻辑完整
- ⚠️ 问题：`revoke_ingestion` 从 `ingested` 退回 `candidate` 后，主表记录怎么处理？spec AC-9 只说"可从 ingested 退回 candidate"，但实施计划 T11 的 `revoke_ingestion` 实现是**直接删除主表记录**——这违反 P0 持久化铁律（用户可见数据默认 TTL=0，删除 ≠ 退回）。见 Must-Fix 2。

**`repo_ingest_lock` 状态机**：`running → done/failed`。

- ✅ 状态机正确
- ⚠️ 问题：`failed` 后能否重试？spec 交接卡 OQ-3 提出此问题但 spec 本身没显式说明。文若 round-2 review 提出补 cleanup 规则（running 卡死 → 超时自动 failed → failed 后允许重 ingest），但这个补丁只在对话历史里，**没写进 spec 文件本身**。见 Must-Fix 3。

### 缓存键审查

缓存键 = `hash(log_template + enclosing_function_signature + model_name + extractor_version)`。

- ✅ 4 字段闭环（spec §二 Unit C 第 77-80 行 + AC-6）
- ⚠️ 交接卡 OQ-4 提问"是否需要加 repo_id？"——我的判断：**不需要**。理由：缓存的目的是在同一 repo 解析时复用 LLM 调用；repo_id 不同 = 不同仓 = 不同上下文，不应该复用假设。缓存键不含 repo_id 是正确设计。但同仓不同函数相同 log_template（如 `logger.info("operation completed")` 在 10 个函数里都出现）应该**分开缓存**（因为 `enclosing_function_signature` 不同），这是正确的。

---

## 维度 3: 实施计划落地

### 任务依赖关系

T1 → T2 → T3（契约） → T4（存储） → T5（gitnexus） → T6（Unit A） → T7-T8（Unit B） → T9-T10（Unit C） → T11（Unit D） → T12（审计） → T13（metrics） → T14（API） → T15（review）

- ✅ 无循环依赖
- ✅ 前置关系合理

### TDD 节奏

15 个 task 全部有 red → fail → impl → pass → lint → commit 6 步节奏。

- ✅ 无 task 缺少 lint 步骤
- ⚠️ 问题见 Must-Fix 4 + Should-Fix 5

### fixture 仓覆盖

7 个 fixture 仓（6 含日志 + 1 decoy） vs 6 种 pattern × 2 语言：

| Pattern | 语言 | Fixture 仓 | 覆盖 |
|---------|------|-----------|------|
| Python logging | Python | python_logging_repo | ✅ |
| Python loguru | Python | python_loguru_repo | ✅ |
| Python 裸 print | Python | python_print_repo | ✅ |
| C printf | C | c_printf_repo | ✅ |
| C syslog | C | c_syslog_repo | ✅ |
| C 自定义 | C | c_custom_log_repo | ✅ |
| 干扰函数 | 跨语言 | decoy_repo | ✅ |

- ✅ 6 × 2 全覆盖
- ⚠️ 缺跨语言混合仓（一个仓同时含 C 和 Python 代码——真实仓常见）

### Global Constraints 覆盖

| Constraint | 是否每 task 显式提及 | 发现 |
|------------|---------------------|------|
| Worktree 铁律 | Global Constraints 节声明 | ✅ |
| Redis 6398 | T2 config_loader 验证 + Global Constraints | ✅ |
| metrics 9100 | T13 + Global Constraints | ✅ |
| Python 基线 | T1 pyproject.toml | ✅ |
| file_path POSIX | T4 models + T8 test | ✅ |
| TTL=0 P0 | T11 + Global Constraints | ✅ |

---

## 维度 4: 风险缓解

spec §Risk 表 10 项逐一审查：

| 风险 | 等级 | spec 缓解 | 实施落地 | 我的判断 |
|------|------|-----------|---------|---------|
| CALLS 边误识别 | 🟡 中 | Layer 1 + Layer 2 + AC-5 | T7-T8 | ✅ 合理 |
| LLM 调用成本 | 🟡 中 | Redis 缓存 + 批量 + 复用 | T9-T10 | ✅ 合理 |
| 候选池无限增长 | 🟢 低 | TTL 30 天清理 | T11 cleanup_expired() | ⚠️ 见 Should-Fix 4 |
| LLM 幻觉 | 🟡 中 | 标注"参考假设" | T9 | ✅ 但见 Nits 1 |
| 跨 thread 平行自己 | 🟡 中 | commit push 后记忆索引 | — | ✅ 合理 |
| 跨平台路径 | 🟢 低 | POSIX 统一 | T8 | ✅ |
| LLM 外发敏感数据 | 🔴 高 | LogSanitizer + AC-8 | T9 | ✅ 合理 |
| 并发 ingest | 🟡 中 | repo_ingest_lock + AC-14 | T6 | ⚠️ 见 Must-Fix 3 |
| schema 演化 | 🟡 中 | git_commit_sha + extractor_version | T10 | ✅ 合理 |
| 候选池确认后识别错误 | 🟡 中 | revoke_ingestion + audit | T11 | ⚠️ 见 Must-Fix 2 |

**缺失风险**：见 Should-Fix 5 — LLM 服务不可用的降级策略没写进 spec Risk 表。

---

## 维度 5: 跨家族风险点

### Siamese 边写边想残留

逐章扫描 spec，找"先这样/后续再改/暂时/v1 可/simplified"等措辞：

| 位置 | 措辞 | 评估 |
|------|------|------|
| §二 Unit A | "v1 可只留接口"（incremental） | ✅ 合理——AC-20 明确声明 |
| §五 ingest_repo | "incremental=True 时调 gitnexus detect_changes 做增量" + "v1 可 raise NotImplementedError" | ✅ 合理——接口预留 + 显式声明 |
| T11 revoke | "simplified — 删除主表记录" | ❌ 见 Must-Fix 2 |

**结论**：spec 整体干净，无"先这样后面再说"的模糊地带——除了 T11 revoke 的实现。这是跨家族 review 发现的最重要的一个问题。

### Maine Coon fallback 层数检测

追踪 Unit C 的降级链：

1. LLM 调用 → 成功 ✅
2. LLM 调用失败 → 重试 3 次（指数退避）
3. 3 次全失败 → `llm_hypothesis = None`，不阻塞流水线
4. 缓存命中 → 跳过 LLM 调用

这是 **3 层 fallback**（正常 → 重试 → None），不是 ≥3 层，刚好在 Maine Coon 检测阈值边缘。我的判断：**合理**——3 层每层都有明确目的，不存在"去掉一层也能正常工作"的情况。

### 创意-实现解耦

扫描 spec 提出的设计 vs plan task 落地：

| spec 设计 | plan Task | 落地 |
|-----------|----------|------|
| gitnexus cypher 粗筛 | T8 | ✅ |
| tree-sitter 精筛 | T7-T8 | ✅ |
| LogSanitizer | T9 | ✅ |
| Redis 缓存 | T9-T10 | ✅ |
| 候选池两阶段入库 | T11 | ✅ |
| audit_log | T12 | ✅ |
| metrics 5 个指标 | T13 | ✅ |
| CallContext（M4 依赖） | T3 | ✅ |
| incremental 接口 | T6 | ✅（NotImplementedError） |
| force_release_lock admin API | T12 | ⚠️ 见 Should-Fix 3 |

**结论**：创意-实现解耦良好，只有 force_release_lock 在 spec 声明但 plan T12 的 audit_log.py 代码里没显式实现这个 admin API。

---

## Must-Fix（阻断实施，必须修订才能通过）

### MF-1: LogPoint.first_seen_at / last_seen_at 类型不一致

**问题**：spec §三 LogPoint dataclass 声明 `first_seen_at: datetime` 和 `last_seen_at: datetime`（无 `| None`），但实施计划 T3 的 `packages/contracts/log_point.py` 实现为 `first_seen_at: datetime | None = None` 和 `last_seen_at: datetime | None = None`。

spec 说这两个字段是必填的（候选池就有值），但实现允许 None。这会导致下游代码在使用这两个字段时要么做 None 检查（违反 spec 语义），要么直接访问可能抛 AttributeError。

**修复**：spec 和实现必须统一。建议实现改为必填（符合 spec 语义——候选池写入时就填时间戳）：

```python
first_seen_at: datetime  # 必填，候选池写入时设值
last_seen_at: datetime   # 必填，候选池写入时设值
```

测试 T3 的 `test_log_point_roundtrip` 也要调整——当前测试传了 `datetime(...)` 值，是正确的，但 dataclass 定义允许 None 会误导后续 task 开发者。

### MF-2: revoke_ingestion 实现违反 P0 持久化铁律

**问题**：实施计划 T11 的 `revoke_ingestion()` 实现**直接删除主表 LogPointModel 记录**（代码注释承认 "simplified"）。但 spec AC-9 说"revoke_ingestion 可从 ingested 退回 candidate"，而家规 P0 铁律要求"用户可见、可追溯、可恢复预期的数据默认 TTL=0"。

**删除 ≠ 退回**——用户 revoke 后：
1. 主表记录消失了（违反可追溯）
2. 历史查询结果不再包含这条 LogPoint（违反可恢复预期）
3. audit_log 记录了撤销动作，但数据本身丢失了

**修复**：`revoke_ingestion()` 不应删除主表记录。正确实现是：
- 主表 LogPointModel 的 `ingestion_status` 从 `ingested` 改回 `candidate`
- 或者：主表记录保留但加 `revoked_at: datetime | None` 字段标记已撤销，`query_log_points()` 过滤掉 `revoked_at != None` 的记录
- audit_log 记录撤销时间 + 撤销人

两种方案各有优劣，建议奉孝选一种并在 spec 补声明。

### MF-3: RepoIngestLock 状态机 failed→重试 + running→超时 规则未写入 spec

**问题**：交接卡 OQ-3 提出此问题。文若 round-2 review 也在对话历史里提出补 cleanup 规则（`running` 超时 → `failed` / `failed` 后允许重 ingest / force_release admin API）。但这些补丁只存在于对话历史和交接卡的问题列表里，**没有写进 spec 文件本身**。

spec §二 Unit A 和 §三 RepoIngestLock 只声明了 `running/done/failed` 三个状态，没说：
- `running` 卡死（进程崩溃）怎么清理？超时阈值是什么？
- `failed` 后能否重试？
- 是否有 `force_release_lock` admin API？

配置文件 §六 有 `ingest_timeout_minutes: 30`，但这个配置项只存在于 config schema 里，没和 RepoIngestLock 状态机行为关联。

**修复**：spec §二 Unit A 和/或 §三 RepoIngestLock 需补一段状态机规则说明：
- `running` 超过 `ingest_timeout_minutes`（配置项）无心跳 → 自动转 `failed`
- `failed` 后允许重新 `ingest_repo`（新建 lock 记录）
- 加 `force_release_lock` admin API（仅 admin role）→ spec §五 对外 API 也需补此方法
- 7 个 ACTION_* 常量里 `ACTION_FORCE_RELEASE_LOCK` 已在 enums.py 定义，但 spec §五 API 方法列表缺少对应方法声明

### MF-4: T11 候选池 staging 丢失完整 LogPoint 数据

**问题**：T11 的 `CandidateStagingModel` 只存了 `id`/`repo_id`/`occurrence_count`/`is_top_n`/`ingestion_status`/`first_seen_at`/`last_seen_at` 等 7 个字段。但 `list_candidates()` API 需要返回完整 LogPoint（含 `file_path`/`function_signature`/`log_message_template`/`llm_hypothesis` 等 20 个字段）。

T11 的 `_staging_to_log_point()` 实现把空字符串填入缺失字段——这意味着 `list_candidates()` 返回的 LogPoint **大部分字段是假数据**。用户看到的候选列表无法展示真实信息（文件路径、函数签名、日志内容），这直接违反 C-5（"高频日志让用户决定后再存入数据库"）——用户怎么决定？看不到日志内容怎么决定？

**修复**：`CandidateStagingModel` 必须存储完整 LogPoint 数据（或至少是用户筛选 UI 需要展示的关键字段：file_path / function_signature / log_message_template / log_level / framework_hint / confidence_score / occurrence_count / is_top_n / llm_hypothesis_json）。两个可行方案：

- **方案 A**：候选池表直接存全部 LogPoint 字段（加 `ingestion_status`/`first_seen_at`/`last_seen_at`）—— 入主表 = 从候选池复制到主表（简单粗暴但数据完整）
- **方案 B**：候选池表只存轻量索引 + LogPoint JSON blob（`full_log_point_json` 字段存完整 dataclass 序列化）—— 入主表 = deserialize + 写 ORM

建议选方案 A——字段级可查询、可索引、可过滤，比 JSON blob 更适合企业内部平台。

---

## Should-Fix（建议但非阻断，可在实施阶段补）

### SF-1: 缺跨语言混合 fixture 仓

6 个 fixture 仓全是单语言，但真实仓常见混合（如 C 核心库 + Python wrapper）。AC-5 误识别率 < 5% 在单语言仓上验证过，但跨语言仓的 tree-sitter parser 切换逻辑没覆盖。

**建议**：加第 8 个 fixture 仓 `mixed_c_python_repo/`——含 C 文件 + Python 文件，验证 Unit B 能正确识别两种语言的日志调用并切换 parser。

### SF-2: CallContext 缺 repo_id 字段

`CallContext` dataclass 有 `function_signature`/`callers`/`callees`/`enclosing_community`/`related_log_points`/`evidence_refs`，但缺 `repo_id`。M4 调用 `get_call_context(repo_id, function_signature)` 时，返回值需要知道来自哪个仓——当前靠调用参数传 repo_id，但如果 M4 把 CallContext 存下来后续使用，就不知道来源仓了。

**建议**：`CallContext` 加 `repo_id: str` 字段。一行改动，不影响 T3 测试（测试里加 `repo_id="repo-1"` 即可）。

### SF-3: force_release_lock admin API 实施计划缺实现

spec §三 enums.py 定义了 `ACTION_FORCE_RELEASE_LOCK`，配置 §六 有 `ingest_timeout_minutes`，但：
- spec §五 对外 API 方法列表只有 6 个方法，缺少 `force_release_lock`
- plan T12 的 audit_log.py 只写了 audit 记录逻辑，没写 force_release 的 API 路由或 service 方法

**建议**：spec §五 补 `force_release_lock(repo_id, admin_user) -> None` 方法声明；plan T6 或 T12 补实现步骤。

### SF-4: 候选池 TTL 清理触发机制缺失

spec §二 Unit D 说 "候选池 TTL 清理：ingestion_status='candidate' AND last_seen_at < now()-TTL(30 天)"，但没说怎么触发：
- cron 定时任务？
- 写操作时惰性清理？
- 独立 worker？

plan T11 有 `cleanup_expired()` 方法，但没说谁调、什么时候调。

**建议**：spec 补一段触发机制声明（如"每次 `ingest_repo` 完成后顺带调 `cleanup_expired()`" 或 "cron 每天 03:00 调"），plan T11 补步骤。

### SF-5: LLM 服务不可用降级策略缺 spec 声明

spec Risk 表只有"LLM 输出幻觉"风险，没有"LLM 服务不可用"的降级策略。plan T9 的实现有重试 3 次 + 全失败设 `llm_hypothesis = None`，但 spec 没显式声明这个行为。

**建议**：spec §Risk 表补一行：
| LLM API 不可用（超时/限流/key 失效） | 🟡 中 | 单条重试 3 次（指数退避），仍失败 → `llm_hypothesis=None`；整批不可用 → `llm_degraded=True` 标记到 RepoIngestLock.error_msg |

---

## Nits（小问题，不影响实施）

### N-1: LLM 幻觉风险缓解措辞偏弱

spec Risk 表写"llm_hypothesis 标注为'参考假设'，不作为 M4 自动改代码依据"——这是正确方向，但"标注为参考假设"只是 label，不是结构性约束。M4 开发者可能不看 label 直接用假设做自动修改。

**建议**：在 CallContext 或 LLMHypothesis 加一个 `is_automated_actionable: bool = False` 字段——代码层面的硬约束比 label 更可靠。或者至少在 spec §四下游依赖里加一句"M4 不得基于 llm_hypothesis 自动提交代码变更，必须 human-in-the-loop review"。

### N-2: AC-21 是流程项不是 spec 验收标准

文若 round-2 review 也提出此问题（"新问题 7"）。AC-21 "跨家族 review 通过" 是实施阶段流程要求，不是 spec 验收标准——review 在 spec 写完后做，不应列为 spec AC。

**建议**：从 AC 列表删除 AC-21，移到团队分工或流程说明里。

### N-3: T5 gitnexus client 用 subprocess 而非 MCP stdio

plan T5 用 `subprocess.run()` 调 gitnexus CLI 而不是 MCP stdio 协议。这是合理的简化（避免 MCP runtime 复杂度），但 spec §一 说"用 gitnexus 做 graph backend"没声明调用方式。如果后续 M2/M3 也要调 gitnexus，统一用 MCP stdio 可能更高效。

**建议**：不阻断——subprocess 方案 v1 可用。但 spec Dependencies 节补一句"当前通过 CLI subprocess 调用；后续 phase 可迁移到 MCP stdio 协议降低开销"。

### N-4: T10 asyncio.run() 在同步上下文中的隐患

plan T10 的 `ingest()` 方法用 `asyncio.run(self._llm_gen.generate(points))` 在同步上下文跑异步 LLM 调用。如果 `ingest()` 本身被 FastAPI 的 async handler 调用，会嵌套 asyncio loop 导致崩溃。

**建议**：不阻断 v1——T14 FastAPI 入口可能把 `ingest()` 包装成 sync endpoint。但 plan T10 补注释："若 FastAPI 用 async handler，需改为 await 而非 asyncio.run()"。

### N-5: 配置加载缺少 config.yaml（入库默认值）路径

spec §六 说加载顺序 "env > config.local.yaml > config.yaml（入库，默认值）"，但 plan T2 只实现了 `config.local.yaml` 和 `config.example.yaml`，没有 `config.yaml`。`config.example.yaml` 的文件名和 spec 描述的 `config.yaml` 不一致。

**建议**：统一命名。要么把 `config.example.yaml` 改名为 `config.yaml`（入库默认值），要么 spec 加说明 "`config.example.yaml` 即入库默认值，`config.local.yaml` 覆盖之"。

---

## 对交接卡 OQ 的回答

| OQ | 我的判断 |
|-----|---------|
| OQ-1: confidence_score 阈值 1.0/0.5/0.7 是否合理？ | ✅ 合理——logging 框架调用 = 1.0（确定性高）；裸 print = 0.5（可能非日志）；自定义函数名 = 0.7（中置信度，regex 匹配但非标准框架）。阈值梯度合理，且 0.5 不会进主表噪音太多（用户筛选 UI 只看 top_n，裸 print 默认不识别） |
| OQ-2: 7 个 fixture 仓是否足够覆盖边界 case？ | ⚠️ 见 SF-1——缺跨语言混合仓。7 个覆盖了 6 pattern × 2 语言的基本组合，但真实仓边界（混合语言、macro 展开、多行日志调用）需要额外 fixture |
| OQ-3: ingest_timeout_minutes=30 是否合理？ | ✅ 合理——中等规模仓（几百文件）30 分钟够了；大仓（万级文件）可能超时，但这正好触发 failed → 用户可重试或 force_release。建议后续 phase 加仓规模自适应超时 |
| OQ-4: 缓存键 enclosing_function_signature 稳定性 | ✅ 不需要修改——函数重命名后缓存失效是合理的（上下文变了）；函数体不变只改签名极少见，且签名变了 = 语义可能也变了，缓存失效比复用旧假设更安全 |
| OQ-5: TDD 粒度是否合理？ | ⚠️ 见 Must-Fix 4——T11 需拆分（staging 数据完整性问题太大）。T7（tree-sitter + 7 fixture 仓）和 T9（LogSanitizer + LLM）粒度可接受——各有独立测试入口 |

---

## Review 总结

| 级别 | 数量 | 阻断实施？ |
|------|------|-----------|
| Must-Fix | 4 | ✅ 是——修订后才能进 T1 |
| Should-Fix | 5 | ❌ 不阻断——可在实施阶段补 |
| Nits | 5 | ❌ 不阻断——小改进 |

### Must-Fix 摘要

1. **LogPoint.first_seen_at/last_seen_at 类型不一致**：spec 说必填，实现允许 None → 统一为必填
2. **revoke_ingestion 删除记录违反 P0 铁律**：删除 ≠ 退回 → 改为状态回退或保留 + revoked_at 标记
3. **RepoIngestLock 状态机规则未写入 spec**：failed→重试 / running→超时 / force_release_lock 缺声明
4. **候选池 staging 丢失完整 LogPoint 数据**：list_candidates() 返回假数据 → 候选池必须存完整字段

### 最终判定

**通过（附条件）**：4 条 Must-Fix 修订后即可进实施。Should-Fix 和 Nits 不阻断，可在实施过程中逐步补齐。

奉孝修订 4 条 Must-Fix 后，我不需要再 round-2 review——这些是 spec/plan 级别的小修补，不是架构推翻。修订完直接开 worktree 进 subagent-driven-development。

---

[云长/GLM-5.1🐾]
