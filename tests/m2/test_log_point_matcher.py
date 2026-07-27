"""F002 M2 — LogPointMatcher 测试（spec AC-2）。

验证 `log_message_template` hash 匹配 M1 LogPoint 主表，匹配率 ≥ 70%。

核心问题：M1 从 code 仓 AST 提取模板用**真实变量名**（如 `{uid}`），
M2 LogParser 从运行时日志提取模板用**编号占位符**（如 `{var_0}`）。
两侧命名约定不一致 → 必须归一化为**结构签名**后再哈希。
"""
from __future__ import annotations

from packages.contracts.log_entry import LogEntry
from packages.contracts.log_point import LogPoint
from packages.m2.log_point_matcher import (
    LogPointIndex,
    LogPointMatcher,
    MatchResult,
    _hash_signature,
    _normalize_to_signature,
)


class FakeLogPointIndex(LogPointIndex):
    """测试用 in-memory 索引。"""

    def __init__(self, by_hash: dict[str, LogPoint]) -> None:
        self._by_hash = by_hash

    def lookup_by_template_hash(self, template_hash: str) -> LogPoint | None:
        return self._by_hash.get(template_hash)


def _make_entry(template: str | None, raw_text: str = "stub") -> LogEntry:
    """构造测试用 LogEntry。"""
    import uuid

    return LogEntry(
        line_id=str(uuid.uuid4()),
        raw_text=raw_text,
        timestamp=None,
        level=None,
        log_message_template=template,
        variables={},
        source_file=None,
        source_line=None,
    )


def _make_log_point(template: str) -> LogPoint:
    """构造测试用 LogPoint（最小字段集）。"""
    from datetime import datetime

    return LogPoint(
        id="lp-1",
        repo_id="repo-1",
        git_commit_sha="sha-1",
        extractor_version="v1",
        file_path="app/auth.py",
        function_signature="login()",
        line_start=10,
        line_end=10,
        language="python",
        log_level="INFO",
        log_message_template=template,
        log_message_variables=["uid"],
        framework_hint="logging",
        confidence_score=0.9,
        enclosing_class=None,
        call_chain_to_entry=[],
        enclosing_community=None,
        first_seen_at=datetime(2026, 7, 27, 0, 0, 0),
        last_seen_at=datetime(2026, 7, 27, 0, 0, 0),
    )


class TestNormalizeToSignature:
    """template 归一化为结构签名（剥掉占位符名/编号）。"""

    def test_named_placeholder_stripped(self) -> None:
        """M1 仓内样式 `{uid}` → `{x}`。"""
        sig = _normalize_to_signature("User {uid} logged in")
        assert sig == "User {x} logged in"

    def test_positional_placeholder_stripped(self) -> None:
        """M2 LogParser 样式 `{var_0}` → `{x}`。"""
        sig = _normalize_to_signature("User {var_0} logged in")
        assert sig == "User {x} logged in"

    def test_multiple_placeholders_stripped_unified(self) -> None:
        """多占位符统一为 `{x}` 重复。"""
        sig = _normalize_to_signature("User {uid} from {ip} session {sid}")
        assert sig == "User {x} from {x} session {x}"

    def test_no_placeholder_unchanged(self) -> None:
        """无占位符模板原样返回。"""
        sig = _normalize_to_signature("system ready")
        assert sig == "system ready"

    def test_idempotent(self) -> None:
        """已归一化的模板再归一化不变。"""
        once = _normalize_to_signature("User {uid} logged in")
        twice = _normalize_to_signature(once)
        assert once == twice

    def test_m1_m2_style_collide_to_same_signature(self) -> None:
        """关键：M1 `{uid}` 与 M2 `{var_0}` 归一化为同一签名。"""
        m1_style = _normalize_to_signature("User {uid} logged in")
        m2_style = _normalize_to_signature("User {var_0} logged in")
        assert m1_style == m2_style


class TestHashSignature:
    """结构签名哈希。"""

    def test_deterministic(self) -> None:
        """同一签名 → 同一哈希。"""
        h1 = _hash_signature("User {x} logged in")
        h2 = _hash_signature("User {x} logged in")
        assert h1 == h2

    def test_different_signatures_different_hashes(self) -> None:
        """不同签名 → 不同哈希。"""
        h1 = _hash_signature("User {x} logged in")
        h2 = _hash_signature("User {x} from {x}")
        assert h1 != h2

    def test_returns_hex_string(self) -> None:
        """返回 hex 字符串。"""
        h = _hash_signature("hello")
        assert isinstance(h, str)
        assert all(c in "0123456789abcdef" for c in h)


