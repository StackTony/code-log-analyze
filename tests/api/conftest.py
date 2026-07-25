"""pytest fixtures for tests/api/."""
from __future__ import annotations

import os

# 在导入 deps 模块前设置测试用的 postgres_dsn
# 避免 get_service 默认值在 module load 时触发 RuntimeError
os.environ.setdefault("CODEFLY_PG_DSN", "sqlite:///:memory:")
