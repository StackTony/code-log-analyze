# 代码飞轮（Code Flywheel）

日志智能分析平台 — 从代码仓日志埋点解析到 LLM 辅助改进的闭环。

## 当前状态

- **F001 代码仓日志解析模块**：spec v4 + 实施计划 v1 完成，T1-T14 已实施，77 测试全绿，待 merge-gate review
- **F002-F004**：backlog，等 F001 落地后启动各自 spec

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
py -m pytest -v

# Lint
py -m ruff check .
```

## 协作

- 主 owner: @奉孝 (ragdoll-pa82, GLM-5.2)
- Reviewer: @云长 (跨家族，GLM-5.1)
- 审计: @孝直 (Qwen-3.7)
- spec 详见 docs/features/F001-*.md
- 实施计划详见 docs/superpowers/plans/2026-07-24-f001-*.md