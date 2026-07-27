"""F002 M2 — LogParser 测试（spec AC-1）。

验证至少 3 种日志格式解析 + 模板提取 + variables 提取。

v1 起步：Python logging 默认格式（spec §五 v1 范围）。
JSON structured / syslog 风格 F002 实施阶段补。
"""
from __future__ import annotations

from datetime import datetime

from packages.m2.log_parser import LogParser, parse_line


class TestParseLinePythonLogging:
    """Python logging 默认格式解析（spec AC-1 v1 起步范围）。"""

    def test_parses_basic_python_logging(self) -> None:
        """基础格式：`2026-07-27 08:30:00,123 INFO [module] message`"""
        raw = "2026-07-27 08:30:00,123 INFO [auth] User 12345 logged in"
        entry = parse_line(raw)
        assert entry.timestamp == datetime(2026, 7, 27, 8, 30, 0, 123000)
        assert entry.level == "INFO"
        assert entry.source_file == "auth"
        # 模板提取：12345 被替换为 {var_0}
        assert entry.log_message_template is not None
        assert "var_0" in entry.log_message_template
        assert entry.variables.get("var_0") == "12345"

    def test_parses_python_logging_iso_format(self) -> None:
        """ISO 格式：`2026-07-27T08:30:00,123 INFO module: message`"""
        raw = "2026-07-27T08:30:00,123 ERROR db: connection failed to postgres://host:5432"
        entry = parse_line(raw)
        assert entry.timestamp == datetime(2026, 7, 27, 8, 30, 0, 123000)
        assert entry.level == "ERROR"
        assert entry.source_file == "db"
        assert entry.log_message_template is not None
        # 5432 被替换为 var
        assert "5432" in entry.variables.values()

    def test_warning_level_normalized(self) -> None:
        """WARNING 归一化为 WARN（_normalize_level）。"""
        raw = "2026-07-27 08:30:00,123 WARNING [api] deprecated endpoint"
        entry = parse_line(raw)
        assert entry.level == "WARN"

    def test_critical_level_preserved(self) -> None:
        """CRITICAL 保持不变。"""
        raw = "2026-07-27 08:30:00,123 CRITICAL [core] system down"
        entry = parse_line(raw)
        assert entry.level == "CRITICAL"

    def test_uuid_in_message_extracted_as_variable(self) -> None:
        """消息中的 UUID 被提取为变量。"""
        raw = "2026-07-27 08:30:00,123 INFO [api] request id 550e8400-e29b-41d4-a716-446655440000 processed"
        entry = parse_line(raw)
        assert entry.log_message_template is not None
        assert "550e8400-e29b-41d4-a716-446655440000" in entry.variables.values()

    def test_ipv4_in_message_extracted_as_variable(self) -> None:
        """消息中的 IPv4 被提取为变量。"""
        raw = "2026-07-27 08:30:00,123 INFO [api] request from 192.168.1.100 accepted"
        entry = parse_line(raw)
        assert entry.log_message_template is not None
        assert "192.168.1.100" in entry.variables.values()

    def test_unrecognized_format_returns_raw_only(self) -> None:
        """无法识别的格式仍返回 LogEntry，但 timestamp/level/template 为 None。"""
        raw = "random text without timestamp or level"
        entry = parse_line(raw)
        assert entry.raw_text == raw
        assert entry.timestamp is None
        assert entry.level is None
        assert entry.log_message_template is None
        assert entry.variables == {}


class TestLogParserParse:
    """LogParser.parse 多行解析（spec AC-1）。"""

    def test_parse_multiline_log(self) -> None:
        """多行日志解析为多个 LogEntry，空行跳过。"""
        log_text = """
2026-07-27 08:30:00,123 INFO [auth] User 12345 logged in

2026-07-27 08:31:00,456 ERROR [db] connection failed to postgres://host:5432
2026-07-27 08:32:00,789 WARN [api] deprecated endpoint called
"""
        parser = LogParser()
        entries = parser.parse(log_text, source_file="app.log")

        assert len(entries) == 3  # 空行跳过
        assert all(e.source_file == "app.log" for e in entries)
        assert all(e.source_line is not None for e in entries)
        # 按时间顺序
        assert entries[0].timestamp is not None
        assert entries[0].timestamp < entries[1].timestamp  # type: ignore[operator]
        # 第一个条目级别 INFO
        assert entries[0].level == "INFO"
        # 第二个条目级别 ERROR
        assert entries[1].level == "ERROR"

    def test_parse_empty_text_returns_empty_list(self) -> None:
        """空文本返回空列表。"""
        parser = LogParser()
        assert parser.parse("") == []

    def test_parse_only_whitespace_returns_empty_list(self) -> None:
        """只有空白行返回空列表。"""
        parser = LogParser()
        assert parser.parse("   \n\n  \n") == []

    def test_parse_assigns_unique_line_ids(self) -> None:
        """每个 LogEntry 有唯一 line_id。"""
        log_text = "\n".join([
            "2026-07-27 08:30:00,123 INFO [a] message 1",
            "2026-07-27 08:31:00,123 INFO [b] message 2",
            "2026-07-27 08:32:00,123 INFO [c] message 3",
        ])
        parser = LogParser()
        entries = parser.parse(log_text)
        line_ids = [e.line_id for e in entries]
        assert len(set(line_ids)) == 3  # 唯一


class TestTemplateExtraction:
    """模板提取验证（用于 M1 LogPoint 匹配，spec §三）。"""

    def test_template_extraction_simple(self) -> None:
        """单变量模板提取。"""
        from packages.m2.log_parser import _extract_template
        template, variables = _extract_template("User 12345 logged in")
        assert template == "User {var_0} logged in"
        assert variables == {"var_0": "12345"}

    def test_template_extraction_multiple_variables(self) -> None:
        """多变量模板提取。"""
        from packages.m2.log_parser import _extract_template
        template, variables = _extract_template(
            "User 12345 from 192.168.1.1 with session abc12345"
        )
        # 3 个变量（12345, 192.168.1.1, abc12345 — 但 abc12345 不是纯数字，不匹配）
        # 实际只匹配前 2 个：12345, 192.168.1.1
        assert "var_0" in template
        assert "var_1" in template
        assert variables["var_0"] == "12345"
        assert variables["var_1"] == "192.168.1.1"
