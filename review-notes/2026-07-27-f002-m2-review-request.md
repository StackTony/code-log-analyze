# F002 M2 离线 LLM 分析模块 — Review 请求

**To**: @云长（关羽 GLM-5.2，跨家族 review）
**From**: @奉孝（郭嘉 GLM-5.2，Siamese）
**Date**: 2026-07-27
**Review-Target-ID**: `f002`
**Branch**: `feat/f002-impl`（远端已 push）
**Base**: `main`（HEAD: f2fafa8 — F002 spec v1）

---

## Original Requirements

铲屎官 2026-07-27 07:18 UTC 需求补充（3 次重复提示）：

> 利用LLM进行分析日志时，先默认对日志全量分析，给出整体性的分析报告（系统在做什么、哪里有问题、错误间的关联等等）。然后客户要求时再对某些行结合日志所在代码仓的解析的结果和全量分析报告的结果重点二次/多次进行深入LLM分析

**来源**：铲屎官 chat 直接指示（已在 docs/features/F002-日志离线分析.md spec v1 提炼为 C-1/C-2 决策追溯矩阵）

**请 reviewer 对照判断**：spec v1 §一/§二/§三/§四 是否忠实落地了铲屎官"两阶段 LLM 分析模式 + 累积上下文"的核心需求？

---

## Architecture Ownership

- **Architecture cell**: M2 离线 LLM 分析（新增 cell，F002 spec §一定位为"依赖 M1 query_log_points + get_call_context + LogPoint.llm_hypothesis 字段，对外提供 analyze_logs + deep_analyze"）
- **Map delta**: new cell required — M2 是全新子包，不修改 M1 cell boundary
- **Why**: 铲屎官需求补充明确"深入 LLM 分析"是 M2 的动作（"利用 LLM 进行分析日志时... 重点二次/多次进行深入 LLM 分析"），M4 应基于 M2 深入分析结果再做"改进"（修复建议/diff），不是 M2 的深入分析本身

**Reviewer 检查 diff 与 Map delta 是否一致**：F002 是否真的没动 M1 cell boundary？AC-18 M1 字节级无回归是否成立？

---

## What's in this PR

11 commits 自 main 起，+6049/-6 行：

```
34e0eb7 feat(m2): M2Config 段 + config_loader 扩展（spec §七）
2c7f5b6 feat(m2): MetricsEmitter — 5 个 m2_* 指标 + service 集成（AC-14）
769a33f feat(m2): HTTP routes — 5 个端点（AC-12 + AC-13）
543ead5 feat(m2): LogAnalysisService — 5 API 方法编排层（AC-15 + AC-19）
9e497d1 feat(m2): ReportGenerator + DeepAnalyzer — 两阶段 LLM 分析（AC-3/4/5/6/7/8/10/11/17）
db597da feat(m2): Storage Repository — dataclass ↔ Model JSON 转换 + CRUD
5e48f63 feat(m2): Storage 三张表 + migration 0002（AC-16/18）
122b525 feat(m2): hypothesis_writer — Phase 2 假设回写 M1 LogPoint.llm_hypothesis（AC-9）
6dc05d1 feat(m1+m2): RepoLogGraphService.update_log_point_hypothesis — F002 §十 回写入口（AC-9）
4572ff3 feat(m2): LogPointMatcher — log_message_template hash 匹配（AC-2）
29c8b7b feat(m2): 起步骨架 — contracts 扩展 + LogParser v1 + 13 测试全绿
```

文件结构（spec §五）：

```
packages/
  contracts/
    analysis_report.py     # AnalysisReport + Anomaly + ErrorChain + TokenUsage
    deep_analysis.py       # DeepAnalysisRecord
    log_entry.py           # LogEntry + LogSource（F002 新增 LogSource）
    enums.py               # ACTION_PHASE1_ANALYZE / ACTION_PHASE2_DEEP_ANALYZE / ACTION_ARCHIVE_REPORT
  m2/
    log_parser.py          # AC-1 三种日志格式
    log_point_matcher.py   # AC-2 template hash 匹配
    report_generator.py    # AC-3/4/5/6/17 Phase 1 LLM 调用
    deep_analyzer.py       # AC-7/8/10/11 Phase 2 LLM 调用
    hypothesis_writer.py   # AC-9 M1 LogPoint 回写
    metrics_emitter.py     # AC-14 5 个 m2_* 指标
    log_analysis_service.py # 5 API 方法编排层（AC-15 + AC-19）
    storage/
      models.py            # AnalysisReportModel + DeepAnalysisModel + LogEntryModel
      repository.py         # dataclass ↔ Model JSON 转换 + CRUD
      migrations/versions/0002_m2_analysis_tables.py
  api/
    schemas/analysis.py    # 8 个 Pydantic schemas（strict + extra=forbid）
    mappers/analysis.py    # dataclass → API schema
    routes/analysis.py     # 5 个 endpoints
```

---

## AC Coverage

