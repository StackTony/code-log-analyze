"""LogSanitizer 测试 — AC-8。"""
from __future__ import annotations

from packages.m1.log_sanitizer import LogSanitizer, SanitizerConfig


def test_api_key_redacted() -> None:
    san = LogSanitizer(SanitizerConfig(enabled=True, patterns=["api_key"], replacement="[REDACTED_{kind}]"))
    text = "Bearer sk-abcd1234 efgh5678 api_key=sk-xxx"
    redacted, hits = san.sanitize(text)
    assert "sk-xxx" not in redacted
    assert "[REDACTED_api_key]" in redacted
    assert hits["api_key"] >= 1


def test_ipv4_redacted() -> None:
    san = LogSanitizer(SanitizerConfig(enabled=True, patterns=["ipv4"], replacement="[REDACTED_{kind}]"))
    text = "client ip 192.168.1.1 connected"
    redacted, _ = san.sanitize(text)
    assert "192.168.1.1" not in redacted
    assert "[REDACTED_ipv4]" in redacted


def test_email_redacted() -> None:
    san = LogSanitizer(SanitizerConfig(enabled=True, patterns=["email"], replacement="[REDACTED_{kind}]"))
    text = "user alice@example.com logged in"
    redacted, _ = san.sanitize(text)
    assert "alice@example.com" not in redacted


def test_disabled_sanitizer_no_changes() -> None:
    san = LogSanitizer(SanitizerConfig(enabled=False, patterns=[], replacement="[REDACTED_{kind}]"))
    text = "api_key=sk-xxx"
    redacted, hits = san.sanitize(text)
    assert redacted == text
    assert hits == {}


def test_zero_hits_required_for_llm_call() -> None:
    """AC-8：命中数=0 才允许发 LLM 调用。"""
    san = LogSanitizer(SanitizerConfig(
        enabled=True, patterns=["api_key", "ipv4", "email", "password", "token"],
        replacement="[REDACTED_{kind}]",
    ))
    cleaned = "clean log text no sensitive data"
    _, hits = san.sanitize(cleaned)
    assert sum(hits.values()) == 0
