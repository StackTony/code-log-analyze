"""pytest fixtures for tests/api/."""
from __future__ import annotations

import os

import pytest
from prometheus_client.core import REGISTRY as DEFAULT_REGISTRY

# 在导入 deps 模块前设置测试用的 postgres_dsn
# 避免 get_service 默认值在 module load 时触发 RuntimeError
os.environ.setdefault("CODEFLY_PG_DSN", "sqlite:///:memory:")


def _reset_prometheus_registry() -> None:
    """Unregister all m1_* collectors from prometheus REGISTRY."""
    # Find all m1 collectors (those that have at least one name starting with 'm1_')
    m1_collectors = [
        collector
        for collector, names in list(DEFAULT_REGISTRY._collector_to_names.items())
        if any(name.startswith("m1_") for name in names)
    ]
    # Unregister them
    for collector in m1_collectors:
        DEFAULT_REGISTRY.unregister(collector)


@pytest.fixture(autouse=True)
def reset_prometheus_registry() -> None:
    """Reset prometheus REGISTRY before and after each test to avoid duplicated timeseries errors.

    Workaround: MetricsEmitter registers gauges/counters/histograms into the default REGISTRY
    during construction. When multiple TestClient(app) instances are created in one test
    session (one per test), each TestClient's lifespan starts a fresh MetricsEmitter via
    get_service, which tries to re-register the same metric names → "Duplicated timeseries"
    error. Unregistering all m1_* collectors before/after each test prevents this.
    """
    _reset_prometheus_registry()  # Clear before test
    yield
    _reset_prometheus_registry()  # Clear after test


# Hook to reset between fixture setup and test execution
@pytest.hookimpl(trylast=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Reset prometheus registry right before test execution (after all fixtures setup)."""
    _reset_prometheus_registry()
