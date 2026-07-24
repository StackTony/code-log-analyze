"""pytest 全局 fixtures。"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).parent.parent


@pytest.fixture(scope="session")
def fixtures_dir() -> pathlib.Path:
    """fixture 代码仓根目录（后续 Unit B 测试用）。"""
    return ROOT / "tests" / "fixtures"