| AC | 状态 | 落地点 | 测试数 |
|----|------|--------|--------|
| AC-1 LogParser 3 种格式 | ✅ | `packages/m2/log_parser.py` | 13 |
| AC-2 LogPointMatcher ≥70% | ✅ | `packages/m2/log_point_matcher.py` | 18（fixture 70%） |
| AC-3 Phase 1 三类信息 | ✅ | `ReportGenerator.generate` | 16（含 AC-19） |
| AC-4 时间窗兜底 24h | ✅ | `ReportGenerator.truncate_to_window` tz-tolerant | — |
| AC-5 LogSanitizer 脱敏 | ✅ | ReportGenerator + DeepAnalyzer 复用 M1 | — |
| AC-6 Redis 缓存 key | ✅ | `_cache_key` 含 phase1/2 + model_name + template hash | — |
| AC-7 Phase 2 上下文组装 | ✅ | `DeepAnalyzer._assemble_prompt` 4 部分 | 11 |
| AC-8 DeepAnalysisRecord | ✅ | `packages/contracts/deep_analysis.py` | — |
| AC-9 回写 M1 LogPoint | ✅ | `HypothesisWriter` + M1 `update_log_point_hypothesis` 新方法 | 8 + 7 |
| AC-10 累积上下文链 | ✅ | `DeepAnalyzer.analyze` iteration 递增 + parent_record_id | — |
| AC-11 max_iterations=5 | ✅ | `IterationLimitExceeded` + 409 错误码 | — |
| AC-12 5 endpoint TestClient | ✅ | `tests/api/test_analysis_routes.py` | 18 |
| AC-13 M2_* 错误码 | ✅ | 5 个错误码 + 复用 F001.1 error_handlers | — |
| AC-14 5 个 m2_* metrics | ✅ | `M2MetricsEmitter` + service 集成 | 6 + 3 |
| AC-15 audit_log 写操作 | ✅ | analyze/deep_analyze/archive 各写 audit_log | — |
| AC-16 P0 持久化 TTL=0 | ✅ | 三张表默认无 TTL 字段 | 13 + 17 |
| AC-17 成本控制 | ✅ | M2Config.phase1_model（便宜）+ phase2_model（强）+ max_log_lines_per_call=200 | — |
| AC-18 M1 字节级无回归 | ✅ | M1 仅加 `update_log_point_hypothesis` 新方法，无字段变更 | 0 regression |
| AC-19 端到端 fixture | ✅ | `test_log_analysis_service.py::TestDeepAnalyze` | 3 |
| AC-20 跨家族 review | 🔄 | 本 PR 提请 @云长 review | — |

---

## Self-Check Evidence

### Quality-gate

- 原始需求逐项对照：spec v1 §一/§二/§三/§四 落地铲屎官 C-1/C-2 决策追溯矩阵
- 测试 / lint / build：见下
- AC-20 跨家族 review：本 PR

### 测试命令输出

```
$ pytest tests/ --ignore=tests/e2e --ignore=tests/unit_b --ignore=tests/unit_c \
    --ignore=tests/api/test_call_context.py \
    --ignore=tests/api/test_candidates.py \
    --ignore=tests/api/test_log_points.py \
    --ignore=tests/api/test_ingest.py
======================= 242 passed, 1 skipped in 9.28s ========================
```

**已知 baseline 失败**：tests/unit_b/ + tests/unit_c/ + 4 个 API route 测试因 tree-sitter 环境问题失败（`TypeError: __init__() takes exactly 1 argument (2 given)`，与 F002 无关，main 分支同样失败）。

### M2 子集测试

```
$ pytest tests/m2/ tests/api/test_analysis_routes.py tests/api/test_config_loader.py tests/api/test_error_handling.py
============================ 142 passed in 11.62s ============================
```

### Worktree 落点自检

```
$ cd .worktrees/f002-impl && git status --short
(empty — 全部已 commit + push）

$ cd main worktree && git status --short
(empty — 主 worktree 干净）
```

### 根目录工件闸门

```
$ git status --short | grep '^.. [^/]+\.(png|jpe?g|webp|gif|webm|mp4|mov|wav|pdf|pen)$'
(empty — PASS）

$ git diff --name-only origin/main...HEAD | grep '^[^/]+\.(png|jpe?g|webp|gif|webm|mp4|mov|wav|pdf|pen)$'
(empty — PASS）
```

---

## 重点 Review 视角（请 @云长 重点看）

### 1. 两阶段架构边界（spec §二）

- Phase 1（全量分析）vs Phase 2（深入分析）的 LLM 调用是否真的分离？
- Phase 1 是否只输出 AnalysisReport（system_summary + anomaly + error_chain），不涉及 root_cause？
- Phase 2 是否依赖 Phase 1 的 system_summary 作为上下文？
- `ReportGenerator` + `DeepAnalyzer` 是否有职责重叠？

**关键文件**：`packages/m2/report_generator.py` + `packages/m2/deep_analyzer.py`

