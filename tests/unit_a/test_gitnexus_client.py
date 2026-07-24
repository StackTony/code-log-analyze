"""gitnexus client 测试 — 用 subprocess mock 验证 CLI 调用。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from packages.m1.gitnexus_client import GitNexusClient


def test_analyze_invokes_gitnexus_cli(tmp_path) -> None:
    client = GitNexusClient()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        client.analyze(repo_path=str(tmp_path), alias="test-repo")
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "gitnexus" in cmd[0] or cmd[0].endswith("gitnexus")
        assert "analyze" in cmd
        assert "--name" in cmd


def test_cypher_parses_markdown_table_to_dicts() -> None:
    client = GitNexusClient()
    fake_output = json.dumps({
        "markdown": "| caller | callee |\n| --- | --- |\n| foo | bar |",
        "row_count": 1,
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
        results = client.cypher("MATCH (a)-[:CALLS]->(b) RETURN a, b", repo_alias="r")
        assert len(results) == 1
        assert results[0]["caller"] == "foo"
        assert results[0]["callee"] == "bar"


def test_list_repos_returns_alias_list() -> None:
    client = GitNexusClient()
    fake_output = "\nIndexed Repositories (1)\n\n  GenericAgent\n    Path: ...\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
        repos = client.list_repos()
        assert "GenericAgent" in repos


def test_context_returns_symbol_info() -> None:
    client = GitNexusClient()
    fake_output = json.dumps({
        "name": "login",
        "filePath": "src/app.py",
        "kind": "Function",
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
        result = client.context(symbol_name="login", repo_alias="r")
        assert result["name"] == "login"
        assert result["filePath"] == "src/app.py"
