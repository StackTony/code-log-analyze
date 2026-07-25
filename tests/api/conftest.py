"""pytest fixtures for tests/api/."""
from __future__ import annotations

import os
import time
from collections.abc import Generator

import pytest
from prometheus_client import start_http_server
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


@pytest.fixture()
def metrics_server() -> Generator[str, None, None]:
    """独立 metrics server fixture（9101 端口，避免与 app lifespan 9100 冲突 — 云长 OQ-2）。

    注：Windows 需要使用 spawn context 且非 daemon 模式启动 prometheus HTTP server。
    """
    import multiprocessing

    import httpx

    # Use spawn context for Windows compatibility
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(target=start_http_server, args=(9101,))
    proc.start()

    # Poll until server is ready (Windows spawn takes time)
    url = "http://localhost:9101"
    max_wait = 5.0
    interval = 0.3
    elapsed = 0.0
    while elapsed < max_wait:
        try:
            r = httpx.get(f"{url}/", timeout=1.0)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(interval)
        elapsed += interval

    yield url

    # Cleanup
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=3)


# Hook to reset between fixture setup and test execution
@pytest.hookimpl(trylast=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Reset prometheus registry right before test execution (after all fixtures setup)."""
    _reset_prometheus_registry()
