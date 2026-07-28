"""F003 M3 — M3Config + config_loader 扩展（spec §七）。"""
from __future__ import annotations

from unittest.mock import MagicMock

from packages.m1.config_loader import Config, M3Config


class TestM3ConfigDefaults:
    def test_defaults_match_spec(self) -> None:
        c = M3Config()
        assert c.file_tail_poll_interval_seconds == 1.0
        assert c.file_tail_use_inotify is False
        assert c.time_window_event_count == 1000
        assert c.time_window_seconds == 300
        assert c.anomaly_density_threshold == 0.30
        assert c.event_ttl_days == 7
        assert c.pause_source_keep_events is True


class TestConfigM3Field:
    def test_config_with_m3(self) -> None:
        c = Config(
            llm=MagicMock(), storage=MagicMock(), extraction=MagicMock(),
            sanitizer=MagicMock(), metrics=MagicMock(), api=MagicMock(),
            m2=MagicMock(), m3=M3Config(),
        )
        assert c.m3.time_window_event_count == 1000
        assert c.m3.anomaly_density_threshold == 0.30
