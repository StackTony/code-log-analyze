---
feature_ids: [F001]
related_features: [F002, F003, F004]
topics: [review, handoff, cross-family]
doc_kind: decision
created: 2026-07-24
---

# F001 Review Handoff — 跨家族 review 交接卡

> Author: 奉孝 (@ragdoll-pa82, GLM-5.2, Siamese/创意族)
> Reviewer: @云长 (GLM-5.1, Maine Coon/quality 族) — 跨家族铁律满足
> Status: **awaiting review**
> Review-Target-ID: `f001`
> Branch: `master`（本 PR 是 spec + plan 文档，无代码 worktree；主仓库直接 commit）

---

## What

F001 代码仓日志解析模块的 **spec + 实施计划**（Phase 0 交付物，无代码改动）请 @云长 跨家族 review。

### Review 范围

| 文件 | 行数 | 内容 |
|------|------|------|
| `docs/features/F001-代码仓日志解析.md` | 539 | spec v4 — 含 8 章 + 21 AC + 客户补充章节（CVO 8 项决策提炼） |
| `docs/superpowers/plans/2026-07-24-f001-code-repo-log-parse.md` | 4340 | 实施计划 — 15 个 bite-sized TDD task 覆盖 21 AC |
| `BACKLOG.md` | 18 | F001-F004 四模块 roadmap |
| `.gitignore` | 84 | Python/pytest/ruff 基线 + config.local.yaml + stray instance-*.log |

### Commit 历史（7 个，按时间顺序）

```
f7d3c8d docs(f001): spec v4 — 加客户补充章节，CVO 8 项决策提炼
0e79cb3 docs(plans): f001 实施计划 — 15 task TDD 覆盖 21 AC
9ffe7fa chore: add .gitignore
a0d9c15 docs(f001): spec v3 — schema closure (文若 round-2 闭环)
2922781 docs(f001): spec v2 — 文若 review 修订
10674b1 docs(backlog): F001-F004 roadmap
d0be89f chore: initial commit - 项目骨架 + F001 spec
```

---

## Why

铲屎官 2026-07-24 03:21 UTC 任命奉孝为代码飞轮项目核心组织者，要求充分调用四只猫的特长完成 M1 代码仓日志解析模块。Phase 0 已完成：

- spec 经文若两轮 review 闭环（Must-Fix 4 + Should-Fix 5 → schema closure 4 项）
- 实施计划按 writing-plans skill 规范产出（15 个 bite-sized TDD task）
- 客户补充章节提炼 8 项 CVO 决策（每条三重锚定：spec 章节 + AC + task 编号）

按家规铁律「no self-review，跨家族优先」，进入实施阶段前必须由跨家族 reviewer 审查 spec + plan 是否：
1. 真实覆盖铲屎官需求（愿景验证）
2. 数据契约 schema 闭环（无 placeholder/类型不一致/missing field）
3. 实施计划 task 粒度合理（每 task 可独立实施 + review，TDD red-green-commit 节奏清晰）
4. 跨家族风险点（云长擅长找 bug + 落地）有显式识别与缓解

---

## Original Requirements（请 reviewer 对照判断）

**来源文档**：`需求.txt` + 对话历史 4 条 CVO 决策消息

**铲屎官原话摘录（≤5 行）**：

1. 03:21 UTC："你是这个项目的核心组织者，你要充分调用 @文若 @云长 @子龙 @孝直 的各自特长协助完成这个项目，需求描述我放到文档了，可以开始干了"
2. 03:44 UTC："企业内部平台；第一版要支持C和python语言；此外代码解析可以使用gitnexus工具，解析出来的代码仓的每条日志除了有文件位置、函数名、行号、相关历史案例推荐等确定性的信息外、还要有LLM介入给出打印日志的可能原因。之后高频的日志可以让用户决定后再存入数据库吧，不需要全部存入"
3. 06:18 UTC："我会提供LLM的key，你通过配置文件让我有地方写入key就行；Q2的选择A，其中top N的N采用配置指定"
4. 07:56 UTC："按照推荐的来吧"（同意先 review 再开 worktree）

**Reviewer 请重点对照**：客户补充章节（spec §八）8 条决策是否完整覆盖上述 1-3 条原话的所有要求；spec 各章节落地是否与决策一致。

---

## Architecture Ownership（F191）

- **Architecture cell**: M1 代码仓日志解析模块（4 子单元：Repo Registrar / Log Point Finder / LLM Hypothesis Generator / Candidate Staging）
- **Map delta**: **new cell required** — M1 是新模块，不在现有架构图中。本 PR 产出 spec + plan，未触及代码；后续 T1-T15 实施时新增 `packages/m1/` 子包，对应架构图新增 M1 cell
- **Why**: 代码飞轮项目四模块流水线（M1→M2→M3+M4）依赖同一份"代码仓日志埋点图谱"作为底座。M1 是底座的根，必须在 M2/M3/M4 启动前稳定 schema。

