"""LogSanitizer — LLM prompt 脱敏（AC-8）。"""
from __future__ import annotations

import dataclasses
import re

# 敏感数据正则库
_PATTERNS: dict[str, str] = {
    "api_key": r"(api[_-]?key[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9\-_]{16,})",
    "password": r"(password[\"']?\s*[:=]\s*[\"']?)([^\s\"']+)",
    "token": r"(token[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9\-_\.]{20,})",
    "ipv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "ipv6": r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b",
    "email": r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
}


@dataclasses.dataclass(frozen=True)
class SanitizerConfig:
    enabled: bool
    patterns: list[str]
    replacement: str


class LogSanitizer:
    def __init__(self, config: SanitizerConfig) -> None:
        self._config = config
        self._compiled: list[tuple[str, re.Pattern[str]]] = []
        if config.enabled:
            for kind in config.patterns:
                pattern = _PATTERNS.get(kind)
                if pattern:
                    self._compiled.append((kind, re.compile(pattern)))

    def sanitize(self, text: str) -> tuple[str, dict[str, int]]:
        """返回 (redacted_text, hits_per_kind)。"""
        if not self._config.enabled:
            return text, {}

        hits: dict[str, int] = {}
        redacted = text
        for kind, pattern in self._compiled:
            matches = pattern.findall(redacted)
            count = len(matches)
            if count > 0:
                hits[kind] = count
                # 替换为 [REDACTED_{kind}] + 短 uuid 保留唯一性追踪
                placeholder = self._config.replacement.replace("{kind}", kind)
                redacted = pattern.sub(
                    lambda m, ph=placeholder: (m.group(1) + ph) if m.groups() else ph,
                    redacted,
                )
        return redacted, hits


def generate_prompt_hash(prompt: str) -> str:
    """prompt 版本 hash（用于 LLMHypothesis.prompt_hash 追溯 A/B 测试）。"""
    import hashlib
    return f"sha256-{hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16]}"
