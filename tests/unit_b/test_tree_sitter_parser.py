"""tree-sitter 解析器测试 — 给定 fixture 文件，能抽函数签名 + call sites。"""
from __future__ import annotations

import pathlib

from packages.m1.tree_sitter_parser import TreeSitterParser


def test_parse_python_logging_repo(fixtures_dir: pathlib.Path) -> None:
    parser = TreeSitterParser()
    parsed = parser.parse_file(fixtures_dir / "python_logging_repo" / "main.py", language="python")
    fn_names = [f.name for f in parsed.functions]
    assert "login" in fn_names
    assert "fail" in fn_names


def test_parse_c_printf_repo(fixtures_dir: pathlib.Path) -> None:
    parser = TreeSitterParser()
    parsed = parser.parse_file(fixtures_dir / "c_printf_repo" / "main.c", language="c")
    fn_names = [f.name for f in parsed.functions]
    assert "do_work" in fn_names


def test_call_sites_extracted(fixtures_dir: pathlib.Path) -> None:
    parser = TreeSitterParser()
    parsed = parser.parse_file(fixtures_dir / "python_logging_repo" / "main.py", language="python")
    # 应该能找到 LOG.info / LOG.warning / LOG.error / LOG.debug 调用
    callee_names = [c.callee_name for c in parsed.call_sites]
    assert "LOG.info" in callee_names or any("info" in n.lower() for n in callee_names)
