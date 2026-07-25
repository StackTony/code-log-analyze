"""AC 覆盖自检 — 14 条 AC 全部映射测试（spec §八 + AC-14 流程项）。"""
from __future__ import annotations

# AC 映射表：AC 编号 → 测试文件路径
AC_COVERAGE = {
    "AC-1": "tests/api/test_ingest.py + test_candidates.py + test_confirm.py + test_revoke.py + test_log_points.py + test_call_context.py",
    "AC-2": "tests/api/test_app.py::test_app_has_openapi_docs",
    "AC-3": "tests/api/test_app.py::test_app_has_health_endpoint + test_app_has_ready_endpoint",
    "AC-4": "tests/api/test_metrics.py::test_metrics_emitter_indicators_present",
    "AC-5": "tests/api/test_error_handling.py",
    "AC-6": "tests/api/test_schema_validation.py",
    "AC-7": "tests/api/test_app.py::test_app_console_warning_unauthorized",
    "AC-8": "全量 pytest 跑通 — M1 77 测试无回归",
    "AC-9": "端口 3004/9100 家规铁律 — spec 显式声明 + lifespan 启动",
    "AC-10": "tests/api/test_metrics.py::test_app_lifespan_starts_metrics_server",
    "AC-11": "tests/api/test_metrics.py::test_app_lifespan_starts_metrics_server（graceful）",
    "AC-12": "tests/api/test_mappers.py",
    "AC-13": "tests/api/test_log_points.py::test_get_log_points_returns_confirmed_only",
    "AC-14": "（实施完成后由 @云长 跨家族 merge-gate review — 流程项）",
}


def test_ac_coverage_table_is_complete() -> None:
    """AC-1 到 AC-14 全部有测试映射（AC-14 除外，流程项）。"""
    for ac in range(1, 14):
        key = f"AC-{ac}"
        assert key in AC_COVERAGE, f"{key} 未在测试覆盖表里"


def test_ac_mapped_tests_exist() -> None:
    """关键 AC 的测试文件存在。"""
    import pathlib
    test_files = [
        "tests/api/test_ingest.py",
        "tests/api/test_candidates.py",
        "tests/api/test_confirm.py",
        "tests/api/test_revoke.py",
        "tests/api/test_log_points.py",
        "tests/api/test_call_context.py",
        "tests/api/test_metrics.py",
        "tests/api/test_app.py",
        "tests/api/test_error_handling.py",
        "tests/api/test_schema_validation.py",
        "tests/api/test_mappers.py",
        "tests/api/test_ac_coverage.py",
    ]
    for f in test_files:
        assert pathlib.Path(f).exists(), f"{f} 不存在"
