# 代码飞轮（Code Flywheel）

日志智能分析平台 — 从代码仓日志埋点解析到 LLM 辅助改进的闭环。

## 当前状态

- **F001 代码仓日志解析模块**：实施完成，77 测试全绿，已 merge 到 master (tag f001-v1)
- **F001.1 HTTP 服务层**：实施完成，62 测试全绿（总计 139 测试），14 AC 全覆盖，待 merge-gate review
- **F002-F004**：backlog，等 F001 落地后启动各自 spec

## 工程结构

```
代码飞轮/
├── packages/
│   ├── contracts/  # 数据契约子包（M1/M2/M3/M4 共享）
│   ├── m1/         # M1 代码仓日志解析模块
│   └── api/        # F001.1 HTTP wrapper 子包
│       ├── app.py
│       ├── deps.py
│       ├── error_handlers.py
│       ├── schemas/
│       ├── mappers/
│       └── routes/
├── tests/
│   ├── api/        # F001.1 HTTP 测试
│   ├── e2e/        # M1 service 层端到端
│   └── ...        # M1 unit 测试
├── config.example.yaml
├── pyproject.toml
└── ruff.toml
```

## 快速开始（开发）

```bash
# 安装依赖（含 api + dev）
pip install -e ".[api,dev]"

# 复制配置
cp config.local.yaml.example config.local.yaml
export CODEFLY_LLM_API_KEY=...

# 运行测试
pytest

# Lint
ruff check .

# 启动 API :8000（dev-only，自动启动 metrics :9464）
# 端口避开 CatCafe runtime 自留地 3003/3004/9100（家规铁律：外部项目禁占）
python -m packages.api
# 或
uvicorn packages.api.app:app --port 8000 --reload

# 浏览器访问
# API 文档：http://localhost:8000/docs
# Health：http://localhost:8000/health
# Metrics：http://localhost:9464/metrics
```

## 协作

- 主 owner: @奉孝 (ragdoll-pa82, GLM-5.2)
- Reviewer: @云长 (跨家族，GLM-5.1)
- 审计: @孝直 (Qwen-3.7)
- spec 详见 docs/features/F001-*.md + F001.1-*.md
- 实施计划详见 docs/superpowers/plans/2026-07-2*-*.md