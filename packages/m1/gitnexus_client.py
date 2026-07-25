"""gitnexus CLI 客户端封装 — 用 subprocess 调用，不依赖 MCP stdio 运行时复杂度。"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any


class GitNexusError(Exception):
    pass


class GitNexusClient:
    """gitnexus CLI 客户端。所有 gitnexus 调用走这里，便于 mock + 跨平台。"""

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary or shutil.which("gitnexus") or "gitnexus"

    def _run(self, args: list[str]) -> str:
        cmd = [self._binary, *args]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=600,
            encoding='utf-8', errors='replace'
        )
        if result.returncode != 0:
            raise GitNexusError(f"gitnexus {args[0]} failed (cmd={cmd}): {result.stderr}")
        return result.stdout

    def analyze(self, repo_path: str, alias: str) -> None:
        """gitnexus analyze --name <alias> <path>"""
        self._run(["analyze", "--name", alias, repo_path])

    def cypher(self, query: str, repo_alias: str | None = None) -> list[dict[str, str]]:
        """gitnexus cypher <query> — 解析 markdown 表为 dict 列表。"""
        args = ["cypher", query]
        if repo_alias:
            args.extend(["-r", repo_alias])
        stdout = self._run(args)
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise GitNexusError(f"cypher output not JSON: {e}") from e
        return self._parse_markdown_table(payload.get("markdown", ""))

    @staticmethod
    def _parse_markdown_table(markdown: str) -> list[dict[str, str]]:
        """把 gitnexus cypher 输出的 markdown 表解析为 dict 列表。"""
        lines = [ln.strip() for ln in markdown.splitlines() if ln.strip()]
        if not lines:
            return []
        # 找表头
        header_idx = next((i for i, ln in enumerate(lines) if "|" in ln), -1)
        if header_idx == -1:
            return []
        headers = [h.strip() for h in lines[header_idx].strip("|").split("|")]
        results: list[dict[str, str]] = []
        for ln in lines[header_idx + 2:]:  # 跳过分隔行 | --- |
            if "|" not in ln:
                continue
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) != len(headers):
                continue
            results.append(dict(zip(headers, cells, strict=False)))
        return results

    def context(self, symbol_name: str, repo_alias: str | None = None) -> dict[str, Any]:
        args = ["context", symbol_name]
        if repo_alias:
            args.extend(["-r", repo_alias])
        stdout = self._run(args)
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            raise GitNexusError(f"context output not JSON: {e}") from e

    def list_repos(self) -> list[dict[str, str]]:
        stdout = self._run(["list"])
        # 解析 "Indexed Repositories (N)\n\n  <alias>\n    Path: ...\n    Indexed: ..."
        # gitnexus list 输出形如：
        # Indexed Repositories (1)
        #
        #   GenericAgent
        #     Path: /path/to/repo
        #     Commit: ...
        #     Indexed: 2024-...
        matches = re.finditer(r"^\s{2,}(\S+)\n\s+Path:\s*(\S+)(?:\n\s+Indexed:\s*(.+))?", stdout, re.MULTILINE)
        return [{"alias": m.group(1), "path": m.group(2), "indexed_at": m.group(3)} for m in matches]
