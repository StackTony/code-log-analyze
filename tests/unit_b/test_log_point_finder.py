"""Unit B 测试 — AC-3 / AC-4 / AC-5。"""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest

from packages.contracts.enums import LANGUAGE_C, LANGUAGE_PYTHON
from packages.m1.unit_b_log_point_finder import LogPointFinder


@pytest.fixture()
def finder_with_mock_gn():
    """finder 用 mock gitnexus（避免真实建图），Layer 2 直接跑 tree-sitter。"""
    gn = MagicMock()
    # cypher 返回空（fixture 不走 gitnexus，直接走 fixture 文件 + tree-sitter）
    gn.cypher.return_value = []
    return LogPointFinder(gitnexus=gn)


def test_python_logging_recognized(fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_logging_repo",
        language=LANGUAGE_PYTHON,
    )
    # 4 个 LOG 调用
    assert len(points) >= 4
    for p in points:
        assert p.framework_hint == "logging"
        assert p.confidence_score == 1.0
        assert p.log_level in {"INFO", "WARNING", "ERROR", "DEBUG"}


def test_python_loguru_recognized(fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_loguru_repo",
        language=LANGUAGE_PYTHON,
    )
    assert len(points) >= 2
    assert all(p.framework_hint == "loguru" for p in points)


def test_python_print_default_not_recognized(
    fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder
) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_print_repo",
        language=LANGUAGE_PYTHON,
        include_print=False,
    )
    # 默认不识别 print
    assert len(points) == 0


def test_python_print_with_include_print_true(
    fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder
) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_print_repo",
        language=LANGUAGE_PYTHON,
        include_print=True,
    )
    assert len(points) >= 2
    assert all(p.confidence_score == 0.5 for p in points)
    assert all(p.framework_hint == "print" for p in points)


def test_c_printf_recognized(fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "c_printf_repo",
        language=LANGUAGE_C,
    )
    assert len(points) >= 2  # printf + fprintf
    assert all(p.confidence_score == 1.0 for p in points)


def test_c_syslog_recognized(fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "c_syslog_repo",
        language=LANGUAGE_C,
    )
    assert len(points) >= 2
    assert all(p.framework_hint == "syslog" for p in points)


def test_c_custom_log_function_recognized(
    fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder
) -> None:
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "c_custom_log_repo",
        language=LANGUAGE_C,
    )
    # app_log_error / app_log_debug 命中 ^.*_(log|error|debug|trace).*$
    assert len(points) >= 2
    assert all(p.framework_hint == "custom" for p in points)
    assert all(p.confidence_score == 0.7 for p in points)


def test_decoy_repo_filters_out_business_functions(
    fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder
) -> None:
    """AC-5：format_error/handleError 等业务函数被过滤（误识别率 < 5%）。"""
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "decoy_repo",
        language=LANGUAGE_PYTHON,
    )
    # decoy_repo 里只有 LoginService.login 里的 logging.info 是真日志调用
    # format_error/handleError 是业务函数，不该被识别
    # 注意 function_signature 是调用点所在函数的签名，不是 callee 名
    # 真正的 log point 只该有 1 个（LoginService.login 内的 logging.info）
    assert len(points) == 1, f"误识别: {points}"
    assert "login" in points[0].function_signature


def test_deduplication_same_file_line(fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder) -> None:
    """AC-4：同 (repo_id, file_path, line_start) 只一条。"""
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_logging_repo",
        language=LANGUAGE_PYTHON,
    )
    keys = [(p.repo_id, p.file_path, p.line_start) for p in points]
    assert len(keys) == len(set(keys))


def test_file_path_posix_style_on_windows(
    fixtures_dir: pathlib.Path, finder_with_mock_gn: LogPointFinder
) -> None:
    """AC-15：file_path 统一 POSIX 风格。"""
    points = finder_with_mock_gn.find(
        repo_id="repo-1",
        repo_path=fixtures_dir / "python_logging_repo",
        language=LANGUAGE_PYTHON,
    )
    for p in points:
        assert "\\" not in p.file_path
