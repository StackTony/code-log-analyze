"""Smoke test — 验证 Python 工程基线能跑通。"""
from __future__ import annotations


def test_pytest_runs() -> None:
    assert True


def test_packages_importable() -> None:
    import packages
    assert packages.__name__ == "packages"
