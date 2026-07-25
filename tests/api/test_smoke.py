"""Smoke test — packages.api 子包可 import。"""
# ruff: noqa: I001, RUF100
from __future__ import annotations


def test_api_package_importable() -> None:
    """packages.api 子包存在（暂无内容）。"""
    import packages.api  # noqa: F401
    import packages.api.schemas  # noqa: F401
    import packages.api.routes  # noqa: F401
    import packages.api.mappers  # noqa: F401
