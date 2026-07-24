"""Unit C: LLM Hypothesis Generator — 脱敏 + 批量调 + Redis 缓存（AC-6/7/8）。"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import redis

from packages.contracts.log_point import LLMHypothesis, LogPoint
from packages.m1.log_sanitizer import LogSanitizer, generate_prompt_hash


class LLMClient:
    """抽象 LLM client — 子类可对接 OpenAI / Anthropic / 内部网关。"""
    async def complete(self, prompt: str) -> str:
        raise NotImplementedError


class RedisCache:
    def __init__(self, redis_client: redis.Redis, namespace: str = "codefly-m1") -> None:
        self._r = redis_client
        self._ns = namespace

    def _key(self, k: str) -> str:
        return f"{self._ns}:{k}"

    def get(self, key: str) -> str | None:
        return self._r.get(self._key(key))

    def set(self, key: str, value: str, ttl_seconds: int = 86400) -> None:
        self._r.setex(self._key(key), ttl_seconds, value)


class LLMHypothesisGenerator:
    def __init__(
        self,
        llm_client: LLMClient,
        cache: RedisCache,
        model_name: str,
        extractor_version: str,
        sanitizer: LogSanitizer,
        batch_size: int = 20,
        max_retries: int = 3,
    ) -> None:
        self._llm = llm_client
        self._cache = cache
        self._model_name = model_name
        self._extractor_version = extractor_version
        self._sanitizer = sanitizer
        self._batch_size = batch_size
        self._max_retries = max_retries

    def _cache_key(self, log_point: LogPoint) -> str:
        """AC-6: cache key 包含 extractor_version（明文）+ sha256 hash。"""
        parts = "|".join([
            log_point.log_message_template,
            log_point.function_signature,
            self._model_name,
            self._extractor_version,
        ])
        h = hashlib.sha256(parts.encode("utf-8")).hexdigest()[:32]
        # 明文包含 extractor_version 便于版本升级缓存失效
        return f"llm-hyp:extractor_version={self._extractor_version}:{h}"

    async def generate(self, points: list[LogPoint]) -> None:
        for batch_start in range(0, len(points), self._batch_size):
            batch = points[batch_start:batch_start + self._batch_size]
            for lp in batch:
                try:
                    await self._generate_one(lp)
                except Exception:
                    # AC-7：失败不阻塞
                    lp.llm_hypothesis = None

    async def _generate_one(self, lp: LogPoint) -> None:
        key = self._cache_key(lp)
        cached = self._cache.get(key)
        if cached:
            lp.llm_hypothesis = self._hypothesis_from_cache(cached)
            return

        # AC-8：脱敏
        prompt = self._build_prompt(lp)
        sanitized, hits = self._sanitizer.sanitize(prompt)
        # 不论 hits 是否为 0，都用 sanitized 调 LLM（hits=0 时 sanitized == prompt）
        if sum(hits.values()) > 0:
            # 已脱敏，仍调 LLM（合规）
            pass

        # 调 LLM（带重试）
        for attempt in range(self._max_retries):
            try:
                response = await self._llm.complete(sanitized)
                hypothesis = self._parse_response(response)
                lp.llm_hypothesis = hypothesis
                # 写缓存
                self._cache.set(key, json.dumps({
                    "summary": hypothesis.summary,
                    "possible_causes": hypothesis.possible_causes,
                    "error_kind": hypothesis.error_kind,
                    "suggested_check": hypothesis.suggested_check,
                    "model_name": hypothesis.model_name,
                    "prompt_hash": hypothesis.prompt_hash,
                }))
                return
            except Exception:
                if attempt == self._max_retries - 1:
                    raise
                continue

    def _build_prompt(self, lp: LogPoint) -> str:
        return (
            f"代码仓日志埋点分析 - 推断这条日志可能为什么打印:\n"
            f"  文件: {lp.file_path}:{lp.line_start}\n"
            f"  函数: {lp.function_signature}\n"
            f"  级别: {lp.log_level}\n"
            f"  日志模板: {lp.log_message_template}\n"
            f"  变量: {lp.log_message_variables}\n"
            f"  框架: {lp.framework_hint}\n"
            "请用 JSON 返回: summary / possible_causes / error_kind / suggested_check\n"
            "error_kind 取值: param_error / state_error / external_dep_error / logic_error / unknown"
        )

    def _parse_response(self, response: str) -> LLMHypothesis:
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # 容错：LLM 没返回 JSON
            data = {
                "summary": response[:200],
                "possible_causes": [],
                "error_kind": "unknown",
                "suggested_check": None,
            }
        prompt_hash = generate_prompt_hash("llm-hyp-v1")
        return LLMHypothesis(
            summary=data.get("summary", ""),
            possible_causes=data.get("possible_causes", []),
            error_kind=data.get("error_kind", "unknown"),
            suggested_check=data.get("suggested_check"),
            model_name=self._model_name,
            prompt_hash=prompt_hash,
            generated_at=datetime.now(UTC),
        )

    @staticmethod
    def _hypothesis_from_cache(cached_json: str) -> LLMHypothesis:
        d = json.loads(cached_json)
        return LLMHypothesis(
            summary=d["summary"],
            possible_causes=d["possible_causes"],
            error_kind=d["error_kind"],
            suggested_check=d["suggested_check"],
            model_name=d["model_name"],
            prompt_hash=d["prompt_hash"],
            generated_at=datetime.now(UTC),
        )