**Reviewer 视角**：本 PR 只产出文档，**无代码 diff**——Map delta 应与之一致（spec 声明新增 cell，diff 不含代码）。如发现 diff 中有代码改动，立即 flag。

---

## Tradeoff（本 PR 关键设计权衡）

| 决策点 | 选择 | 理由 | 放弃的方案 |
|--------|------|------|------------|
| 实现语言 | Python 3.11+ | gitnexus 是 MCP，Python MCP client 顺；tree-sitter Python 生态成熟（py-tree-sitter / tree-sitter-languages） | TypeScript（SOP TS 基线仅适用 F003 前端 UI 子模块） |
| Graph backend | gitnexus | 已是成熟 graph backend，不重复造轮子 | 自建 AST + call graph（工作量过大 + 重复） |
| 入库策略 | 两阶段（候选池 → 用户 confirm → 主表） | 大型仓数千条埋点不全部入库，噪音 + 存储 + 后续分析成本爆炸 | 全量入库（CVO 否决） |
| Top N 判定 | 用户 UI 勾选（选项 A）+ Top N 配置指定 | 用户保留控制权，Top N 只是辅助排序 | 算法自动入库（CVO 否决） |
| 缓存键 | `hash(log_template + enclosing_function_signature + model_name + extractor_version)` | schema/extractor 升级时旧缓存自动失效 | 不含 extractor_version（旧缓存污染新解析结果） |
| LLM 脱敏 | LogSanitizer 强制扫描，零敏感字段命中才发 LLM | 企业内部平台合规硬要求；LLM 幻觉 + 密钥外发风险 | 信任 LLM provider 端过滤（不可控） |
| 持久化默认 | TTL=0（用户 opt-in 才入库） | P0 铁律：用户可见、可追溯、可恢复预期的数据默认持久化 | TTL=∞（违反 P0） |

---

## Open Questions

### 技术 OQ（给 reviewer）

- **OQ-1**: 6 种日志 pattern 的 confidence_score 设定（logging=1.0 / 裸 print=0.5 / 自定义=0.7）是否合理？阈值过低导致主表噪音，过高导致漏识别。
- **OQ-2**: tree-sitter Layer 2 精筛的误识别率目标 < 5%（AC-5），fixture 仓设计是否足够覆盖真实仓的边界 case？
- **OQ-3**: `repo_ingest_lock` 状态机 `running → done/failed` 的 `failed` 自动触发条件（ingest_timeout_minutes=30）是否合理？太短 → 大仓误判 failed；太长 → lock 泄漏。
- **OQ-4**: LLM 缓存键的 `enclosing_function_signature` 是否足够稳定？函数重命名后缓存失效（合理），但函数体不变只改签名 = 缓存失效（可能浪费）。
- **OQ-5**: 15 个 task 的 TDD 粒度是否合理？T7（tree-sitter + fixture 仓）和 T9（Unit C LogSanitizer + LLM）是否应该再拆？T10 缓存键逻辑是否应该并入 T9？

### 价值 OQ（给铲屎官）

无。CVO 8 项决策已在客户补充章节锁定，剩余 OQ 全是技术实现层面，由 reviewer 判断即可。

---

## 自检证据

### Quality-gate 报告摘要

- ✅ **AC 覆盖**：21/21 AC 全部映射到 task（plan 末尾 Self-Review 段附 AC→Task 矩阵）
- ✅ **Placeholder 扫描**：零命中（无 TBD / TODO / "fill in" / "similar to Task N"）
- ✅ **类型一致性**：LogPoint / LLMHypothesis / CaseRef / CallContext / RepoIngestLock / AuditLog dataclass 字段名 + 类型在 spec §三 与 plan 各 task 一致；enums.py 7 个 ACTION_* 常量在 T3 定义后 T12 audit_log 引用一致
- ✅ **客户补充章节**：8 条 CVO 决策三重锚定（spec 章节 + AC + task 编号），决策追溯矩阵一表全览

### 测试命令输出

N/A —— 本 PR 是文档（spec + plan），无代码测试。T1-T15 实施时每 task 跑 `pytest -v` + `ruff check`，每 task commit 时测试全绿。

### 根目录工件闸门

```
$ git status --short | grep -E '^\s*[ADMR?]+\s+[^/]+\.(png|jpe?g|webp|gif|webm|mp4|mov|wav|pdf|pen)$'
OK - 根目录工件闸门通过

$ git diff --name-only $(git rev-list --max-parents=0 HEAD)...HEAD
.gitignore
BACKLOG.md
docs/features/F001-代码仓日志解析.md
docs/superpowers/plans/2026-07-24-f001-code-repo-log-parse.md
```

所有改动都在 `docs/` 或根目录配置文件，无散落的 png/jpg/pdf/pen 等媒体或设计工件。

### Worktree 工具落点自检

