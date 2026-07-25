"""AC 覆盖表 — 21 条 AC 映射到测试。

AC-21 是流程项（跨家族 review），不在测试覆盖。
"""
from __future__ import annotations

AC_COVERAGE = {
    "AC-1": "tests/unit_a/test_repo_registrar.py::test_ingest_local_path_returns_repo_id",
    "AC-2": "tests/unit_a/test_repo_registrar.py::test_ingest_rejects_dotdot_path",
    "AC-3": "tests/unit_b/test_log_point_finder.py::test_python_logging_recognized",
    "AC-4": "tests/unit_b/test_log_point_finder.py::test_deduplication_same_file_line",
    "AC-5": "tests/unit_b/test_log_point_finder.py::test_decoy_repo_filters_out_business_functions",
    "AC-6": "tests/unit_c/test_llm_hypothesis_generator.py::test_cache_hit_skips_llm_call",
    "AC-7": "tests/unit_c/test_llm_hypothesis_generator.py::test_llm_failure_keeps_hypothesis_none",
    "AC-8": "tests/unit_c/test_log_sanitizer.py::test_zero_hits_required_for_llm_call",
    "AC-9": "tests/unit_d/test_candidate_staging.py::test_revoke_ingestion_back_to_candidate",
    "AC-10": "tests/unit_d/test_candidate_staging.py::test_list_candidates_default_only_top_n",
    "AC-11": "tests/unit_d/test_candidate_staging.py::test_confirm_ingestion_moves_to_main",
    "AC-12": "tests/unit_a/test_config_loader.py::test_env_var_overrides_yaml",
    "AC-13": "tests/unit_d/test_candidate_staging.py::test_query_log_points_returns_only_ingested",
    "AC-14": "tests/unit_a/test_repo_registrar.py::test_concurrent_ingest_same_repo_returns_running",
    "AC-15": "tests/unit_b/test_log_point_finder.py::test_file_path_posix_style_on_windows",
    "AC-16": "tests/e2e/test_repo_log_graph_service.py::test_confirm_then_query",
    "AC-17": "tests/unit_d/test_candidate_staging.py::test_audit_log_written_on_confirm",
    "AC-18": "tests/metrics/test_metrics_emitter.py::test_candidate_pool_size_metric",
    "AC-19": "tests/contracts/test_log_point.py::test_log_point_roundtrip",
    "AC-20": "tests/unit_a/test_repo_registrar.py::test_incremental_not_implemented",
    "AC-21": "(实施完成后由 @云长 跨家族 review - 流程项，不在测试覆盖)",
}


def test_ac_coverage_table_is_complete() -> None:
    """AC-1 到 AC-20 全部有测试映射（AC-21 除外，流程项）。"""
    for ac in range(1, 21):  # 1-20，AC-21 是流程项
        key = f"AC-{ac}"
        assert key in AC_COVERAGE, f"{key} 未在测试覆盖表里"


def test_ac_mapped_tests_exist() -> None:
    """每个 AC 映射的测试路径真实存在。"""
    import os

    for ac, test_path in AC_COVERAGE.items():
        if "(" in test_path and "流程项" in test_path:  # 跳过 AC-21 流程项
            continue
        file_path = test_path.split("::")[0]
        # 使用 worktree 根目录作为基准
        base_dir = os.path.dirname(os.path.dirname(__file__))
        full_path = os.path.join(base_dir, file_path)
        assert os.path.exists(full_path), f"{ac}: {file_path} 不存在"