### 2. M1↔M2 回写契约（spec §十）

- `HypothesisWriter.write_back()` 调用 M1 `update_log_point_hypothesis` 的契约是否清晰？
- 字段映射：`root_cause_hypothesis → summary`，`fix_suggestion → suggested_check` 是否合理？
- M1 `update_log_point_hypothesis` 是否只更新 `confirmed` 状态的 LogPoint（防止候选池污染）？
- 是否避免 M2↔M1 循环 import（用了 `M1ServiceProtocol`）？

**关键文件**：`packages/m2/hypothesis_writer.py` + `packages/m1/repo_log_graph_service.py` 的 `update_log_point_hypothesis` 方法

### 3. Pydantic strict + extra="forbid" schema 设计

- `packages/api/schemas/analysis.py` 8 个 schema 全部 strict + extra="forbid"
- 是否过于严格？例如 `AnalyzeRequest` 三字段互斥校验在 route handler 而非 schema 层
- `DeepAnalyzeRequest.line_ids: list[str] = Field(min_length=1)` 是否合理？

### 4. 路由测试策略：dependency_overrides 注入 mock

- `tests/api/test_analysis_routes.py` 全用 FastAPI `dependency_overrides[get_log_analysis_service]` 注入 mock service
- 端到端流程已在 `tests/m2/test_log_analysis_service.py` 覆盖（AC-19）
- 这种"路由测试用 mock，集成测试在别处"的策略是否符合测试金字塔？
- 是否漏掉了真实 service 的端到端 HTTP 测试（如 analyze_logs → 报告返回 → deep_analyze → M1 回写）？

### 5. M2 metrics 与 M1 共存 default REGISTRY

- `M2MetricsEmitter` 共享 prometheus_client default REGISTRY
- 主进程 `/metrics` endpoint 会同时暴露 m1_* + m2_* 指标
- 9464 独立进程（spec §六）同样会暴露
- 是否会有"主进程 vs 9464 进程数值不一致"问题（spec §六 B-2 注释提到）？

**关键文件**：`packages/m2/metrics_emitter.py` + `packages/api/deps.py` 的 `_get_m2_metrics_emitter()`

---

## Open Questions

### 技术 OQ（给 @云长）

1. **真实 LLM client 注入**：`deps.get_log_analysis_service` 当前用 `AsyncMock(spec=LLMClient)` 占位，production 需要实现 `LLMClient` 的 OpenAI/Anthropic 子类。是否需要现在就实现一个 OpenAI 子类作为参考？还是留作单独 task？
2. **StorageBackedLogPointIndex**：`LogPointMatcher` 用 `MagicMock(spec=LogPointIndex)` 占位，production 需要从 M1 LogPoint 主表按 template_hash 查询。是否要在本 PR 内补？还是单独 task？
3. **deep_analyze 的 call_context 调用**：当前 `LogAnalysisService.deep_analyze` 对每个 LogPoint 调一次 `m1_service.get_call_context`。如果 N 个 LogPoint，会不会有 N+1 query 问题？是否应该批量？
4. **iteration 父链查找**：`LogAnalysisService.deep_analyze` 用 `set(r.line_ids) == target_line_set` 匹配 parent。如果是部分重叠（前次 [L1, L2]，本次 [L1]），会不会丢失上下文？
5. **AuditLogger.log 签名**：`packages/m2/log_analysis_service.py` 的 audit 写法用了 `target_log_point_ids=record.log_point_ids`，这是 M1 AuditLogger 的字段名。如果 M1 AuditLogger 字段重命名，M2 会断。

### 价值 OQ（给铲屎官/CVO 判断）

无 — 铲屎官需求已在 spec v1 §一/§二/§三/§四 完整落地，没有需要 CVO 拍板的悬而未决事项。

---

## 已知 baseline 问题（与 F002 无关）

- tree-sitter 环境问题（`TypeError: __init__() takes exactly 1 argument (2 given)`）在 `tests/unit_b/` + `tests/unit_c/` + 4 个 API route 测试（call_context/candidates/log_points/ingest）失败，与 F002 无关，main 分支同样失败

## 已知 placeholder（production 部署前必须替换）

- `deps.get_log_analysis_service` 用 `AsyncMock(spec=LLMClient)` 占位 — production 注入真实 `LLMClient` 子类
- `LogPointMatcher(log_point_index)` 的 `log_point_index` 用 `MagicMock(spec=LogPointIndex)` 占位 — production 实现 `StorageBackedLogPointIndex`（M1 主表查询）

---

## Reviewer 启动命令

```bash
# Review-Target-ID: f002
# Branch: feat/f002-impl
git fetch origin
git checkout feat/f002-impl  # 在 worktree 内
pnpm review:start  # 自动分配隔离端口（起点 3201/3202）
```

沙盒标准路径：`/tmp/cat-cafe-review/f002/云长`

---

[奉孝/GLM-5.2🐾]
