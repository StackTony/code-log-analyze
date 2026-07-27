"""F002 M2 — LogPointMatcher（spec §三 + §十 + AC-2）。

通过 `log_message_template` hash 匹配 M1 LogPoint 主表，匹配率 ≥ 70%。

**两侧命名约定不一致问题**（spec §十）：
  - M1 从 code 仓 AST 提取模板用**真实变量名**（如 `"User {uid} logged in"`）
  - M2 LogParser 从运行时日志提取模板用**编号占位符**（如 `"User {var_0} logged in"`）

直接哈希两侧不一致 → 漏匹配。归一化为**结构签名**（剥掉占位符名/编号，统一为 `{x}`）
后哈希，两侧命中同一签名。

匹配算法（spec §十）：
  1. LogParser 从日志原文提取模板
  2. LogPointMatcher 计算 `hash(归一化签名)` 在 M1 主表查询
  3. 命中 → 关联 log_point_id；未命中 → log_point_id=None（Phase 2 仍可分析，但不回写 M1）
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from packages.contracts.log_entry import LogEntry
from packages.contracts.log_point import LogPoint


# 匹配 `{任意字符}` 占位符（M1 `{uid}` / M2 `{var_0}` / 第三方 `{host}` 都覆盖）
_PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")


def _normalize_to_signature(template: str) -> str:
    """归一化模板为结构签名。

    把所有 `{name}` 占位符替换为 `{x}`，剥掉变量名/编号差异。

    >>> _normalize_to_signature("User {uid} logged in")
    'User {x} logged in'
    >>> _normalize_to_signature("User {var_0} logged in")
    'User {x} logged in'
    >>> _normalize_to_signature("User {uid} from {ip}")
    'User {x} from {x}'
    """
    return _PLACEHOLDER_RE.sub("{x}", template)


def _hash_signature(signature: str) -> str:
    """对结构签名求 sha256 hex 哈希。

    >>> _hash_signature("User {x} logged in") == _hash_signature("User {x} logged in")
    True
    """
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


class LogPointIndex:
    """M1 LogPoint 主表索引抽象（实现端从 M1 主表读入并建索引）。

    F002 实施阶段补 storage 层注入实现（spec §五 文件结构 log_point_matcher.py）。
    本类作为协议接口存在，避免 LogPointMatcher 直接耦合 SQLAlchemy。
    """

    def lookup_by_template_hash(self, template_hash: str) -> LogPoint | None:
        """根据归一化模板哈希查 LogPoint，未命中返回 None。"""
        raise NotImplementedError


class NullLogPointIndex(LogPointIndex):
    """空索引：所有 lookup 返回 None。

    用途：无 repo_id 场景（text-only analyze_logs）的 fallback matcher。
    """

    def lookup_by_template_hash(self, template_hash: str) -> LogPoint | None:  # type: ignore[override]
        return None


@dataclass(frozen=True)
class MatchResult:
    """单条 LogEntry 匹配结果。"""
    entry: LogEntry
    template_hash: str | None  # entry 模板为 None 时为 None
    log_point: LogPoint | None  # 未命中时为 None


class LogPointMatcher:
    """日志条目 → M1 LogPoint 匹配器（spec AC-2）。

    用法：
        index = StorageBackedLogPointIndex(repo_id, session_factory)
        matcher = LogPointMatcher(index)
        results = matcher.match(entries)
        rate = matcher.match_rate(results)
    """

    def __init__(self, index: LogPointIndex) -> None:
        self._index = index

    def match(self, entries: list[LogEntry]) -> list[MatchResult]:
        """对每个 LogEntry 计算 hash 并查 M1 索引，返回匹配结果列表。

        Args:
            entries: LogParser 解析出的 LogEntry 列表

        Returns:
            list[MatchResult]，顺序与 entries 一致
        """
        results: list[MatchResult] = []
        for entry in entries:
            template = entry.log_message_template
            if template is None:
                results.append(MatchResult(entry=entry, template_hash=None, log_point=None))
                continue

            sig = _normalize_to_signature(template)
            h = _hash_signature(sig)
            log_point = self._index.lookup_by_template_hash(h)
            results.append(MatchResult(entry=entry, template_hash=h, log_point=log_point))
        return results

    def match_rate(self, results: list[MatchResult]) -> float:
        """计算匹配率（命中数 / 总数）。

        AC-2 fixture 验证 ≥ 0.70。

        >>> matcher = LogPointMatcher(EmptyIndex())
        >>> matcher.match_rate([])
        0.0
        """
        if not results:
            return 0.0
        hits = sum(1 for r in results if r.log_point is not None)
        return hits / len(results)
