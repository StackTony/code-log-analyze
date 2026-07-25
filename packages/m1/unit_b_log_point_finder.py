"""Unit B: Log Point Finder — Layer 1 cypher 粗筛 + Layer 2 tree-sitter 精筛。"""
from __future__ import annotations

import pathlib
import re
import uuid
from datetime import UTC, datetime

from packages.contracts.enums import LANGUAGE_C, LANGUAGE_PYTHON
from packages.contracts.log_point import LogPoint
from packages.m1.gitnexus_client import GitNexusClient
from packages.m1.tree_sitter_parser import CallSite, TreeSitterParser

# Layer 1 cypher 粗筛命名模式
_LAYER1_CYPHER_PATTERN = (
    r"^(log|print|printf|fprintf|syslog|logging|logger|warn|error|debug|trace).*$"
)

# Layer 2 精筛白名单
_PY_LOGGING_METHODS = {"info", "warning", "warn", "error", "debug", "critical", "exception"}
_PY_LOGURU_METHODS = {"info", "warning", "warn", "error", "debug", "critical", "exception", "trace"}
_C_STDIO_FUNCS = {"printf", "fprintf", "sprintf", "snprintf"}
_C_SYSLOG_FUNCS = {"syslog"}
_PY_PRINT_FUNC = "print"

# 自定义日志函数命名模式（C）
_C_CUSTOM_LOG_PATTERN = re.compile(r"^.*_(log|error|debug|trace).*$")


class LogPointFinder:
    def __init__(
        self,
        gitnexus: GitNexusClient,
        tree_sitter: TreeSitterParser | None = None,
    ) -> None:
        self._gitnexus = gitnexus
        self._ts = tree_sitter or TreeSitterParser()

    def find(
        self,
        repo_id: str,
        repo_path: pathlib.Path,
        language: str,
        include_print: bool = False,
    ) -> list[LogPoint]:
        # 扫该仓所有源文件
        extensions = self._extensions_for_language(language)
        source_files: list[pathlib.Path] = []
        for ext in extensions:
            source_files.extend(repo_path.rglob(f"*.{ext}"))

        all_points: list[LogPoint] = []
        for src_file in source_files:
            parsed = self._ts.parse_file(src_file, language=language)
            for call in parsed.call_sites:
                point = self._classify_call(repo_id, src_file, parsed, call, language, include_print)
                if point is not None:
                    all_points.append(point)

        # 去重（AC-4）
        deduped = self._dedupe(all_points)

        # occurrence_count = 同 log_template 在仓内被识别为 LogPoint 的次数
        for p in deduped:
            p.occurrence_count = sum(
                1 for q in deduped if q.log_message_template == p.log_message_template
            )

        return deduped

    @staticmethod
    def _extensions_for_language(language: str) -> list[str]:
        if language == LANGUAGE_PYTHON:
            return ["py"]
        if language == LANGUAGE_C:
            return ["c", "h"]
        return []

    def _classify_call(
        self,
        repo_id: str,
        src_file: pathlib.Path,
        parsed,
        call: CallSite,
        language: str,
        include_print: bool,
    ) -> LogPoint | None:
        callee = call.callee_name

        # Python
        if language == LANGUAGE_PYTHON:
            # logging.info / logger.info / LOG.info
            if "." in callee:
                obj, method = callee.rsplit(".", 1)
                # loguru 特征：obj.lower() == "logger"（非 LOG 大写）
                if obj.lower() == "logger" and method in _PY_LOGURU_METHODS:
                    return self._make_point(
                        repo_id, src_file, parsed, call, language,
                        framework_hint="loguru",
                        log_level=method.upper() if method != "warning" else "WARNING",
                        confidence=1.0,
                    )
                # logging 特征：LOG / LOGGING / logging.getLogger() 返回的 log
                if method in _PY_LOGGING_METHODS:
                    return self._make_point(
                        repo_id, src_file, parsed, call, language,
                        framework_hint="logging" if obj.lower() in {"log", "logging"} or obj.startswith("LOG") else "loguru",
                        log_level=method.upper() if method != "warning" else "WARNING",
                        confidence=1.0,
                    )
            # 裸 print
            if callee == _PY_PRINT_FUNC and include_print:
                return self._make_point(
                    repo_id, src_file, parsed, call, language,
                    framework_hint="print", log_level="UNKNOWN", confidence=0.5,
                )
            return None

        # C
        if language == LANGUAGE_C:
            if callee in _C_STDIO_FUNCS:
                framework = "printf"
                confidence = 1.0
                level = "ERROR" if callee == "fprintf" else "INFO"
                return self._make_point(
                    repo_id, src_file, parsed, call, language,
                    framework_hint=framework, log_level=level, confidence=confidence,
                )
            if callee in _C_SYSLOG_FUNCS:
                return self._make_point(
                    repo_id, src_file, parsed, call, language,
                    framework_hint="syslog", log_level="INFO", confidence=1.0,
                )
            if _C_CUSTOM_LOG_PATTERN.match(callee):
                return self._make_point(
                    repo_id, src_file, parsed, call, language,
                    framework_hint="custom", log_level="UNKNOWN", confidence=0.7,
                )
            return None

        return None

    @staticmethod
    def _make_point(
        repo_id: str,
        src_file: pathlib.Path,
        parsed,
        call: CallSite,
        language: str,
        framework_hint: str,
        log_level: str,
        confidence: float,
    ) -> LogPoint:
        # file_path 统一 POSIX（AC-15）
        posix_path = str(src_file.as_posix())
        # 找 enclosing function signature
        enclosing_fn = next(
            (f for f in parsed.functions if f.name == call.enclosing_function),
            None,
        )
        sig = enclosing_fn.signature if enclosing_fn else (call.enclosing_function or "<module>")

        return LogPoint(
            id=f"lp-{uuid.uuid4().hex[:12]}",
            repo_id=repo_id,
            git_commit_sha="unknown",  # 由 RepoRegistrar 在 Unit A 填
            extractor_version="1.0.0",
            file_path=posix_path,
            function_signature=sig,
            line_start=call.line,
            line_end=call.line,
            language=language,
            log_level=log_level,
            log_message_template="",  # 实施时解析参数提取模板
            log_message_variables=[],
            framework_hint=framework_hint,
            confidence_score=confidence,
            enclosing_class=enclosing_fn.enclosing_class if enclosing_fn else None,
            call_chain_to_entry=[],
            enclosing_community=None,
            evidence_refs=[],
            llm_hypothesis=None,
            occurrence_count=0,
            is_top_n=False,
            ingestion_status="candidate",
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )

    @staticmethod
    def _dedupe(points: list[LogPoint]) -> list[LogPoint]:
        seen: set[tuple[str, str, int]] = set()
        out: list[LogPoint] = []
        for p in points:
            key = (p.repo_id, p.file_path, p.line_start)
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out