class TestLogPointMatcherMatch:
    """LogPointMatcher.match 单条匹配行为。"""

    def test_match_returns_log_point_on_hash_hit(self) -> None:
        """哈希命中索引 → 返回 LogPoint。"""
        # M1 仓内 LogPoint 模板
        log_point = _make_log_point("User {uid} logged in")
        sig = _normalize_to_signature("User {uid} logged in")
        h = _hash_signature(sig)
        index = FakeLogPointIndex({h: log_point})

        # M2 LogParser 提取的模板（编号占位符）
        entry = _make_entry("User {var_0} logged in")
        matcher = LogPointMatcher(index)

        results = matcher.match([entry])
        assert len(results) == 1
        assert results[0].log_point is log_point
        assert results[0].template_hash == h

    def test_match_returns_none_on_hash_miss(self) -> None:
        """哈希未命中索引 → fallback None。"""
        index = FakeLogPointIndex({})
        entry = _make_entry("User {var_0} logged in")
        matcher = LogPointMatcher(index)

        results = matcher.match([entry])
        assert len(results) == 1
        assert results[0].log_point is None
        assert results[0].template_hash is not None  # hash 仍计算

    def test_match_returns_none_when_template_is_none(self) -> None:
        """entry.log_message_template 为 None（未识别格式）→ log_point=None + template_hash=None。"""
        index = FakeLogPointIndex({})
        entry = _make_entry(None)
        matcher = LogPointMatcher(index)

        results = matcher.match([entry])
        assert len(results) == 1
        assert results[0].log_point is None
        assert results[0].template_hash is None

    def test_match_multiple_entries(self) -> None:
        """批量匹配。"""
        log_point_a = _make_log_point("User {uid} logged in")
        log_point_b = _make_log_point("connection failed to postgres://{host}")
        h_a = _hash_signature(_normalize_to_signature("User {uid} logged in"))
        h_b = _hash_signature(_normalize_to_signature("connection failed to postgres://{host}"))
        index = FakeLogPointIndex({h_a: log_point_a, h_b: log_point_b})

        entries = [
            _make_entry("User {var_0} logged in"),     # → log_point_a
            _make_entry("connection failed to postgres://{var_0}"),  # → log_point_b
            _make_entry("random unmatched template"),  # → None
        ]
        matcher = LogPointMatcher(index)

        results = matcher.match(entries)
        assert len(results) == 3
        assert results[0].log_point is log_point_a
        assert results[1].log_point is log_point_b
        assert results[2].log_point is None

    def test_match_empty_list_returns_empty(self) -> None:
        """空列表返回空。"""
        matcher = LogPointMatcher(FakeLogPointIndex({}))
        assert matcher.match([]) == []


class TestMatchRate:
    """AC-2 关键：匹配率 ≥ 70% fixture 验证。"""

    def test_match_rate_zero_when_empty(self) -> None:
        """空结果集匹配率 0。"""
        matcher = LogPointMatcher(FakeLogPointIndex({}))
        assert matcher.match_rate([]) == 0.0

    def test_match_rate_one_when_all_match(self) -> None:
        """全部命中 → 1.0。"""
        log_point = _make_log_point("User {uid} logged in")
        h = _hash_signature(_normalize_to_signature("User {uid} logged in"))
        index = FakeLogPointIndex({h: log_point})
        matcher = LogPointMatcher(index)

        entries = [_make_entry("User {var_0} logged in") for _ in range(5)]
        results = matcher.match(entries)
        assert matcher.match_rate(results) == 1.0

    def test_match_rate_zero_when_none_match(self) -> None:
        """全无命中 → 0.0。"""
        matcher = LogPointMatcher(FakeLogPointIndex({}))
        entries = [_make_entry("User {var_0} logged in") for _ in range(5)]
        results = matcher.match(entries)
        assert matcher.match_rate(results) == 0.0

    def test_ac2_match_rate_70_percent_fixture(self) -> None:
        """AC-2 fixture：10 条日志，7 条命中（≥70%），3 条 fallback。

        Fixture 场景：真实日志中一部分（如自定义业务日志、第三方库日志）
        没有对应的代码仓 LogPoint —— fallback 到 None，Phase 2 仍可分析
        但不回写 M1。70% 匹配率是 spec 验收线。
        """
        # 7 个 M1 仓内 LogPoint 模板
        indexed_templates = [
            "User {uid} logged in",
            "connection failed to postgres://{host}",
            "request {id} timeout",
            "cache miss for {key}",
            "task {tid} completed",
            "auth failed for {user}",
            "rate limit exceeded for {ip}",
        ]
        by_hash: dict[str, LogPoint] = {}
        for i, t in enumerate(indexed_templates):
            lp = _make_log_point(t)
            lp.id = f"lp-{i}"
            h = _hash_signature(_normalize_to_signature(t))
            by_hash[h] = lp
        index = FakeLogPointIndex(by_hash)

        # 10 条 M2 日志：7 个对应仓内 LogPoint，3 个不对应（业务自定义日志）
        m2_entries_templates = [
            "User {var_0} logged in",                              # 命中
            "connection failed to postgres://{var_0}",             # 命中
            "request {var_0} timeout",                              # 命中
            "cache miss for {var_0}",                              # 命中
            "task {var_0} completed",                               # 命中
            "auth failed for {var_0}",                              # 命中
            "rate limit exceeded for {var_0}",                      # 命中
            "business metric order_count={var_0}",                  # 不命中（业务自定义）
            "third-party sdk error: {var_0}",                      # 不命中（第三方库）
            "startup complete in {var_0}s",                         # 不命中（系统启动）
        ]
        entries = [_make_entry(t) for t in m2_entries_templates]
        matcher = LogPointMatcher(index)

        results = matcher.match(entries)
        rate = matcher.match_rate(results)
        assert rate == 0.7
        assert rate >= 0.70  # AC-2 验收线