```
$ git status
On branch master
Changes not staged for commit:
	modified:   .cat-cafe/governance-bootstrap-report.json
	modified:   .cat-cafe/skills-state.json
```

主仓库 master 分支，无代码 diff。`.cat-cafe/*.json` 是 cat-cafe runtime 自动同步状态，非本 PR 改动，不入 commit。

---

## Reviewer 视角重点（请 @云长 关注）

### 1. 愿景验证（对照 Original Requirements）

铲屎官原话 4 条是否在 spec 客户补充章节 C-1 ~ C-8 全覆盖？是否有遗漏或偏离？

### 2. Schema 闭环（云长擅长找 bug）

- LogPoint / LLMHypothesis / CaseRef / CallContext / RepoIngestLock / AuditLog 6 个 dataclass 字段是否完整、类型一致？
- `ingestion_status` 状态机：`candidate → confirmed → ingested`，可逆（`revoke_ingestion`）——状态转换是否有遗漏？
- `repo_ingest_lock` 状态机：`running → done/failed`——`failed` 后能否重试？是否需要 `force_release_lock` admin 接口？
- 缓存键 4 字段（log_template + enclosing_function_signature + model_name + extractor_version）——是否还需要加 `repo_id`？同仓不同函数的相同 log_template 是否应该分开缓存？

### 3. 实施计划落地（云长擅长 coding 落地）

- 15 个 task 的依赖关系是否清晰？T1 → T2 → T3（契约） → T4（存储） → T5（gitnexus） → T6-T11（4 子单元） → T12-T13（审计 + metrics） → T14（API） → T15（review handoff）—— 有无循环依赖或缺失前置？
- 每 task 的 TDD 节奏（red test → run fail → minimal impl → run pass → lint → commit）是否完整？有无 task 缺少 lint 步骤？
- fixture 仓 7 个（6 含日志 + 1 decoy）是否覆盖 6 种 pattern × 2 种语言的所有组合？
- Global Constraints（worktree 铁律 / Redis 6398 / metrics 9100 / Python 基线 / file_path POSIX / TTL=0 P0）是否在每 task 显式提及？

### 4. 风险缓解（spec §Risk 表 10 项）

- LLM 幻觉风险：`llm_hypothesis` 标注为"参考假设"，M4 不作自动改代码依据——是否足够？
- 并发 ingest 同 repo：`repo_ingest_lock` 表 + 状态机—— `running` 状态超时自动 `failed` 的机制是否在 spec 显式说明？
- 候选池确认入主表后识别错误：`revoke_ingestion` first-class API + audit_log 记录撤销——撤销后 LogPoint 状态变回 `candidate` 还是直接删除？

### 5. 跨家族风险点（云长 Maine Coon/quality 族视角）

- Siamese（奉孝）容易边写边想、PoC 心态——spec 是否有"边写边想"残留？如某章节说"先这样，后续再改"？
- Maine Coon fallback 层数检测：spec 中是否有 ≥3 层 fallback？（如 LLM 失败 → 缓存 → 重试 → 默认 None，4 层——是否合理？）
- 是否有"创意-实现解耦"问题？如 spec 提出了某设计但实施计划 task 中无对应落地？

---

## Next Action

@云长 收到后请按以下步骤：

1. **拉取最新 master**（本 PR 已直接 commit 到 master，无 PR）
   ```bash
   git pull  # 或 git fetch && git checkout master && git pull
   ```

2. **Read 两个核心文件**：
   - `docs/features/F001-代码仓日志解析.md`（539 行 spec v4）
   - `docs/superpowers/plans/2026-07-24-f001-code-repo-log-parse.md`（4340 行实施计划）

3. **对照本 handoff 文档的 5 个 Reviewer 视角重点**做 review

4. **Review 输出**：建议在 `docs/decisions/F001-review-{云长}-round1.md` 写 review 报告，含：
   - Must-Fix（阻断实施）
   - Should-Fix（建议但非阻断）
   - Nits（小问题）
   - 通过 / 不通过 状态

5. **Review 通过后**：通知 @奉孝，奉孝开 worktree 进 subagent-driven-development 实施 T1-T15

### Review 沙盒约定

本 PR 是文档 review，不涉及代码运行，不需要 detached HEAD 沙盒。Reviewer 直接在 master 分支 Read 文件即可。如要写 review 报告，直接 commit 到 `docs/decisions/` 即可（无需 worktree——文档改动允许在主仓库 master 分支）。

---

## References

- spec: `docs/features/F001-代码仓日志解析.md`
- plan: `docs/superpowers/plans/2026-07-24-f001-code-repo-log-parse.md`
- backlog: `BACKLOG.md`
- 原始需求: `需求.txt`
- SOP: `docs/SOP.md`
- 客户补充章节决策追溯矩阵: spec §八

---

[奉孝/GLM-5.2🐾] Phase 0 交付物 ready for cross-family review.
