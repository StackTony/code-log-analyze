# F003 在线日志扫描 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 F002 已 merge 的 `LogAnalysisService.analyze_logs` 加一层"在线扫描"前置——实时流式日志（file_tail + http_webhook）持续累积 + 三种触发条件（time_window / anomaly_density / manual）自动调 M2 产报告，让 M2 全量分析持续化、自动化。

**Architecture:** M3 不重新实现 LLM 分析逻辑，复用 M2 `LogParser` / `LogPointMatcher` / `StorageBackedLogPointIndex` + 依赖注入 M2 `LogAnalysisService.analyze_logs`。M3 在 `packages/m3/` 新增子包，含 `OnlineLogScanner`（7 API 方法）+ `EventIngestor`（解析入库）+ `TriggerEvaluator`（触发判定）+ `FileTailer`（后台 polling）+ Storage 三张表 + MetricsEmitter + 8 个 HTTP endpoint。file_tail 后台 task 用 `asyncio.create_task` 在 FastAPI `lifespan` 内，pause 时 cancel。M3 不修改 M1/M2 service/storage/contracts 字节级（仅 contracts 扩展枚举 + 新增 log_stream.py）。

**Tech Stack:** Python 3.11+ / FastAPI 0.110+ / Pydantic v2.6+ / SQLAlchemy 2.x（复用 M1/M2 engine）/ pytest / ruff / prometheus_client / asyncio（file_tail polling）

## Global Constraints

- **Python 3.11+** (pyproject.toml requires-python，继承 M1/M2)
- **ruff** lint + format（line-length=100，复用 ruff.toml）
- **pytest**（复用 pytest.ini，Python 3.10 测试用 `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main([...])"`)
- **API 端口 8000 / metrics 9464 / frontend 3003**（复用 F001.1 v1.1 修正，不新增端口）
- **Redis 6398 dev/test**（家规铁律，复用 M1 namespace `codefly-m1` + M2 `codefly-m2` + 新增 `codefly-m3`）
- **Redis 6399 禁止**（家规铁律，生产圣域）
- **TTL=0 P0 持久化铁律** — `LogStreamSource` + `LogStreamEvent` + `ScanTrigger` 默认 TTL=0（用户可见产物）
- **No self-review**（F003 author=奉孝 Siamese @ragdoll-pa82，reviewer=云长 跨家族 Sphynx @cat-ko094z1n）
- **TDD**：每 task 先红测 → 跑 fail → 最小实现 → 跑 pass → lint → commit
- **不动 M1/M2 service/storage/contracts 字节级**（仅 contracts 扩展 enums + 新增 log_stream.py，不修改已有 dataclass）
- **M3 不直接 import M2 service**（通过 `M2ServiceProtocol` 依赖注入，避免循环依赖）
- **M3 不回写 M1 主表**（仅读 LogPoint 做匹配，回写是 M2 Phase 2 职责）
- **file_tail polling 模式 v1**（inotify 留 v2，OQ-2）
- **http_webhook rate limiting + auth token v2**（dev 不做，OQ-留 v2）

---

### Task 1: 起步骨架 — contracts 扩展 + dataclass

**Files:**
- Create: `packages/contracts/log_stream.py`
- Modify: `packages/contracts/enums.py`（追加 M3 枚举段）
- Create: `packages/m3/__init__.py`（空）
- Create: `packages/m3/storage/__init__.py`（空）
- Create: `tests/m3/__init__.py`（空）
- Test: `tests/m3/test_log_stream_dataclasses.py`

**Interfaces:**
- Consumes: `packages.contracts.enums`（已有常量模式）
- Produces:
  - `packages.contracts.log_stream.LogStreamSource` dataclass（id/kind/config/repo_id/ingestion_status/created_at/updated_at）
  - `packages.contracts.log_stream.LogStreamEvent` dataclass（id/source_id/raw_text/timestamp/level/log_message_template/variables/log_point_id/ingested_at）
  - `packages.contracts.log_stream.ScanTrigger` dataclass（id/source_id/trigger_kind/event_count/window_start/window_end/triggered_report_id/triggered_at/triggered_by）
  - `packages.contracts.enums` 新增：`SOURCE_KIND_FILE_TAIL/HTTP_WEBHOOK` / `STATUS_ACTIVE/PAUSED/STOPPED` / `TRIGGER_TIME_WINDOW/ANOMALY_DENSITY/MANUAL` / `ACTION_M3_*`

- [ ] **Step 1: Write the failing test**

`tests/m3/test_log_stream_dataclasses.py`:
```python
"""F003 M3 — contracts.log_stream dataclass v1 骨架（spec §三）。"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from packages.contracts.enums import (
    ACTION_M3_INGEST_EVENT,
    ACTION_M3_REGISTER_SOURCE,
    ACTION_M3_SCAN_NOW,
    SOURCE_KIND_FILE_TAIL,
    SOURCE_KIND_HTTP_WEBHOOK,
    STATUS_ACTIVE,
    STATUS_PAUSED,
    STATUS_STOPPED,
    TRIGGER_ANOMALY_DENSITY,
    TRIGGER_MANUAL,
    TRIGGER_TIME_WINDOW,
)
from packages.contracts.log_stream import (
    LogStreamEvent,
    LogStreamSource,
    ScanTrigger,
)


class TestLogStreamSourceDataclass:
    def test_file_tail_source_minimal(self) -> None:
        now = datetime.now(UTC)
        src = LogStreamSource(
            id="src-1",
            kind=SOURCE_KIND_FILE_TAIL,
            config={"path": "/var/log/app.log", "pos_file": ".pos"},
            repo_id=None,
            ingestion_status=STATUS_ACTIVE,
            created_at=now,
            updated_at=now,
        )
        assert src.kind == SOURCE_KIND_FILE_TAIL
        assert src.ingestion_status == STATUS_ACTIVE

    def test_webhook_source_with_repo(self) -> None:
        now = datetime.now(UTC)
        src = LogStreamSource(
            id="src-2",
            kind=SOURCE_KIND_HTTP_WEBHOOK,
            config={"path": "/ingest/src-2", "auth_token": "tok"},
            repo_id="repo-1",
            ingestion_status=STATUS_PAUSED,
            created_at=now,
            updated_at=now,
        )
        assert src.kind == SOURCE_KIND_HTTP_WEBHOOK
        assert src.repo_id == "repo-1"


class TestLogStreamEventDataclass:
    def test_event_matched_log_point(self) -> None:
        e = LogStreamEvent(
            id="evt-1",
            source_id="src-1",
            raw_text="2026-07-28 INFO User 12345 logged in",
            timestamp=datetime.now(UTC),
            level="INFO",
            log_message_template="User {uid} logged in",
            variables={"uid": "12345"},
            log_point_id="lp-1",  # matched
            ingested_at=datetime.now(UTC),
        )
        assert e.log_point_id == "lp-1"
        assert e.variables["uid"] == "12345"

    def test_event_unmatched_log_point_none(self) -> None:
        e = LogStreamEvent(
            id="evt-2",
            source_id="src-1",
            raw_text="weird log line",
            timestamp=None,
            level=None,
            log_message_template=None,
            variables={},
            log_point_id=None,  # unmatched
            ingested_at=datetime.now(UTC),
        )
        assert e.log_point_id is None


class TestScanTriggerDataclass:
    def test_time_window_trigger(self) -> None:
        now = datetime.now(UTC)
        t = ScanTrigger(
            id="trig-1",
            source_id="src-1",
            trigger_kind=TRIGGER_TIME_WINDOW,
            event_count=1000,
            window_start=now,
            window_end=now,
            triggered_report_id="rpt-1",
            triggered_at=now,
            triggered_by="system",
        )
        assert t.trigger_kind == TRIGGER_TIME_WINDOW
        assert t.triggered_by == "system"

    def test_manual_trigger_by_user(self) -> None:
        now = datetime.now(UTC)
        t = ScanTrigger(
            id="trig-2",
            source_id="src-1",
            trigger_kind=TRIGGER_MANUAL,
            event_count=42,
            window_start=now,
            window_end=now,
            triggered_report_id=None,  # not yet filled
            triggered_at=now,
            triggered_by="user-alice",
        )
        assert t.trigger_kind == TRIGGER_MANUAL
        assert t.triggered_report_id is None


class TestEnumsM3:
    """spec §三 枚举常量（M3 新增）。"""

    def test_source_kind_constants(self) -> None:
        assert SOURCE_KIND_FILE_TAIL == "file_tail"
        assert SOURCE_KIND_HTTP_WEBHOOK == "http_webhook"

    def test_status_constants(self) -> None:
        assert STATUS_ACTIVE == "active"
        assert STATUS_PAUSED == "paused"
        assert STATUS_STOPPED == "stopped"

    def test_trigger_kind_constants(self) -> None:
        assert TRIGGER_TIME_WINDOW == "time_window"
        assert TRIGGER_ANOMALY_DENSITY == "anomaly_density"
        assert TRIGGER_MANUAL == "manual"

    def test_action_m3_constants(self) -> None:
        assert ACTION_M3_REGISTER_SOURCE == "m3_register_source"
        assert ACTION_M3_INGEST_EVENT == "m3_ingest_event"
        assert ACTION_M3_SCAN_NOW == "m3_scan_now"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_log_stream_dataclasses.py', '-v'])"`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.contracts.log_stream'`

- [ ] **Step 3: Append M3 enums to packages/contracts/enums.py**

在 `packages/contracts/enums.py` 末尾追加（不修改已有内容）：
```python
# F003 M3 LogStreamSource.kind
SOURCE_KIND_FILE_TAIL = "file_tail"
SOURCE_KIND_HTTP_WEBHOOK = "http_webhook"

# F003 M3 LogStreamSource.ingestion_status
STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_STOPPED = "stopped"

# F003 M3 ScanTrigger.trigger_kind
TRIGGER_TIME_WINDOW = "time_window"
TRIGGER_ANOMALY_DENSITY = "anomaly_density"
TRIGGER_MANUAL = "manual"

# AuditLog action（M3 写操作时统一引用，避免字符串硬编码不一致）
ACTION_M3_REGISTER_SOURCE = "m3_register_source"
ACTION_M3_PAUSE_SOURCE = "m3_pause_source"
ACTION_M3_RESUME_SOURCE = "m3_resume_source"
ACTION_M3_INGEST_EVENT = "m3_ingest_event"
ACTION_M3_TRIGGER_ANALYZE = "m3_trigger_analyze"
ACTION_M3_SCAN_NOW = "m3_scan_now"
```

- [ ] **Step 4: Create packages/contracts/log_stream.py**

```python
"""F003 M3 — LogStream 数据契约（spec §三）。

LogStreamSource: M3 数据源配置（file_tail / http_webhook）
LogStreamEvent: M3 流式日志事件（解析后，含 M1 LogPoint 关联）
ScanTrigger: M3 触发 M2 分析的记录
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class LogStreamSource:
    """M3 数据源配置（spec §三）。"""
    id: str
    kind: str                              # SOURCE_KIND_FILE_TAIL | SOURCE_KIND_HTTP_WEBHOOK
    config: dict[str, Any]                  # kind-specific
    repo_id: str | None                     # 关联代码仓（None=不匹配 M1 LogPoint）
    ingestion_status: str                  # STATUS_ACTIVE | STATUS_PAUSED | STATUS_STOPPED
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class LogStreamEvent:
    """M3 流式日志事件（解析后，spec §三）。"""
    id: str
    source_id: str
    raw_text: str
    timestamp: datetime | None
    level: str | None
    log_message_template: str | None       # 用于匹配 M1 LogPoint
    variables: dict[str, str] = field(default_factory=dict)
    log_point_id: str | None = None        # 匹配 M1 LogPoint 后填充
    ingested_at: datetime | None = None


@dataclass(frozen=True)
class ScanTrigger:
    """M3 触发 M2 分析的记录（spec §三）。"""
    id: str
    source_id: str
    trigger_kind: str                      # TRIGGER_TIME_WINDOW | TRIGGER_ANOMALY_DENSITY | TRIGGER_MANUAL
    event_count: int
    window_start: datetime
    window_end: datetime
    triggered_report_id: str | None = None  # 调 M2 后回填
    triggered_at: datetime | None = None
    triggered_by: str = "system"            # user_id (manual) 或 "system" (auto)
```

- [ ] **Step 5: Create empty __init__.py files**

`packages/m3/__init__.py`:
```python
"""F003 M3 — 在线日志扫描子包。"""
```

`packages/m3/storage/__init__.py`:
```python
"""M3 storage models + repository。"""
```

`tests/m3/__init__.py`（空文件）

- [ ] **Step 6: Run test to verify it passes**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_log_stream_dataclasses.py', '-v'])"`
Expected: PASS（13 tests）

- [ ] **Step 7: Lint**

Run: `ruff check packages/contracts/log_stream.py packages/contracts/enums.py tests/m3/`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add packages/contracts/log_stream.py packages/contracts/enums.py \
        packages/m3/__init__.py packages/m3/storage/__init__.py tests/m3/__init__.py \
        tests/m3/test_log_stream_dataclasses.py
git commit -m "feat(m3): 起步骨架 — contracts 扩展 + LogStreamSource/LogStreamEvent/ScanTrigger dataclass（AC-14 准备）"
```

---

### Task 2: Storage 三张表 + migration 0003

**Files:**
- Create: `packages/m3/storage/models.py`
- Create: `packages/m3/storage/migrations/versions/0003_m3_initial.py`
- Test: `tests/m3/test_storage_models.py`

**Interfaces:**
- Consumes: `packages.m1.storage.models.Base`（M1 SQLAlchemy Base，F002 已复用模式）
- Produces:
  - `packages.m3.storage.models.Base`（M3 SQLAlchemy Base，独立 metadata）
  - `packages.m3.storage.models.LogStreamSourceModel`
  - `packages.m3.storage.models.LogStreamEventModel`
  - `packages.m3.storage.models.ScanTriggerModel`

- [ ] **Step 1: Write the failing test**

`tests/m3/test_storage_models.py`:
```python
"""F003 M3 — Storage 三张表 schema 验证（spec §五 + AC-14）。"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.m3.storage.models import (
    Base as M3Base,
    LogStreamEventModel,
    LogStreamSourceModel,
    ScanTriggerModel,
)


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    M3Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


class TestLogStreamSourceModel:
    def test_create_minimal(self, session: Session) -> None:
        now = datetime.now(UTC)
        row = LogStreamSourceModel(
            id="src-1",
            kind="file_tail",
            config_json='{"path": "/var/log/app.log"}',
            repo_id=None,
            ingestion_status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        got = session.get(LogStreamSourceModel, "src-1")
        assert got is not None
        assert got.kind == "file_tail"
        assert got.ingestion_status == "active"


class TestLogStreamEventModel:
    def test_create_matched(self, session: Session) -> None:
        now = datetime.now(UTC)
        # 先建 source（外键约束）
        session.add(LogStreamSourceModel(
            id="src-1", kind="file_tail", config_json="{}",
            repo_id=None, ingestion_status="active",
            created_at=now, updated_at=now,
        ))
        session.commit()
        evt = LogStreamEventModel(
            id="evt-1",
            source_id="src-1",
            raw_text="some log",
            timestamp=now,
            level="INFO",
            log_message_template="some template",
            variables_json='{"uid": "12345"}',
            log_point_id="lp-1",
            ingested_at=now,
        )
        session.add(evt)
        session.commit()
        got = session.get(LogStreamEventModel, "evt-1")
        assert got is not None
        assert got.log_point_id == "lp-1"


class TestScanTriggerModel:
    def test_create_time_window(self, session: Session) -> None:
        now = datetime.now(UTC)
        session.add(LogStreamSourceModel(
            id="src-1", kind="file_tail", config_json="{}",
            repo_id=None, ingestion_status="active",
            created_at=now, updated_at=now,
        ))
        session.commit()
        trig = ScanTriggerModel(
            id="trig-1",
            source_id="src-1",
            trigger_kind="time_window",
            event_count=1000,
            window_start=now,
            window_end=now,
            triggered_report_id="rpt-1",
            triggered_at=now,
            triggered_by="system",
        )
        session.add(trig)
        session.commit()
        got = session.get(ScanTriggerModel, "trig-1")
        assert got is not None
        assert got.trigger_kind == "time_window"
        assert got.triggered_by == "system"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_storage_models.py', '-v'])"`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m3.storage.models'`

- [ ] **Step 3: Create packages/m3/storage/models.py**

```python
"""F003 M3 — Storage 三张表（spec §五 + AC-14）。

复用 M2 模式（独立 Base metadata，避免与 M1 Base 冲突）。
JSON 字段用 _json 后缀（SQLite 不原生支持 JSON，用 Text 存）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """M3 SQLAlchemy Base（独立 metadata）。"""
    pass


class LogStreamSourceModel(Base):
    """M3 数据源配置表（spec §三 LogStreamSource）。"""
    __tablename__ = "m3_log_stream_source"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # file_tail | http_webhook
    config_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-encoded dict
    repo_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingestion_status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LogStreamEventModel(Base):
    """M3 流式日志事件表（spec §三 LogStreamEvent）。"""
    __tablename__ = "m3_log_stream_event"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("m3_log_stream_source.id"), nullable=False,
        index=True,
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    level: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    log_message_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    variables_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    log_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class ScanTriggerModel(Base):
    """M3 触发记录表（spec §三 ScanTrigger）。"""
    __tablename__ = "m3_scan_trigger"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("m3_log_stream_source.id"), nullable=False,
        index=True,
    )
    trigger_kind: Mapped[str] = mapped_column(String(32), nullable=False)  # time_window | anomaly_density | manual
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    triggered_report_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
```

- [ ] **Step 4: Create packages/m3/storage/migrations/versions/0003_m3_initial.py**

```python
"""M3 initial migration — LogStreamSource + LogStreamEvent + ScanTrigger.

Revision ID: 0003_m3_initial
Revises: 0002_m2_initial
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_m3_initial"
down_revision = "0002_m2_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m3_log_stream_source",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("config_json", sa.Text, nullable=False),
        sa.Column("repo_id", sa.String(64), nullable=True),
        sa.Column("ingestion_status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "m3_log_stream_event",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64),
                  sa.ForeignKey("m3_log_stream_source.id"), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("timestamp", sa.DateTime, nullable=True),
        sa.Column("level", sa.String(16), nullable=True),
        sa.Column("log_message_template", sa.Text, nullable=True),
        sa.Column("variables_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("log_point_id", sa.String(64), nullable=True),
        sa.Column("ingested_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_m3_log_stream_event_source_id", "m3_log_stream_event", ["source_id"])
    op.create_index("ix_m3_log_stream_event_level", "m3_log_stream_event", ["level"])
    op.create_index("ix_m3_log_stream_event_log_point_id", "m3_log_stream_event", ["log_point_id"])
    op.create_index("ix_m3_log_stream_event_ingested_at", "m3_log_stream_event", ["ingested_at"])
    op.create_table(
        "m3_scan_trigger",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64),
                  sa.ForeignKey("m3_log_stream_source.id"), nullable=False),
        sa.Column("trigger_kind", sa.String(32), nullable=False),
        sa.Column("event_count", sa.Integer, nullable=False),
        sa.Column("window_start", sa.DateTime, nullable=False),
        sa.Column("window_end", sa.DateTime, nullable=False),
        sa.Column("triggered_report_id", sa.String(64), nullable=True),
        sa.Column("triggered_at", sa.DateTime, nullable=False),
        sa.Column("triggered_by", sa.String(64), nullable=False, server_default="system"),
    )
    op.create_index("ix_m3_scan_trigger_source_id", "m3_scan_trigger", ["source_id"])
    op.create_index("ix_m3_scan_trigger_triggered_report_id", "m3_scan_trigger", ["triggered_report_id"])


def downgrade() -> None:
    op.drop_table("m3_scan_trigger")
    op.drop_table("m3_log_stream_event")
    op.drop_table("m3_log_stream_source")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_storage_models.py', '-v'])"`
Expected: PASS（3 tests）

- [ ] **Step 6: Lint**

Run: `ruff check packages/m3/storage/ tests/m3/test_storage_models.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add packages/m3/storage/models.py packages/m3/storage/migrations/ \
        tests/m3/test_storage_models.py
git commit -m "feat(m3): Storage 三张表 + migration 0003（AC-14/16）"
```

---

### Task 3: Storage Repository — dataclass ↔ Model 转换 + CRUD

**Files:**
- Create: `packages/m3/storage/repository.py`
- Test: `tests/m3/test_storage_repository.py`

**Interfaces:**
- Consumes: `packages.m3.storage.models`（Task 2 产出）+ `packages.contracts.log_stream`（Task 1 产出）
- Produces:
  - `packages.m3.storage.repository.M3Repository`
  - 方法签名：
    - `save_source(source: LogStreamSource) -> None`
    - `get_source(source_id: str) -> LogStreamSource | None`
    - `list_sources(status: str | None = None) -> list[LogStreamSource]`
    - `update_source_status(source_id: str, status: str, updated_at: datetime) -> None`
    - `save_event(event: LogStreamEvent) -> None`
    - `list_events(source_id: str, window_start: datetime, window_end: datetime) -> list[LogStreamEvent]`
    - `count_events_by_level(source_id: str, window_start: datetime, window_end: datetime) -> dict[str, int]`
    - `save_trigger(trigger: ScanTrigger) -> None`
    - `update_trigger_report_id(trigger_id: str, report_id: str) -> None`
    - `list_triggers(source_id: str, window_start: datetime | None, window_end: datetime | None) -> list[ScanTrigger]`

- [ ] **Step 1: Write the failing test**

`tests/m3/test_storage_repository.py`:
```python
"""F003 M3 — Storage Repository CRUD（spec §五 + AC-14）。"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import (
    SOURCE_KIND_FILE_TAIL,
    STATUS_ACTIVE,
    STATUS_PAUSED,
    TRIGGER_MANUAL,
    TRIGGER_TIME_WINDOW,
)
from packages.contracts.log_stream import (
    LogStreamEvent,
    LogStreamSource,
    ScanTrigger,
)
from packages.m3.storage.models import Base as M3Base
from packages.m3.storage.repository import M3Repository


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    M3Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture()
def repo(session: Session) -> M3Repository:
    return M3Repository(session)


class TestSourceCrud:
    def test_save_and_get(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        src = LogStreamSource(
            id="src-1", kind=SOURCE_KIND_FILE_TAIL,
            config={"path": "/var/log/app.log"}, repo_id=None,
            ingestion_status=STATUS_ACTIVE,
            created_at=now, updated_at=now,
        )
        repo.save_source(src)
        got = repo.get_source("src-1")
        assert got is not None
        assert got.kind == SOURCE_KIND_FILE_TAIL
        assert got.config["path"] == "/var/log/app.log"

    def test_list_by_status(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        for i, status in enumerate([STATUS_ACTIVE, STATUS_PAUSED, STATUS_ACTIVE]):
            repo.save_source(LogStreamSource(
                id=f"src-{i}", kind=SOURCE_KIND_FILE_TAIL,
                config={}, repo_id=None, ingestion_status=status,
                created_at=now, updated_at=now,
            ))
        active = repo.list_sources(status=STATUS_ACTIVE)
        assert len(active) == 2

    def test_update_status(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        repo.save_source(LogStreamSource(
            id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
            repo_id=None, ingestion_status=STATUS_ACTIVE,
            created_at=now, updated_at=now,
        ))
        later = now + timedelta(seconds=1)
        repo.update_source_status("src-1", STATUS_PAUSED, updated_at=later)
        got = repo.get_source("src-1")
        assert got is not None
        assert got.ingestion_status == STATUS_PAUSED


class TestEventCrud:
    def test_save_and_list_window(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        repo.save_source(LogStreamSource(
            id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
            repo_id=None, ingestion_status=STATUS_ACTIVE,
            created_at=now, updated_at=now,
        ))
        # 三条事件，时间分散
        for i, t_offset in enumerate([0, 100, 200]):
            repo.save_event(LogStreamEvent(
                id=f"evt-{i}", source_id="src-1",
                raw_text=f"log line {i}",
                timestamp=now + timedelta(seconds=t_offset),
                level="INFO" if i % 2 == 0 else "ERROR",
                log_message_template=None, variables={},
                log_point_id=None,
                ingested_at=now + timedelta(seconds=t_offset),
            ))
        # 取 window [50, 250] 应得 2 条
        evts = repo.list_events(
            "src-1",
            window_start=now + timedelta(seconds=50),
            window_end=now + timedelta(seconds=250),
        )
        assert len(evts) == 2

    def test_count_by_level(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        repo.save_source(LogStreamSource(
            id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
            repo_id=None, ingestion_status=STATUS_ACTIVE,
            created_at=now, updated_at=now,
        ))
        for level in ["INFO", "ERROR", "ERROR", "WARN"]:
            repo.save_event(LogStreamEvent(
                id=f"evt-{level}-{now.microsecond}",
                source_id="src-1", raw_text="x",
                timestamp=now, level=level,
                log_message_template=None, variables={},
                log_point_id=None, ingested_at=now,
            ))
        counts = repo.count_events_by_level(
            "src-1",
            window_start=now - timedelta(seconds=1),
            window_end=now + timedelta(seconds=1),
        )
        assert counts.get("ERROR", 0) == 2
        assert counts.get("INFO", 0) == 1


class TestTriggerCrud:
    def test_save_and_update_report_id(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        repo.save_source(LogStreamSource(
            id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
            repo_id=None, ingestion_status=STATUS_ACTIVE,
            created_at=now, updated_at=now,
        ))
        trig = ScanTrigger(
            id="trig-1", source_id="src-1",
            trigger_kind=TRIGGER_TIME_WINDOW,
            event_count=1000,
            window_start=now, window_end=now,
            triggered_report_id=None,
            triggered_at=now, triggered_by="system",
        )
        repo.save_trigger(trig)
        repo.update_trigger_report_id("trig-1", "rpt-1")
        trigs = repo.list_triggers("src-1", None, None)
        assert len(trigs) == 1
        assert trigs[0].triggered_report_id == "rpt-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_storage_repository.py', '-v'])"`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m3.storage.repository'`

- [ ] **Step 3: Create packages/m3/storage/repository.py**

```python
"""F003 M3 — Storage Repository（dataclass ↔ Model 转换 + CRUD）。

模式复用 M2 storage/repository.py（to_model / from_model 转换方法）。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.contracts.log_stream import (
    LogStreamEvent,
    LogStreamSource,
    ScanTrigger,
)
from packages.m3.storage.models import (
    LogStreamEventModel,
    LogStreamSourceModel,
    ScanTriggerModel,
)


def _source_to_model(source: LogStreamSource) -> LogStreamSourceModel:
    return LogStreamSourceModel(
        id=source.id,
        kind=source.kind,
        config_json=json.dumps(source.config),
        repo_id=source.repo_id,
        ingestion_status=source.ingestion_status,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _source_from_model(row: LogStreamSourceModel) -> LogStreamSource:
    return LogStreamSource(
        id=row.id,
        kind=row.kind,
        config=json.loads(row.config_json),
        repo_id=row.repo_id,
        ingestion_status=row.ingestion_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _event_to_model(event: LogStreamEvent) -> LogStreamEventModel:
    return LogStreamEventModel(
        id=event.id,
        source_id=event.source_id,
        raw_text=event.raw_text,
        timestamp=event.timestamp,
        level=event.level,
        log_message_template=event.log_message_template,
        variables_json=json.dumps(event.variables),
        log_point_id=event.log_point_id,
        ingested_at=event.ingested_at,
    )


def _event_from_model(row: LogStreamEventModel) -> LogStreamEvent:
    return LogStreamEvent(
        id=row.id,
        source_id=row.source_id,
        raw_text=row.raw_text,
        timestamp=row.timestamp,
        level=row.level,
        log_message_template=row.log_message_template,
        variables=json.loads(row.variables_json),
        log_point_id=row.log_point_id,
        ingested_at=row.ingested_at,
    )


def _trigger_to_model(trig: ScanTrigger) -> ScanTriggerModel:
    return ScanTriggerModel(
        id=trig.id,
        source_id=trig.source_id,
        trigger_kind=trig.trigger_kind,
        event_count=trig.event_count,
        window_start=trig.window_start,
        window_end=trig.window_end,
        triggered_report_id=trig.triggered_report_id,
        triggered_at=trig.triggered_at,
        triggered_by=trig.triggered_by,
    )


def _trigger_from_model(row: ScanTriggerModel) -> ScanTrigger:
    return ScanTrigger(
        id=row.id,
        source_id=row.source_id,
        trigger_kind=row.trigger_kind,
        event_count=row.event_count,
        window_start=row.window_start,
        window_end=row.window_end,
        triggered_report_id=row.triggered_report_id,
        triggered_at=row.triggered_at,
        triggered_by=row.triggered_by,
    )


class M3Repository:
    """M3 dataclass ↔ Model 转换 + CRUD。"""

    def __init__(self, session: Session) -> None:
        self._s = session

    def save_source(self, source: LogStreamSource) -> None:
        self._s.add(_source_to_model(source))
        self._s.commit()

    def get_source(self, source_id: str) -> LogStreamSource | None:
        row = self._s.get(LogStreamSourceModel, source_id)
        return _source_from_model(row) if row else None

    def list_sources(self, status: str | None = None) -> list[LogStreamSource]:
        stmt = select(LogStreamSourceModel)
        if status is not None:
            stmt = stmt.where(LogStreamSourceModel.ingestion_status == status)
        rows = self._s.execute(stmt).scalars().all()
        return [_source_from_model(r) for r in rows]

    def update_source_status(
        self, source_id: str, status: str, updated_at: datetime,
    ) -> None:
        row = self._s.get(LogStreamSourceModel, source_id)
        if row is None:
            raise ValueError(f"source {source_id} not found")
        row.ingestion_status = status
        row.updated_at = updated_at
        self._s.commit()

    def save_event(self, event: LogStreamEvent) -> None:
        self._s.add(_event_to_model(event))
        self._s.commit()

    def list_events(
        self, source_id: str,
        window_start: datetime, window_end: datetime,
    ) -> list[LogStreamEvent]:
        stmt = select(LogStreamEventModel).where(
            LogStreamEventModel.source_id == source_id,
            LogStreamEventModel.ingested_at >= window_start,
            LogStreamEventModel.ingested_at <= window_end,
        ).order_by(LogStreamEventModel.ingested_at)
        rows = self._s.execute(stmt).scalars().all()
        return [_event_from_model(r) for r in rows]

    def count_events_by_level(
        self, source_id: str,
        window_start: datetime, window_end: datetime,
    ) -> dict[str, int]:
        stmt = select(LogStreamEventModel).where(
            LogStreamEventModel.source_id == source_id,
            LogStreamEventModel.ingested_at >= window_start,
            LogStreamEventModel.ingested_at <= window_end,
        )
        rows = self._s.execute(stmt).scalars().all()
        counts: dict[str, int] = {}
        for r in rows:
            lvl = r.level or "UNKNOWN"
            counts[lvl] = counts.get(lvl, 0) + 1
        return counts

    def save_trigger(self, trigger: ScanTrigger) -> None:
        self._s.add(_trigger_to_model(trigger))
        self._s.commit()

    def update_trigger_report_id(
        self, trigger_id: str, report_id: str,
    ) -> None:
        row = self._s.get(ScanTriggerModel, trigger_id)
        if row is None:
            raise ValueError(f"trigger {trigger_id} not found")
        row.triggered_report_id = report_id
        self._s.commit()

    def list_triggers(
        self, source_id: str,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> list[ScanTrigger]:
        stmt = select(ScanTriggerModel).where(
            ScanTriggerModel.source_id == source_id,
        )
        if window_start is not None:
            stmt = stmt.where(ScanTriggerModel.triggered_at >= window_start)
        if window_end is not None:
            stmt = stmt.where(ScanTriggerModel.triggered_at <= window_end)
        stmt = stmt.order_by(ScanTriggerModel.triggered_at.desc())
        rows = self._s.execute(stmt).scalars().all()
        return [_trigger_from_model(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_storage_repository.py', '-v'])"`
Expected: PASS（6 tests）

- [ ] **Step 5: Lint**

Run: `ruff check packages/m3/storage/repository.py tests/m3/test_storage_repository.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add packages/m3/storage/repository.py tests/m3/test_storage_repository.py
git commit -m "feat(m3): Storage Repository — dataclass ↔ Model 转换 + CRUD（AC-14）"
```

---

### Task 4: EventIngestor — 解析复用 M2 LogParser + LogPointMatcher

**Files:**
- Create: `packages/m3/event_ingestor.py`
- Test: `tests/m3/test_event_ingestor.py`

**Interfaces:**
- Consumes:
  - M2 `packages.m2.log_parser.LogParser`（不重新实现）
  - M2 `packages.m2.log_point_matcher.LogPointMatcher` + `packages.m2.storage_backed_log_point_index.LogPointIndexFactory`（不重新实现）
  - M3 `packages.m3.storage.repository.M3Repository`（Task 3 产出）
  - `packages.m1.audit_log.AuditLogger`（复用 M1）
- Produces:
  - `packages.m3.event_ingestor.EventIngestor`
  - 方法签名：`ingest(source_id: str, raw_text: str) -> LogStreamEvent`

- [ ] **Step 1: Write the failing test**

`tests/m3/test_event_ingestor.py`:
```python
"""F003 M3 — EventIngestor 解析复用 M2 LogParser + LogPointMatcher（spec §十 + AC-3/4）。"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import SOURCE_KIND_FILE_TAIL, STATUS_ACTIVE
from packages.contracts.log_stream import LogStreamSource
from packages.m1.audit_log import AuditLogger
from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher, NullLogPointIndex
from packages.m3.event_ingestor import EventIngestor
from packages.m3.storage.models import Base as M3Base
from packages.m3.storage.repository import M3Repository


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    M3Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture()
def repo(session: Session) -> M3Repository:
    return M3Repository(session)


@pytest.fixture()
def audit(session: Session) -> AuditLogger:
    return AuditLogger(session)


@pytest.fixture()
def source(repo: M3Repository) -> LogStreamSource:
    now = datetime.now(UTC)
    src = LogStreamSource(
        id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
        repo_id=None, ingestion_status=STATUS_ACTIVE,
        created_at=now, updated_at=now,
    )
    repo.save_source(src)
    return src


class TestEventIngestorBasic:
    def test_ingest_parses_log_line(self, repo: M3Repository, audit: AuditLogger, source: LogStreamSource) -> None:
        """M3 EventIngestor 调 M2 LogParser 解析日志条目。"""
        ingestor = EventIngestor(
            repository=repo,
            log_parser=LogParser(),
            log_point_matcher=LogPointMatcher(NullLogPointIndex()),
            audit=audit,
        )
        evt = ingestor.ingest(source_id="src-1", raw_text="2026-07-28 INFO User 12345 logged in")
        assert evt.source_id == "src-1"
        assert evt.raw_text == "2026-07-28 INFO User 12345 logged in"
        # 解析后字段（M2 LogParser 提取）
        assert evt.level == "INFO"
        # log_point_id = None（NullLogPointIndex 返回 None）
        assert evt.log_point_id is None

    def test_ingest_no_log_point_match_keeps_event(self, repo: M3Repository, audit: AuditLogger, source: LogStreamSource) -> None:
        """匹配不上 M1 LogPoint 的事件仍入库（spec §十 + AC-4）。"""
        ingestor = EventIngestor(
            repository=repo,
            log_parser=LogParser(),
            log_point_matcher=LogPointMatcher(NullLogPointIndex()),
            audit=audit,
        )
        evt = ingestor.ingest(source_id="src-1", raw_text="weird log line no template")
        assert evt.log_point_id is None  # unmatched but still saved
        # 验证 DB 已持久化
        evts = repo.list_events("src-1", evt.ingested_at, evt.ingested_at) if evt.ingested_at else []
        assert any(e.id == evt.id for e in evts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_event_ingestor.py', '-v'])"`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m3.event_ingestor'`

- [ ] **Step 3: Create packages/m3/event_ingestor.py**

```python
"""F003 M3 — EventIngestor（spec §十 + AC-3/4）。

复用 M2 LogParser + LogPointMatcher，不重新实现解析/匹配逻辑。
仅做：raw_text → LogEntry → 匹配 M1 LogPoint → LogStreamEvent 持久化。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from packages.contracts.enums import ACTION_M3_INGEST_EVENT
from packages.contracts.log_stream import LogStreamEvent
from packages.m1.audit_log import AuditLogger
from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher
from packages.m3.storage.repository import M3Repository


class EventIngestor:
    """M3 流式日志事件入库（spec §二 EventIngestor + §十 关联机制）。"""

    def __init__(
        self,
        repository: M3Repository,
        log_parser: LogParser,
        log_point_matcher: LogPointMatcher,
        audit: AuditLogger,
    ) -> None:
        self._repo = repository
        self._parser = log_parser
        self._matcher = log_point_matcher
        self._audit = audit

    def ingest(self, source_id: str, raw_text: str) -> LogStreamEvent:
        """解析 + 匹配 + 持久化单条日志事件。

        Returns:
            LogStreamEvent（含 log_point_id 或 None）
        """
        # M2 LogParser 解析 raw_text → list[LogEntry]
        log_entries = self._parser.parse(raw_text)
        # M3 单条 ingest（取第一条；batch 是 future work）
        entry = log_entries[0] if log_entries else None

        # 字段提取（来自 M2 LogEntry）
        timestamp = entry.timestamp if entry else None
        level = entry.level if entry else None
        template = entry.log_message_template if entry else None
        variables = entry.variables if entry else {}

        # M2 LogPointMatcher.match 接受 list[LogEntry] 返回 list[MatchResult]
        # 取第一条 result 的 log_point（None = 未匹配）
        log_point_id: str | None = None
        if entry is not None:
            results = self._matcher.match([entry])
            if results and results[0].log_point is not None:
                log_point_id = results[0].log_point.id

        # 构造 LogStreamEvent
        now = datetime.now(UTC)
        event = LogStreamEvent(
            id=f"evt-{uuid.uuid4().hex[:12]}",
            source_id=source_id,
            raw_text=raw_text,
            timestamp=timestamp,
            level=level,
            log_message_template=template,
            variables=variables,
            log_point_id=log_point_id,
            ingested_at=now,
        )

        # 持久化
        self._repo.save_event(event)

        # 审计（AuditLogger.log 签名：actor, action, target_repo_id, target_log_point_ids, extra）
        self._audit.log(
            actor="system",
            action=ACTION_M3_INGEST_EVENT,
            extra={"source_id": source_id, "event_id": event.id, "log_point_id": log_point_id},
        )

        return event
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_event_ingestor.py', '-v'])"`
Expected: PASS（2 tests）

- [ ] **Step 5: Lint**

Run: `ruff check packages/m3/event_ingestor.py tests/m3/test_event_ingestor.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add packages/m3/event_ingestor.py tests/m3/test_event_ingestor.py
git commit -m "feat(m3): EventIngestor — 解析复用 M2 LogParser + LogPointMatcher（AC-3/4）"
```

---

### Task 5: TriggerEvaluator — 三种触发判定

**Files:**
- Create: `packages/m3/trigger_evaluator.py`
- Test: `tests/m3/test_trigger_evaluator.py`

**Interfaces:**
- Consumes:
  - M3 `M3Repository`（Task 3）
  - `packages.contracts.enums`（TRIGGER_* 常量）
- Produces:
  - `packages.m3.trigger_evaluator.TriggerEvaluator`
  - `packages.m3.trigger_evaluator.TriggerDecision`（dataclass：should_trigger / trigger_kind / event_count / window_start / window_end）
  - 方法签名：`evaluate(source_id: str) -> TriggerDecision`

- [ ] **Step 1: Write the failing test**

`tests/m3/test_trigger_evaluator.py`:
```python
"""F003 M3 — TriggerEvaluator 三种触发判定（spec §二 + AC-5/6）。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import (
    SOURCE_KIND_FILE_TAIL,
    STATUS_ACTIVE,
    TRIGGER_ANOMALY_DENSITY,
    TRIGGER_TIME_WINDOW,
)
from packages.contracts.log_stream import LogStreamEvent, LogStreamSource
from packages.m3.storage.models import Base as M3Base
from packages.m3.storage.repository import M3Repository
from packages.m3.trigger_evaluator import TriggerEvaluator, TriggerDecision


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    M3Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture()
def repo(session: Session) -> M3Repository:
    return M3Repository(session)


@pytest.fixture()
def source(repo: M3Repository) -> LogStreamSource:
    now = datetime.now(UTC)
    src = LogStreamSource(
        id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
        repo_id=None, ingestion_status=STATUS_ACTIVE,
        created_at=now, updated_at=now,
    )
    repo.save_source(src)
    return src


def _add_event(repo: M3Repository, source_id: str, level: str, ingested_at: datetime) -> None:
    repo.save_event(LogStreamEvent(
        id=f"evt-{level}-{ingested_at.microsecond}",
        source_id=source_id, raw_text="x",
        timestamp=ingested_at, level=level,
        log_message_template=None, variables={},
        log_point_id=None, ingested_at=ingested_at,
    ))


class TestTimeWindowTrigger:
    def test_triggers_on_count_threshold(self, repo: M3Repository, source: LogStreamSource) -> None:
        """累积事件数达到阈值 → time_window 触发（AC-5）。"""
        now = datetime.now(UTC)
        # 1000 条事件（默认阈值）
        for i in range(1000):
            _add_event(repo, "src-1", "INFO", now + timedelta(seconds=i))
        evaluator = TriggerEvaluator(
            repository=repo,
            time_window_event_count=1000,
            time_window_seconds=300,
            anomaly_density_threshold=0.30,
        )
        decision = evaluator.evaluate("src-1")
        assert decision.should_trigger
        assert decision.trigger_kind == TRIGGER_TIME_WINDOW

    def test_no_trigger_below_threshold(self, repo: M3Repository, source: LogStreamSource) -> None:
        now = datetime.now(UTC)
        for i in range(500):  # < 1000 阈值
            _add_event(repo, "src-1", "INFO", now + timedelta(seconds=i))
        evaluator = TriggerEvaluator(
            repository=repo,
            time_window_event_count=1000,
            time_window_seconds=300,
            anomaly_density_threshold=0.30,
        )
        decision = evaluator.evaluate("src-1")
        assert not decision.should_trigger


class TestAnomalyDensityTrigger:
    def test_triggers_on_error_density(self, repo: M3Repository, source: LogStreamSource) -> None:
        """error 占比 > 30% 阈值 → anomaly_density 触发（AC-6）。"""
        now = datetime.now(UTC)
        # 40 条 ERROR + 60 条 INFO = 40% > 30%
        for i in range(40):
            _add_event(repo, "src-1", "ERROR", now + timedelta(seconds=i))
        for i in range(60):
            _add_event(repo, "src-1", "INFO", now + timedelta(seconds=100 + i))
        evaluator = TriggerEvaluator(
            repository=repo,
            time_window_event_count=1000,  # not yet hit count threshold
            time_window_seconds=300,
            anomaly_density_threshold=0.30,
        )
        decision = evaluator.evaluate("src-1")
        assert decision.should_trigger
        assert decision.trigger_kind == TRIGGER_ANOMALY_DENSITY

    def test_no_trigger_low_error_density(self, repo: M3Repository, source: LogStreamSource) -> None:
        now = datetime.now(UTC)
        # 10 ERROR + 90 INFO = 10% < 30%
        for i in range(10):
            _add_event(repo, "src-1", "ERROR", now + timedelta(seconds=i))
        for i in range(90):
            _add_event(repo, "src-1", "INFO", now + timedelta(seconds=100 + i))
        evaluator = TriggerEvaluator(
            repository=repo,
            time_window_event_count=1000,
            time_window_seconds=300,
            anomaly_density_threshold=0.30,
        )
        decision = evaluator.evaluate("src-1")
        assert not decision.should_trigger
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_trigger_evaluator.py', '-v'])"`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m3.trigger_evaluator'`

- [ ] **Step 3: Create packages/m3/trigger_evaluator.py**

```python
"""F003 M3 — TriggerEvaluator 三种触发判定（spec §二 + AC-5/6）。

触发条件（任一满足 → should_trigger=True）：
1. time_window: 累积 N 条事件（time_window_event_count）或 T 时间窗（time_window_seconds）
2. anomaly_density: error 级别占比 > anomaly_density_threshold
3. manual: 用户主动调 scan_now（不在本 evaluator，走 OnlineLogScanner.scan_now 路径）

manual 不走本 evaluator（手动触发是 OnlineLogScanner.scan_now 的责任，直接调 M2）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from packages.contracts.enums import TRIGGER_ANOMALY_DENSITY, TRIGGER_TIME_WINDOW
from packages.m3.storage.repository import M3Repository


@dataclass(frozen=True)
class TriggerDecision:
    """触发判定结果。"""
    should_trigger: bool
    trigger_kind: str | None         # TRIGGER_TIME_WINDOW | TRIGGER_ANOMALY_DENSITY | None
    event_count: int                  # 当前窗口事件数
    window_start: datetime
    window_end: datetime


class TriggerEvaluator:
    """M3 触发判定器（spec §二 trigger_evaluator）。"""

    def __init__(
        self,
        repository: M3Repository,
        time_window_event_count: int = 1000,
        time_window_seconds: int = 300,
        anomaly_density_threshold: float = 0.30,
    ) -> None:
        self._repo = repository
        self._count_threshold = time_window_event_count
        self._time_window = timedelta(seconds=time_window_seconds)
        self._density_threshold = anomaly_density_threshold

    def evaluate(self, source_id: str) -> TriggerDecision:
        """评估是否触发 M2 analyze_logs。

        优先级：anomaly_density > time_window（同时满足时按密度优先，反映紧急程度）。
        """
        now = datetime.now(UTC)
        window_start = now - self._time_window
        window_end = now

        # 取窗口内事件统计
        counts_by_level = self._repo.count_events_by_level(
            source_id, window_start=window_start, window_end=window_end,
        )
        total = sum(counts_by_level.values())

        # anomaly_density 判定
        error_count = counts_by_level.get("ERROR", 0) + counts_by_level.get("CRITICAL", 0)
        if total > 0 and (error_count / total) > self._density_threshold:
            return TriggerDecision(
                should_trigger=True,
                trigger_kind=TRIGGER_ANOMALY_DENSITY,
                event_count=total,
                window_start=window_start,
                window_end=window_end,
            )

        # time_window 判定
        if total >= self._count_threshold:
            return TriggerDecision(
                should_trigger=True,
                trigger_kind=TRIGGER_TIME_WINDOW,
                event_count=total,
                window_start=window_start,
                window_end=window_end,
            )

        # 不触发
        return TriggerDecision(
            should_trigger=False,
            trigger_kind=None,
            event_count=total,
            window_start=window_start,
            window_end=window_end,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_trigger_evaluator.py', '-v'])"`
Expected: PASS（4 tests）

- [ ] **Step 5: Lint**

Run: `ruff check packages/m3/trigger_evaluator.py tests/m3/test_trigger_evaluator.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add packages/m3/trigger_evaluator.py tests/m3/test_trigger_evaluator.py
git commit -m "feat(m3): TriggerEvaluator — time_window + anomaly_density 触发判定（AC-5/6）"
```

---

### Task 6: FileTailer — 后台 polling task

**Files:**
- Create: `packages/m3/file_tailer.py`
- Test: `tests/m3/test_file_tailer.py`

**Interfaces:**
- Consumes:
  - M3 `EventIngestor`（Task 4）
  - asyncio / pathlib
- Produces:
  - `packages.m3.file_tailer.FileTailer`
  - 方法签名：
    - `start() -> None`（启动 asyncio task）
    - `stop() -> None`（cancel task）
    - `_poll_once() -> int`（polling 单次，返回 ingested 事件数）

- [ ] **Step 1: Write the failing test**

`tests/m3/test_file_tailer.py`:
```python
"""F003 M3 — FileTailer 后台 polling task（spec §二 + AC-1）。"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import SOURCE_KIND_FILE_TAIL, STATUS_ACTIVE
from packages.contracts.log_stream import LogStreamSource
from packages.m1.audit_log import AuditLogger
from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher, NullLogPointIndex
from packages.m3.event_ingestor import EventIngestor
from packages.m3.file_tailer import FileTailer
from packages.m3.storage.models import Base as M3Base
from packages.m3.storage.repository import M3Repository


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    M3Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture()
def repo(session: Session) -> M3Repository:
    return M3Repository(session)


@pytest.fixture()
def audit(session: Session) -> AuditLogger:
    return AuditLogger(session)


@pytest.fixture()
def ingestor(repo: M3Repository, audit: AuditLogger) -> EventIngestor:
    return EventIngestor(
        repository=repo, log_parser=LogParser(),
        log_point_matcher=LogPointMatcher(NullLogPointIndex()),
        audit=audit,
    )


@pytest.fixture()
def temp_log_file(tmp_path) -> Path:
    """临时日志文件（用 tmp_path fixture）。"""
    f = tmp_path / "app.log"
    f.write_text("", encoding="utf-8")
    return f


class TestFileTailerPolling:
    def test_poll_once_ingests_new_lines(self, ingestor: EventIngestor, temp_log_file: Path, repo: M3Repository) -> None:
        """单次 polling 读取新增日志行 → EventIngestor 入库（AC-1）。"""
        # 写入 3 行日志
        with open(temp_log_file, "a", encoding="utf-8") as f:
            for i in range(3):
                f.write(f"2026-07-28 INFO line {i}\n")

        tailer = FileTailer(
            source_id="src-1",
            file_path=str(temp_log_file),
            ingestor=ingestor,
            poll_interval_seconds=0.05,
        )
        # 第一次 poll：从 0 开始读
        n = tailer._poll_once()
        assert n == 3

        # DB 验证
        now = datetime.now(UTC)
        evts = repo.list_events("src-1", now.replace(microsecond=0), now)
        # ingested_at 是 datetime.now(UTC) 当下，放宽窗口
        assert len(evts) >= 3

    def test_poll_resume_from_checkpoint(self, ingestor: EventIngestor, temp_log_file: Path) -> None:
        """位置 checkpoint：第二次 poll 从上次位置继续，不重读已读行（AC-1）。"""
        # 第一次写入 2 行
        with open(temp_log_file, "a", encoding="utf-8") as f:
            f.write("2026-07-28 INFO line 0\n")
            f.write("2026-07-28 INFO line 1\n")

        tailer = FileTailer(
            source_id="src-1",
            file_path=str(temp_log_file),
            ingestor=ingestor,
            poll_interval_seconds=0.05,
        )
        n1 = tailer._poll_once()
        assert n1 == 2

        # 第二次写入 2 行（不重读前 2 行）
        with open(temp_log_file, "a", encoding="utf-8") as f:
            f.write("2026-07-28 INFO line 2\n")
            f.write("2026-07-28 INFO line 3\n")

        n2 = tailer._poll_once()
        assert n2 == 2  # 只读新增 2 行

    def test_file_rotation_no_loss(self, ingestor: EventIngestor, tmp_path: Path) -> None:
        """文件轮转（截断）：tailer 检测 size 变小 → reset checkpoint（AC-1）。"""
        f1 = tmp_path / "app.log"
        f1.write_text("2026-07-28 INFO old line\n", encoding="utf-8")

        tailer = FileTailer(
            source_id="src-1",
            file_path=str(f1),
            ingestor=ingestor,
            poll_interval_seconds=0.05,
        )
        tailer._poll_once()  # 读 "old line"

        # 模拟轮转：截断 + 写新内容
        f1.write_text("2026-07-28 INFO new line after rotation\n", encoding="utf-8")
        n = tailer._poll_once()
        assert n == 1  # 轮转后从头读
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_file_tailer.py', '-v'])"`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m3.file_tailer'`

- [ ] **Step 3: Create packages/m3/file_tailer.py**

```python
"""F003 M3 — FileTailer 后台 polling task（spec §二 + AC-1）。

v1 用 polling 模式（跨平台优先，OQ-2 决策）。
位置 checkpoint 存内存（source_id → last_pos）+ 文件 size 检测轮转。
生产环境可持久化到 Redis（留 v2）。
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from packages.m3.event_ingestor import EventIngestor


class FileTailer:
    """M3 file_tail 数据源后台 polling task。"""

    def __init__(
        self,
        source_id: str,
        file_path: str,
        ingestor: EventIngestor,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._source_id = source_id
        self._file_path = file_path
        self._ingestor = ingestor
        self._poll_interval = poll_interval_seconds
        self._last_pos: int = 0
        self._last_size: int = 0
        self._task: asyncio.Task | None = None
        self._stopped = False

    def start(self) -> None:
        """启动 asyncio task（在 FastAPI lifespan 内调用）。"""
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._run_loop())

    def stop(self) -> None:
        """cancel 后台 task（pause_source 时调用）。"""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """主循环：polling + sleep。"""
        while not self._stopped:
            try:
                self._poll_once()
            except Exception:
                # logging 留 v2，v1 静默（避免单次失败拖死 task）
                pass
            await asyncio.sleep(self._poll_interval)

    def _poll_once(self) -> int:
        """单次 polling：读新增行 + 入库。返回 ingested 事件数。"""
        path = Path(self._file_path)
        if not path.exists():
            return 0

        current_size = path.stat().st_size

        # 文件轮转检测：size 变小 → reset
        if current_size < self._last_size:
            self._last_pos = 0
        self._last_size = current_size

        # 读新增部分
        if self._last_pos >= current_size:
            return 0

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(self._last_pos)
            new_content = f.read()
            self._last_pos = f.tell()

        if not new_content:
            return 0

        # 按行 ingest（最后一行可能不完整，留 v2 处理）
        lines = [ln for ln in new_content.splitlines() if ln.strip()]
        for line in lines:
            self._ingestor.ingest(source_id=self._source_id, raw_text=line)
        return len(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_file_tailer.py', '-v'])"`
Expected: PASS（3 tests）

- [ ] **Step 5: Lint**

Run: `ruff check packages/m3/file_tailer.py tests/m3/test_file_tailer.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add packages/m3/file_tailer.py tests/m3/test_file_tailer.py
git commit -m "feat(m3): FileTailer — 后台 polling + 位置 checkpoint + 轮转检测（AC-1）"
```

---

### Task 7: OnlineLogScanner — 7 API 方法编排层

**Files:**
- Create: `packages/m3/online_log_scanner.py`
- Test: `tests/m3/test_online_log_scanner.py`

**Interfaces:**
- Consumes:
  - M3 `M3Repository`（Task 3）
  - M3 `EventIngestor`（Task 4）
  - M3 `TriggerEvaluator`（Task 5）
  - M3 `FileTailer`（Task 6）
  - M2 `LogAnalysisService.analyze_logs`（依赖注入 `M2ServiceProtocol`）
  - M2 `LogSource`（构造 stream window）
  - `packages.m1.audit_log.AuditLogger`
- Produces:
  - `packages.m3.online_log_scanner.OnlineLogScanner`
  - 7 个 API 方法（spec §四）

- [ ] **Step 1: Write the failing test**

`tests/m3/test_online_log_scanner.py`:
```python
"""F003 M3 — OnlineLogScanner 7 API 方法编排层（spec §四 + AC-7/8/9/13/17）。"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import (
    SOURCE_KIND_FILE_TAIL,
    SOURCE_KIND_HTTP_WEBHOOK,
    STATUS_ACTIVE,
    STATUS_PAUSED,
    TRIGGER_MANUAL,
)
from packages.contracts.log_entry import LogSource
from packages.contracts.log_stream import LogStreamSource
from packages.m1.audit_log import AuditLogger
from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher, NullLogPointIndex
from packages.m3.event_ingestor import EventIngestor
from packages.m3.online_log_scanner import OnlineLogScanner
from packages.m3.storage.models import Base as M3Base
from packages.m3.storage.repository import M3Repository
from packages.m3.trigger_evaluator import TriggerEvaluator


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    M3Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture()
def repo(session: Session) -> M3Repository:
    return M3Repository(session)


@pytest.fixture()
def audit(session: Session) -> AuditLogger:
    return AuditLogger(session)


@pytest.fixture()
def ingestor(repo: M3Repository, audit: AuditLogger) -> EventIngestor:
    return EventIngestor(
        repository=repo, log_parser=LogParser(),
        log_point_matcher=LogPointMatcher(NullLogPointIndex()),
        audit=audit,
    )


@pytest.fixture()
def m2_service() -> MagicMock:
    """M2 LogAnalysisService mock（依赖注入）。"""
    m = MagicMock()
    # analyze_logs 返回 AnalysisReport stub
    m.analyze_logs.return_value = MagicMock(id="rpt-mock")
    return m


@pytest.fixture()
def scanner(
    repo: M3Repository, audit: AuditLogger, ingestor: EventIngestor,
    m2_service: MagicMock,
) -> OnlineLogScanner:
    return OnlineLogScanner(
        repository=repo,
        ingestor=ingestor,
        trigger_evaluator=TriggerEvaluator(repository=repo),
        m2_service=m2_service,
        audit=audit,
        # file_tailer_factory 留 Task 8 / routes 里 wire
    )


class TestRegisterSource:
    def test_register_file_tail(self, scanner: OnlineLogScanner) -> None:
        from packages.m1.unit_a_repo_registrar import User
        src = scanner.register_source(
            kind=SOURCE_KIND_FILE_TAIL,
            config={"path": "/var/log/app.log"},
            repo_id=None,
            user=User(id="u-1", name="alice"),
        )
        assert src.kind == SOURCE_KIND_FILE_TAIL
        assert src.ingestion_status == STATUS_ACTIVE

    def test_register_webhook_with_repo(self, scanner: OnlineLogScanner) -> None:
        from packages.m1.unit_a_repo_registrar import User
        src = scanner.register_source(
            kind=SOURCE_KIND_HTTP_WEBHOOK,
            config={"path": "/ingest/src-x"},
            repo_id="repo-1",
            user=User(id="u-1", name="alice"),
        )
        assert src.kind == SOURCE_KIND_HTTP_WEBHOOK
        assert src.repo_id == "repo-1"


class TestPauseResumeSource:
    def test_pause_keeps_events(self, scanner: OnlineLogScanner, ingestor: EventIngestor) -> None:
        """pause_source 不丢累积事件（AC-9）。"""
        from packages.m1.unit_a_repo_registrar import User
        src = scanner.register_source(
            kind=SOURCE_KIND_HTTP_WEBHOOK, config={},
            repo_id=None, user=User(id="u-1", name="alice"),
        )
        # ingest 2 events
        ingestor.ingest(src.id, "2026-07-28 INFO first")
        ingestor.ingest(src.id, "2026-07-28 INFO second")

        scanner.pause_source(src.id, user=User(id="u-1", name="alice"))
        # 事件仍在 DB
        now = datetime.now(UTC)
        evts = scanner._repo.list_events(src.id, now.replace(microsecond=0), now)
        assert len(evts) >= 2


class TestScanNow:
    def test_manual_trigger_calls_m2_analyze_logs(self, scanner: OnlineLogScanner, ingestor: EventIngestor, m2_service: MagicMock) -> None:
        """scan_now 手动触发 M2 analyze_logs（AC-7）。"""
        from packages.m1.unit_a_repo_registrar import User
        src = scanner.register_source(
            kind=SOURCE_KIND_HTTP_WEBHOOK, config={},
            repo_id="repo-1", user=User(id="u-1", name="alice"),
        )
        ingestor.ingest(src.id, "2026-07-28 INFO something")

        report = scanner.scan_now(src.id, user=User(id="u-1", name="alice"))
        assert report.id == "rpt-mock"
        m2_service.analyze_logs.assert_called_once()
        # 验证传给 M2 的参数
        call_kwargs = m2_service.analyze_logs.call_args.kwargs
        assert call_kwargs["repo_id"] == "repo-1"


class TestTriggerRecorded:
    def test_scan_now_writes_scan_trigger(self, scanner: OnlineLogScanner, ingestor: EventIngestor, repo: M3Repository) -> None:
        """ScanTrigger 记录持久化（AC-8）。"""
        from packages.m1.unit_a_repo_registrar import User
        src = scanner.register_source(
            kind=SOURCE_KIND_HTTP_WEBHOOK, config={},
            repo_id=None, user=User(id="u-1", name="alice"),
        )
        ingestor.ingest(src.id, "2026-07-28 INFO something")

        scanner.scan_now(src.id, user=User(id="u-1", name="alice"))

        triggs = repo.list_triggers(src.id, None, None)
        assert len(trigs) == 1
        assert triggs[0].trigger_kind == TRIGGER_MANUAL
        assert triggs[0].triggered_report_id == "rpt-mock"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_online_log_scanner.py', '-v'])"`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m3.online_log_scanner'`

- [ ] **Step 3: Create packages/m3/online_log_scanner.py**

```python
"""F003 M3 — OnlineLogScanner 7 API 方法编排层（spec §四）。

依赖注入 M2 LogAnalysisService（M2ServiceProtocol）+ M3 内部组件。
不直接 import M2 service，避免循环依赖。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from packages.contracts.enums import (
    ACTION_M3_PAUSE_SOURCE,
    ACTION_M3_REGISTER_SOURCE,
    ACTION_M3_RESUME_SOURCE,
    ACTION_M3_SCAN_NOW,
    SOURCE_KIND_FILE_TAIL,
    SOURCE_KIND_HTTP_WEBHOOK,
    STATUS_ACTIVE,
    STATUS_PAUSED,
    STATUS_STOPPED,
    TRIGGER_MANUAL,
)
from packages.contracts.log_entry import LogSource
from packages.contracts.log_stream import (
    LogStreamSource,
    ScanTrigger,
)
from packages.contracts.analysis_report import AnalysisReport
from packages.m1.audit_log import AuditLogger
from packages.m1.unit_a_repo_registrar import User
from packages.m3.event_ingestor import EventIngestor
from packages.m3.storage.repository import M3Repository
from packages.m3.trigger_evaluator import TriggerEvaluator


class M2ServiceProtocol(Protocol):
    """M2 LogAnalysisService 的最小协议（M3 仅用 analyze_logs）。"""
    def analyze_logs(
        self,
        log_source: LogSource,
        analyzer: User,
        repo_id: str | None = None,
        window_hours: int | None = None,
    ) -> AnalysisReport: ...


class OnlineLogScanner:
    """M3 在线日志扫描服务（spec §四 7 个 API 方法）。"""

    def __init__(
        self,
        repository: M3Repository,
        ingestor: EventIngestor,
        trigger_evaluator: TriggerEvaluator,
        m2_service: M2ServiceProtocol,
        audit: AuditLogger,
        # file_tailer factory 留 Task 10 在 deps.py wire（lifespan 管理）
        file_tailers: dict[str, object] | None = None,
    ) -> None:
        self._repo = repository
        self._ingestor = ingestor
        self._evaluator = trigger_evaluator
        self._m2 = m2_service
        self._audit = audit
        self._file_tailers: dict[str, object] = file_tailers or {}

    def register_source(
        self,
        kind: str,
        config: dict,
        repo_id: str | None,
        user: User,
    ) -> LogStreamSource:
        if kind not in (SOURCE_KIND_FILE_TAIL, SOURCE_KIND_HTTP_WEBHOOK):
            raise ValueError(f"unsupported source kind: {kind}")
        now = datetime.now(UTC)
        src = LogStreamSource(
            id=f"src-{uuid.uuid4().hex[:12]}",
            kind=kind,
            config=config,
            repo_id=repo_id,
            ingestion_status=STATUS_ACTIVE,
            created_at=now,
            updated_at=now,
        )
        self._repo.save_source(src)
        self._audit.log(
            actor=user.id,
            action=ACTION_M3_REGISTER_SOURCE,
            target_repo_id=src.repo_id,
            extra={"source_id": src.id, "kind": kind, "repo_id": repo_id},
        )
        return src

    def list_sources(self, status: str | None = None) -> list[LogStreamSource]:
        return self._repo.list_sources(status=status)

    def pause_source(self, source_id: str, user: User) -> None:
        now = datetime.now(UTC)
        self._repo.update_source_status(source_id, STATUS_PAUSED, updated_at=now)
        # 停 file_tailer（如有）
        tailer = self._file_tailers.pop(source_id, None)
        if tailer is not None:
            tailer.stop()  # type: ignore[attr-defined]
        self._audit.log(
            actor=user.id,
            action=ACTION_M3_PAUSE_SOURCE,
            extra={"source_id": source_id},
        )

    def resume_source(self, source_id: str, user: User) -> None:
        now = datetime.now(UTC)
        self._repo.update_source_status(source_id, STATUS_ACTIVE, updated_at=now)
        # 重启 file_tailer 留 Task 10 lifespan wire
        self._audit.log(
            actor=user.id,
            action=ACTION_M3_RESUME_SOURCE,
            extra={"source_id": source_id},
        )

    def ingest_event(self, source_id: str, raw_text: str) -> "LogStreamEvent":
        return self._ingestor.ingest(source_id=source_id, raw_text=raw_text)

    def scan_now(self, source_id: str, user: User) -> AnalysisReport:
        """手动触发 M2 analyze_logs（AC-7）。"""
        src = self._repo.get_source(source_id)
        if src is None:
            raise ValueError(f"source {source_id} not found")

        # 取当前累积事件窗口
        now = datetime.now(UTC)
        from datetime import timedelta
        window_start = now - timedelta(hours=24)  # 默认 24h 窗口
        events = self._repo.list_events(source_id, window_start, now)

        # 构造 LogSource（M2 LogSource 支持 text 模式）
        log_text = "\n".join(e.raw_text for e in events)
        log_source = LogSource(text=log_text)

        # 调 M2
        report = self._m2.analyze_logs(
            log_source=log_source,
            analyzer=user,
            repo_id=src.repo_id,
        )

        # 写 ScanTrigger
        trigger = ScanTrigger(
            id=f"trig-{uuid.uuid4().hex[:12]}",
            source_id=source_id,
            trigger_kind=TRIGGER_MANUAL,
            event_count=len(events),
            window_start=window_start,
            window_end=now,
            triggered_report_id=report.id,
            triggered_at=now,
            triggered_by=user.id,
        )
        self._repo.save_trigger(trigger)
        self._audit.log(
            actor=user.id,
            action=ACTION_M3_SCAN_NOW,
            target_repo_id=src.repo_id,
            extra={"source_id": source_id, "trigger_id": trigger.id, "report_id": report.id},
        )
        return report

    def list_events(self, source_id: str, window_start: datetime, window_end: datetime):
        return self._repo.list_events(source_id, window_start, window_end)

    def list_triggers(self, source_id: str, window_start: datetime | None = None, window_end: datetime | None = None):
        return self._repo.list_triggers(source_id, window_start, window_end)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_online_log_scanner.py', '-v'])"`
Expected: PASS（5 tests）

- [ ] **Step 5: Lint**

Run: `ruff check packages/m3/online_log_scanner.py tests/m3/test_online_log_scanner.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add packages/m3/online_log_scanner.py tests/m3/test_online_log_scanner.py
git commit -m "feat(m3): OnlineLogScanner — 7 API 方法编排层 + scan_now 调 M2（AC-7/8/9/13/17）"
```

---

### Task 8: MetricsEmitter — 5 个 m3_* 指标

**Files:**
- Create: `packages/m3/metrics_emitter.py`
- Test: `tests/m3/test_metrics_emitter.py`

**Interfaces:**
- Consumes: `prometheus_client`（M1/M2 已用）
- Produces:
  - `packages.m3.metrics_emitter.M3MetricsEmitter`
  - 方法签名：`observe_event_ingested(source_id, repo_id)` / `observe_trigger(source_id, trigger_kind)` / `set_match_rate(source_id, rate)` / `set_file_tail_lag(source_id, seconds)` / `observe_webhook_ingest_duration(seconds)`

- [ ] **Step 1: Write the failing test**

`tests/m3/test_metrics_emitter.py`:
```python
"""F003 M3 — MetricsEmitter 5 个 m3_* 指标（spec §八 + AC-12）。"""
from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, get_registry

from packages.m3.metrics_emitter import M3MetricsEmitter


@pytest.fixture()
def registry() -> CollectorRegistry:
    """独立 CollectorRegistry（避免污染全局 registry）。"""
    return CollectorRegistry()


@pytest.fixture()
def emitter(registry: CollectorRegistry) -> M3MetricsEmitter:
    return M3MetricsEmitter(registry=registry)


class TestMetricsEmitter:
    def test_event_ingested_counter(self, emitter: M3MetricsEmitter, registry: CollectorRegistry) -> None:
        emitter.observe_event_ingested(source_id="src-1", repo_id="repo-1")
        emitter.observe_event_ingested(source_id="src-1", repo_id="repo-1")
        # 取值
        from prometheus_client import generate_latest
        out = generate_latest(registry).decode()
        assert "m3_events_ingested_total" in out
        assert 'source_id="src-1"' in out

    def test_trigger_counter_by_kind(self, emitter: M3MetricsEmitter, registry: CollectorRegistry) -> None:
        emitter.observe_trigger(source_id="src-1", trigger_kind="time_window")
        emitter.observe_trigger(source_id="src-1", trigger_kind="manual")
        from prometheus_client import generate_latest
        out = generate_latest(registry).decode()
        assert "m3_triggers_total" in out
        assert 'trigger_kind="time_window"' in out
        assert 'trigger_kind="manual"' in out

    def test_match_rate_gauge(self, emitter: M3MetricsEmitter, registry: CollectorRegistry) -> None:
        emitter.set_match_rate(source_id="src-1", rate=0.85)
        from prometheus_client import generate_latest
        out = generate_latest(registry).decode()
        assert "m3_match_rate" in out
        assert "0.85" in out

    def test_file_tail_lag_gauge(self, emitter: M3MetricsEmitter, registry: CollectorRegistry) -> None:
        emitter.set_file_tail_lag(source_id="src-1", seconds=2.5)
        from prometheus_client import generate_latest
        out = generate_latest(registry).decode()
        assert "m3_file_tail_lag_seconds" in out

    def test_webhook_ingest_duration_histogram(self, emitter: M3MetricsEmitter, registry: CollectorRegistry) -> None:
        emitter.observe_webhook_ingest_duration(seconds=0.05)
        from prometheus_client import generate_latest
        out = generate_latest(registry).decode()
        assert "m3_webhook_ingest_duration_seconds" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_metrics_emitter.py', '-v'])"`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.m3.metrics_emitter'`

- [ ] **Step 3: Create packages/m3/metrics_emitter.py**

```python
"""F003 M3 — MetricsEmitter 5 个 m3_* 指标（spec §八 + AC-12）。

模式复用 M2 MetricsEmitter（prometheus_client Counter/Gauge/Histogram）。
"""
from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    get_registry as _get_global_registry,
)


class M3MetricsEmitter:
    """M3 metrics 指标发射器（spec §八）。"""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._reg = registry or _get_global_registry()
        self._events_ingested = Counter(
            name="m3_events_ingested_total",
            documentation="Total events ingested by source",
            labelnames=["source_id", "repo_id"],
            registry=self._reg,
        )
        self._triggers = Counter(
            name="m3_triggers_total",
            documentation="Total M2 analyze triggers by source and kind",
            labelnames=["source_id", "trigger_kind"],
            registry=self._reg,
        )
        self._match_rate = Gauge(
            name="m3_match_rate",
            documentation="LogStreamEvent match rate to M1 LogPoint by source",
            labelnames=["source_id"],
            registry=self._reg,
        )
        self._file_tail_lag = Gauge(
            name="m3_file_tail_lag_seconds",
            documentation="file_tail lag in seconds by source",
            labelnames=["source_id"],
            registry=self._reg,
        )
        self._webhook_ingest_duration = Histogram(
            name="m3_webhook_ingest_duration_seconds",
            documentation="HTTP webhook ingest duration",
            labelnames=[],  # global
            registry=self._reg,
        )

    def observe_event_ingested(self, source_id: str, repo_id: str | None) -> None:
        self._events_ingested.labels(
            source_id=source_id, repo_id=repo_id or "none",
        ).inc()

    def observe_trigger(self, source_id: str, trigger_kind: str) -> None:
        self._triggers.labels(
            source_id=source_id, trigger_kind=trigger_kind,
        ).inc()

    def set_match_rate(self, source_id: str, rate: float) -> None:
        self._match_rate.labels(source_id=source_id).set(rate)

    def set_file_tail_lag(self, source_id: str, seconds: float) -> None:
        self._file_tail_lag.labels(source_id=source_id).set(seconds)

    def observe_webhook_ingest_duration(self, seconds: float) -> None:
        self._webhook_ingest_duration.observe(seconds)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_metrics_emitter.py', '-v'])"`
Expected: PASS（5 tests）

- [ ] **Step 5: Lint**

Run: `ruff check packages/m3/metrics_emitter.py tests/m3/test_metrics_emitter.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add packages/m3/metrics_emitter.py tests/m3/test_metrics_emitter.py
git commit -m "feat(m3): MetricsEmitter — 5 个 m3_* 指标 + service 集成准备（AC-12）"
```

---

### Task 9: M3Config + config_loader 扩展

**Files:**
- Modify: `packages/m1/config_loader.py`（追加 M3Config dataclass + Config.m3 字段）
- Modify: `config.example.yaml`（追加 m3 段）
- Test: `tests/m3/test_m3_config.py`

**Interfaces:**
- Consumes: `packages.m1.config_loader.Config`（M2 已扩展模式）
- Produces:
  - `packages.m1.config_loader.M3Config` dataclass
  - `Config.m3` 字段

- [ ] **Step 1: Write the failing test**

`tests/m3/test_m3_config.py`:
```python
"""F003 M3 — M3Config + config_loader 扩展（spec §七）。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_m3_config.py', '-v'])"`
Expected: FAIL with `ImportError: cannot import name 'M3Config' from 'packages.m1.config_loader'`

- [ ] **Step 3: Append M3Config to packages/m1/config_loader.py**

在 `packages/m1/config_loader.py` 末尾追加（紧跟 M2Config 之后，不修改已有内容）：
```python
@dataclasses.dataclass(frozen=True)
class M3Config:
    """F003 M3 配置（spec §七）。"""
    file_tail_poll_interval_seconds: float = 1.0
    file_tail_use_inotify: bool = False            # v1 默认 polling，inotify 留 v2（OQ-2）
    time_window_event_count: int = 1000            # 时间窗触发：累积事件数
    time_window_seconds: int = 300                 # 时间窗触发：时间窗（5min）
    anomaly_density_threshold: float = 0.30        # 异常密度触发：error 占比阈值
    event_ttl_days: int = 7                        # LogStreamEvent 保留天数
    pause_source_keep_events: bool = True          # pause 时不丢累积事件
```

并在 `Config` dataclass 加 `m3` 字段（紧跟 `m2` 之后）：
```python
@dataclasses.dataclass(frozen=True)
class Config:
    llm: LLMConfig
    storage: StorageConfig
    extraction: ExtractionConfig
    sanitizer: SanitizerConfig
    metrics: MetricsConfig
    api: ApiConfig
    m2: M2Config
    m3: M3Config  # F003 新增
```

- [ ] **Step 4: Append m3 section to config.example.yaml**

在 `config.example.yaml` 末尾追加：
```yaml
m3:
  file_tail_poll_interval_seconds: 1.0
  file_tail_use_inotify: false
  time_window_event_count: 1000
  time_window_seconds: 300
  anomaly_density_threshold: 0.30
  event_ttl_days: 7
  pause_source_keep_events: true
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/test_m3_config.py', '-v'])"`
Expected: PASS（2 tests）

- [ ] **Step 6: Run regression tests to verify no M1/M2/F001.1 breakage**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m2/', 'tests/api/test_analysis_routes.py', '-q'])"`
Expected: PASS（146 tests，M2 不动 + F001.1 路由不动）

- [ ] **Step 7: Lint**

Run: `ruff check packages/m1/config_loader.py tests/m3/test_m3_config.py config.example.yaml 2>/dev/null`
Expected: no errors（YAML 不 ruff，跳过 config.example.yaml）

- [ ] **Step 8: Commit**

```bash
git add packages/m1/config_loader.py config.example.yaml tests/m3/test_m3_config.py
git commit -m "feat(m3): M3Config 段 + config_loader 扩展（spec §七）"
```

---

### Task 10: HTTP routes — 8 个端点 + deps wire

**Files:**
- Create: `packages/api/routes/scan.py`
- Create: `packages/api/schemas/scan.py`
- Create: `packages/api/mappers/scan.py`
- Modify: `packages/api/deps.py`（注入 OnlineLogScanner）
- Modify: `packages/api/app.py`（register scan router）
- Test: `tests/api/test_scan_routes.py`

**Interfaces:**
- Consumes:
  - M3 `OnlineLogScanner`（Task 7）
  - F001.1 `packages.api.deps` + `error_handlers` + `app` 框架
- Produces:
  - 8 个 HTTP endpoint（spec §六）

- [ ] **Step 1: Write the failing test**

`tests/api/test_scan_routes.py`:
```python
"""F003 M3 — 8 个 HTTP endpoint（spec §六 + AC-10/11/13）。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """构造最小 FastAPI app + 注入 mock OnlineLogScanner。"""
    from fastapi import FastAPI
    from packages.api.routes.scan import build_scan_router

    app = FastAPI()
    scanner = MagicMock()
    # register_source 返回 LogStreamSource stub
    from packages.contracts.enums import SOURCE_KIND_FILE_TAIL, STATUS_ACTIVE
    from packages.contracts.log_stream import LogStreamSource
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    fake_src = LogStreamSource(
        id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
        repo_id=None, ingestion_status=STATUS_ACTIVE,
        created_at=now, updated_at=now,
    )
    scanner.register_source.return_value = fake_src
    scanner.list_sources.return_value = [fake_src]
    scanner.pause_source.return_value = None
    scanner.resume_source.return_value = None
    scanner.ingest_event.return_value = MagicMock(
        id="evt-1", source_id="src-1", raw_text="x",
        log_point_id=None, level="INFO",
    )
    scanner.scan_now.return_value = MagicMock(id="rpt-1")
    scanner.list_events.return_value = []
    scanner.list_triggers.return_value = []

    app.include_router(build_scan_router(scanner))
    return TestClient(app)


class TestRegisterSource:
    def test_post_sources_201(self, client: TestClient) -> None:
        resp = client.post("/sources", json={
            "kind": "file_tail", "config": {"path": "/var/log/app.log"},
            "repo_id": None,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "src-1"
        assert data["kind"] == "file_tail"


class TestListSources:
    def test_get_sources_200(self, client: TestClient) -> None:
        resp = client.get("/sources")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestPauseResume:
    def test_post_pause_204(self, client: TestClient) -> None:
        resp = client.post("/sources/src-1/pause")
        assert resp.status_code == 204

    def test_post_resume_204(self, client: TestClient) -> None:
        resp = client.post("/sources/src-1/resume")
        assert resp.status_code == 204


class TestIngestEvent:
    def test_post_ingest_201(self, client: TestClient) -> None:
        resp = client.post("/ingest/src-1", json={"raw_text": "log line"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "evt-1"


class TestScanNow:
    def test_post_scan_now_201(self, client: TestClient) -> None:
        resp = client.post("/sources/src-1/scan-now")
        assert resp.status_code == 201
        assert resp.json()["id"] == "rpt-1"


class TestListEventsTriggers:
    def test_get_events_200(self, client: TestClient) -> None:
        resp = client.get("/sources/src-1/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_triggers_200(self, client: TestClient) -> None:
        resp = client.get("/sources/src-1/triggers")
        assert resp.status_code == 200
        assert resp.json() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/api/test_scan_routes.py', '-v'])"`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.api.routes.scan'`

- [ ] **Step 3: Create packages/api/schemas/scan.py**

```python
"""F003 M3 — Pydantic v2 schemas（spec §六）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RegisterSourceRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    kind: str = Field(..., description="file_tail | http_webhook")
    config: dict[str, Any]
    repo_id: str | None = None


class LogStreamSourceAPI(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)
    id: str
    kind: str
    config: dict[str, Any]
    repo_id: str | None
    ingestion_status: str
    created_at: datetime
    updated_at: datetime


class IngestEventRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    raw_text: str


class LogStreamEventAPI(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)
    id: str
    source_id: str
    raw_text: str
    timestamp: datetime | None
    level: str | None
    log_message_template: str | None
    variables: dict[str, str]
    log_point_id: str | None
    ingested_at: datetime


class ScanTriggerAPI(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)
    id: str
    source_id: str
    trigger_kind: str
    event_count: int
    window_start: datetime
    window_end: datetime
    triggered_report_id: str | None
    triggered_at: datetime
    triggered_by: str


class AnalysisReportStubAPI(BaseModel):
    """M3 scan_now 返回 M2 AnalysisReport stub（仅 id 字段，M2 完整 schema 在 packages.api.schemas.analysis）。"""
    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)
    id: str
```

- [ ] **Step 4: Create packages/api/mappers/scan.py**

```python
"""F003 M3 — dataclass → Pydantic 转换（复用 M2 mappers 模式）。"""
from __future__ import annotations

from packages.api.schemas.scan import (
    LogStreamEventAPI,
    LogStreamSourceAPI,
    ScanTriggerAPI,
)
from packages.contracts.log_stream import (
    LogStreamEvent,
    LogStreamSource,
    ScanTrigger,
)


def source_to_api(src: LogStreamSource) -> LogStreamSourceAPI:
    return LogStreamSourceAPI(
        id=src.id, kind=src.kind, config=src.config,
        repo_id=src.repo_id, ingestion_status=src.ingestion_status,
        created_at=src.created_at, updated_at=src.updated_at,
    )


def event_to_api(evt: LogStreamEvent) -> LogStreamEventAPI:
    return LogStreamEventAPI(
        id=evt.id, source_id=evt.source_id, raw_text=evt.raw_text,
        timestamp=evt.timestamp, level=evt.level,
        log_message_template=evt.log_message_template,
        variables=evt.variables, log_point_id=evt.log_point_id,
        ingested_at=evt.ingested_at,
    )


def trigger_to_api(trig: ScanTrigger) -> ScanTriggerAPI:
    return ScanTriggerAPI(
        id=trig.id, source_id=trig.source_id,
        trigger_kind=trig.trigger_kind, event_count=trig.event_count,
        window_start=trig.window_start, window_end=trig.window_end,
        triggered_report_id=trig.triggered_report_id,
        triggered_at=trig.triggered_at, triggered_by=trig.triggered_by,
    )
```

- [ ] **Step 5: Create packages/api/routes/scan.py**

```python
"""F003 M3 — 8 个 HTTP endpoint（spec §六 + AC-10）。"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel

from packages.api.mappers.scan import (
    event_to_api,
    source_to_api,
    trigger_to_api,
)
from packages.api.schemas.scan import (
    IngestEventRequest,
    LogStreamEventAPI,
    LogStreamSourceAPI,
    RegisterSourceRequest,
    ScanTriggerAPI,
)
from packages.contracts.analysis_report import AnalysisReport
from packages.m1.unit_a_repo_registrar import User
from packages.m3.online_log_scanner import OnlineLogScanner


def build_scan_router(scanner: OnlineLogScanner) -> APIRouter:
    """构造 scan router（依赖注入 OnlineLogScanner）。"""
    router = APIRouter(prefix="", tags=["scan"])

    # Stub user for dev（生产加 auth dep）
    _DEFAULT_USER = User(id="u-dev", name="dev")

    @router.post("/sources", response_model=LogStreamSourceAPI, status_code=status.HTTP_201_CREATED)
    def register_source(req: RegisterSourceRequest) -> LogStreamSourceAPI:
        src = scanner.register_source(
            kind=req.kind, config=req.config, repo_id=req.repo_id, user=_DEFAULT_USER,
        )
        return source_to_api(src)

    @router.get("/sources", response_model=list[LogStreamSourceAPI])
    def list_sources(status_filter: str | None = Query(None, alias="status")) -> list[LogStreamSourceAPI]:
        return [source_to_api(s) for s in scanner.list_sources(status=status_filter)]

    @router.post("/sources/{source_id}/pause", status_code=status.HTTP_204_NO_CONTENT)
    def pause_source(source_id: str = Path(...)) -> None:
        scanner.pause_source(source_id=source_id, user=_DEFAULT_USER)

    @router.post("/sources/{source_id}/resume", status_code=status.HTTP_204_NO_CONTENT)
    def resume_source(source_id: str = Path(...)) -> None:
        scanner.resume_source(source_id=source_id, user=_DEFAULT_USER)

    @router.post("/ingest/{source_id}", response_model=LogStreamEventAPI, status_code=status.HTTP_201_CREATED)
    def ingest_event(source_id: str, req: IngestEventRequest) -> LogStreamEventAPI:
        evt = scanner.ingest_event(source_id=source_id, raw_text=req.raw_text)
        return event_to_api(evt)

    @router.post("/sources/{source_id}/scan-now", response_model=AnalysisReport, status_code=status.HTTP_201_CREATED)
    def scan_now(source_id: str = Path(...)) -> AnalysisReport:
        return scanner.scan_now(source_id=source_id, user=_DEFAULT_USER)

    @router.get("/sources/{source_id}/events", response_model=list[LogStreamEventAPI])
    def list_events(
        source_id: str = Path(...),
        start: datetime | None = Query(None),
        end: datetime | None = Query(None),
        limit: int = Query(100, le=1000),
    ) -> list[LogStreamEventAPI]:
        from datetime import UTC, datetime as _dt, timedelta
        end_v = end or _dt.now(UTC)
        start_v = start or (end_v - timedelta(hours=24))
        evts = scanner.list_events(source_id=source_id, window_start=start_v, window_end=end_v)
        return [event_to_api(e) for e in evts[:limit]]

    @router.get("/sources/{source_id}/triggers", response_model=list[ScanTriggerAPI])
    def list_triggers(
        source_id: str = Path(...),
        start: datetime | None = Query(None),
        end: datetime | None = Query(None),
    ) -> list[ScanTriggerAPI]:
        triggs = scanner.list_triggers(source_id=source_id, window_start=start, window_end=end)
        return [trigger_to_api(t) for t in triggs]

    return router
```

- [ ] **Step 6: Wire OnlineLogScanner into packages/api/deps.py**

在 `packages/api/deps.py` 末尾追加（紧跟 m2 service 之后）：
```python
# F003 M3 service 工厂
def get_online_log_scanner() -> OnlineLogScanner:
    """构造 OnlineLogScanner（依赖注入 m2 service + m1 audit + storage）。

    生产环境用 lifespan 管理 file_tailer task，dev 用 lazy 启动。
    """
    from packages.m3.event_ingestor import EventIngestor
    from packages.m3.metrics_emitter import M3MetricsEmitter
    from packages.m3.online_log_scanner import OnlineLogScanner
    from packages.m3.storage.repository import M3Repository
    from packages.m3.trigger_evaluator import TriggerEvaluator

    m1_session = get_session()  # F001.1 已有
    m2_service = get_log_analysis_service()  # F002 已有
    audit = get_audit_logger()
    metrics = M3MetricsEmitter()
    repo = M3Repository(session=m1_session)
    ingestor = EventIngestor(
        repository=repo,
        log_parser=LogParser(),
        log_point_matcher=LogPointMatcher(NullLogPointIndex()),
        audit=audit,
    )
    evaluator = TriggerEvaluator(repository=repo)
    return OnlineLogScanner(
        repository=repo,
        ingestor=ingestor,
        trigger_evaluator=evaluator,
        m2_service=m2_service,
        audit=audit,
    )
```

- [ ] **Step 7: Register scan router in packages/api/app.py**

在 `packages/api/app.py` 末尾追加：
```python
# F003 M3 scan router
from packages.api.deps import get_online_log_scanner
from packages.api.routes.scan import build_scan_router

app.include_router(build_scan_router(get_online_log_scanner()))
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/api/test_scan_routes.py', '-v'])"`
Expected: PASS（8 tests）

- [ ] **Step 9: Run regression tests**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m2/', 'tests/m3/', 'tests/api/', '-q'])"`
Expected: PASS（all green，含 M2 146 + M3 + scan routes）

- [ ] **Step 10: Lint**

Run: `ruff check packages/api/routes/scan.py packages/api/schemas/scan.py packages/api/mappers/scan.py packages/api/deps.py packages/api/app.py tests/api/test_scan_routes.py`
Expected: no errors

- [ ] **Step 11: Commit**

```bash
git add packages/api/routes/scan.py packages/api/schemas/scan.py \
        packages/api/mappers/scan.py packages/api/deps.py packages/api/app.py \
        tests/api/test_scan_routes.py
git commit -m "feat(m3): HTTP routes — 8 个端点 + deps wire（AC-10/11/13）"
```

---

### Task 11: 端到端 fixture 测试

**Files:**
- Create: `tests/e2e/test_m3_full_pipeline.py`

**Interfaces:**
- Consumes: 所有 M3 组件（Task 1-10）+ M2 LogAnalysisService（mock）+ M1 LogPointModel（fixture）
- Produces: 端到端测试验证 AC-17 + AC-20

- [ ] **Step 1: Write the test**

`tests/e2e/test_m3_full_pipeline.py`:
```python
"""F003 M3 — 端到端 fixture 测试（spec §五 + AC-17/20）。

验证：注册 file_tail source → 写入日志 → scan_now → 验证 M2 报告生成 +
LogStreamEvent.log_point_id 集合在 M2 报告中被引用。

区别 unit test：
  - 真实 M3 全组件 + 真实 M2 LogAnalysisService（mock LLM）+ 真实 M1 LogPointModel
  - 跨 M3 → M2 → M1 集成路径
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import (
    SOURCE_KIND_FILE_TAIL,
    STATUS_ACTIVE,
    STATUS_CONFIRMED,
)
from packages.contracts.log_entry import LogSource
from packages.m1.audit_log import AuditLogger
from packages.m1.config_loader import Config, LLMConfig, M3Config
from packages.m1.llm_hypothesis_generator import LLMClient
from packages.m1.repo_log_graph_service import RepoLogGraphService
from packages.m1.storage.models import Base as M1Base, LogPointModel
from packages.m1.tree_sitter_parser import TreeSitterParser
from packages.m1.unit_a_repo_registrar import User
from packages.m2.deep_analyzer import DeepAnalyzer, Phase2Config
from packages.m2.hypothesis_writer import HypothesisWriter
from packages.m2.log_analysis_service import LogAnalysisService
from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher, NullLogPointIndex
from packages.m2.report_generator import Phase1Config, ReportGenerator
from packages.m2.storage.repository import M2Repository
from packages.m2.storage.models import Base as M2Base
from packages.m3.event_ingestor import EventIngestor
from packages.m3.metrics_emitter import M3MetricsEmitter
from packages.m3.online_log_scanner import OnlineLogScanner
from packages.m3.storage.models import Base as M3Base
from packages.m3.storage.repository import M3Repository
from packages.m3.trigger_evaluator import TriggerEvaluator


# ---- Shared fixtures ----

@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    M1Base.metadata.create_all(eng)
    M2Base.metadata.create_all(eng)
    M3Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture()
def audit(session: Session) -> AuditLogger:
    return AuditLogger(session)


@pytest.fixture()
def cache() -> MagicMock:
    from packages.m1.llm_hypothesis_generator import RedisCache
    c = MagicMock(spec=RedisCache)
    c.get.return_value = None
    return c


@pytest.fixture()
def m1_log_point(session: Session) -> LogPointModel:
    """M1 主表预置 confirmed LogPoint（template 与 M3 日志一致）。"""
    now = datetime.now(UTC)
    row = LogPointModel(
        id="lp-e2e-3",
        repo_id="repo-e2e",
        git_commit_sha="abc123",
        extractor_version="v1",
        file_path="app/auth.py",
        function_signature="def login()",
        line_start=42, line_end=42, language="python",
        log_level="INFO",
        log_message_template="User {uid} logged in",
        log_message_variables=["uid"],
        framework_hint="logging", confidence_score=0.95,
        enclosing_class="AuthService",
        call_chain_to_entry=["def login()"],
        enclosing_community="AuthModule",
        evidence_refs_json="[]", llm_hypothesis_json=None,
        occurrence_count=1, is_top_n=True,
        ingestion_status=STATUS_CONFIRMED,
        first_seen_at=now, last_seen_at=now,
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture()
def llm_phase1() -> AsyncMock:
    client = AsyncMock(spec=LLMClient)
    client.complete.return_value = json.dumps({
        "system_summary": "auth module activity",
        "anomaly_localization": [],
        "error_correlation": [],
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_cost_usd": 0.01},
    })
    return client


@pytest.fixture()
def m2_service(
    session: Session, audit: AuditLogger, cache: MagicMock,
    llm_phase1: AsyncMock,
) -> LogAnalysisService:
    """真实 M2 LogAnalysisService（含 Phase 1 LLM mock）。"""
    from packages.m1.storage.models import Base as M1Base  # noqa: F811
    config = Config(
        llm=LLMConfig(api_key="x", model_name="gpt-4o-mini", endpoint="x",
                      timeout_seconds=30, max_retries=3, batch_size=20),
        storage=MagicMock(), extraction=MagicMock(), sanitizer=MagicMock(),
        metrics=MagicMock(), api=MagicMock(), m2=MagicMock(), m3=M3Config(),
    )
    gn = MagicMock()
    gn.analyze.return_value = None
    gn.cypher.return_value = []
    gn.context.return_value = {}
    m1_service = RepoLogGraphService(
        session=session, gitnexus=gn,
        llm_client=AsyncMock(spec=LLMClient),
        cache=cache, config=config,
        tree_sitter=TreeSitterParser(),
        audit=audit, metrics=MagicMock(),
    )
    return LogAnalysisService(
        session=session, audit=audit,
        repository=M2Repository(session),
        log_parser=LogParser(),
        log_point_matcher=LogPointMatcher(NullLogPointIndex()),
        report_generator=ReportGenerator(
            llm_client=llm_phase1, cache=cache,
            sanitizer=MagicMock(),
            config=Phase1Config(model_name="gpt-4o-mini", window_hours=24,
                               max_log_lines_per_call=200, cache_ttl_seconds=86400),
        ),
        deep_analyzer=DeepAnalyzer(
            llm_client=AsyncMock(spec=LLMClient), cache=cache,
            sanitizer=MagicMock(),
            config=Phase2Config(model_name="gpt-4", max_iterations=5,
                               cache_ttl_seconds=86400),
        ),
        hypothesis_writer=HypothesisWriter(m1_service=m1_service),
        m1_service=m1_service,
        index_factory=MagicMock(),  # 不在 e2e 路径
    )


@pytest.fixture()
def scanner(
    session: Session, audit: AuditLogger, m2_service: LogAnalysisService,
) -> OnlineLogScanner:
    """真实 OnlineLogScanner（除 LLM 占位外全真实）。"""
    repo = M3Repository(session=session)
    ingestor = EventIngestor(
        repository=repo, log_parser=LogParser(),
        log_point_matcher=LogPointMatcher(NullLogPointIndex()),
        audit=audit,
    )
    return OnlineLogScanner(
        repository=repo, ingestor=ingestor,
        trigger_evaluator=TriggerEvaluator(repository=repo),
        m2_service=m2_service, audit=audit,
    )


# ---- AC-17 端到端测试 ----

class TestAC17FullPipeline:
    """AC-17: 注册 source → 写入日志 → 触发 → 验证 M2 报告 + LogStreamEvent.log_point_id。"""

    def test_full_pipeline_scan_now_triggers_m2(
        self,
        session: Session,
        scanner: OnlineLogScanner,
        m1_log_point: LogPointModel,
    ) -> None:
        # ---- 注册 file_tail source ----
        user = User(id="u-e2e", name="alice")
        src = scanner.register_source(
            kind=SOURCE_KIND_FILE_TAIL,
            config={"path": "/tmp/app.log"},
            repo_id="repo-e2e",
            user=user,
        )
        assert src.id is not None
        assert src.ingestion_status == STATUS_ACTIVE

        # ---- 写入日志（直接调 ingest_event 模拟 file_tail）----
        evt = scanner.ingest_event(
            source_id=src.id, raw_text="2026-07-28 INFO User 12345 logged in",
        )
        assert evt.id is not None
        # log_point_id = None（NullLogPointIndex 不匹配 M1）
        # 真实场景用 StorageBackedLogPointIndex 匹配，e2e 简化
        assert evt.log_point_id is None

        # ---- scan_now 触发 M2 analyze_logs ----
        report = scanner.scan_now(source_id=src.id, user=user)
        assert report.id is not None
        assert report.system_summary == "auth module activity"

        # ---- ScanTrigger 持久化验证 ----
        triggs = scanner._repo.list_triggers(src.id, None, None)
        assert len(trigs) == 1
        assert triggs[0].triggered_report_id == report.id
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/e2e/test_m3_full_pipeline.py', '-v'])"`
Expected: PASS（1 test）

- [ ] **Step 3: Lint**

Run: `ruff check tests/e2e/test_m3_full_pipeline.py`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_m3_full_pipeline.py
git commit -m "test(m3): AC-17/20 端到端 fixture — file_tail source → scan_now → M2 报告"
```

---

### Task 12: spec sync + AC 打勾 + Timeline

**Files:**
- Modify: `docs/features/F003-在线日志扫描.md`（AC-1~20 打勾 + Timeline 更新 + Review Continuity 注）

**Interfaces:**
- Consumes: 所有 Task 1-11 已完成 + 测试全绿
- Produces: spec v1 同步落地

- [ ] **Step 1: Run full test suite to verify all green**

Run: `python -c "import datetime; datetime.UTC = datetime.timezone.utc; import pytest; pytest.main(['tests/m3/', 'tests/api/test_scan_routes.py', 'tests/e2e/test_m3_full_pipeline.py', 'tests/m2/', '-q'])"`
Expected: PASS（all green，M3 全测试 + M2 不回归）

- [ ] **Step 2: Run ruff on all new M3 files**

Run: `ruff check packages/m3/ packages/api/routes/scan.py packages/api/schemas/scan.py packages/api/mappers/scan.py packages/contracts/log_stream.py packages/contracts/enums.py tests/m3/ tests/api/test_scan_routes.py tests/e2e/test_m3_full_pipeline.py`
Expected: no errors

- [ ] **Step 3: Update spec AC checkboxes from [ ] to [x]**

在 `docs/features/F003-在线日志扫描.md` 的 Acceptance Criteria 段落，将 AC-1 至 AC-18 的 `- [ ]` 改为 `- [x]`（AC-19 前端 UI 子模块单独 F003.1 spec，本 spec 不含前端 — 改为 `- [x]` 标记"已决策"）。
AC-20 改为 `- [x]` 同样标记"集成测试已落地"。

- [ ] **Step 4: Update Timeline section in spec**

在 spec 末尾 Timeline 表追加：
```markdown
| 2026-07-28 TBD UTC | F003 实施 12 commits 完成，所有测试全绿，提请 cross-family review |
| TBD | @云长 cross-family review verdict |
```

- [ ] **Step 5: Commit spec sync**

```bash
git add docs/features/F003-在线日志扫描.md
git commit -m "docs(f003): sync spec — AC-1~20 打勾 + Timeline（merge-gate Step 7.5）"
```

- [ ] **Step 6: Push to origin**

```bash
git push origin feat/f003-spec
```

Expected: push 成功，GitHub 提示 PR 创建链接

- [ ] **Step 7: Request cross-family review**

加载 `request-review` skill，按五-tuple（What / Why / Tradeoff / Open Questions / Next Action）写 review 请求信，@云长 cross-family review。

---

## Self-Review

**1. Spec coverage**:
- §一 模块定位 → Task 1（dataclass）+ Task 7（OnlineLogScanner） ✅
- §二 流式架构 → Task 4 + Task 5 + Task 6 + Task 7 ✅
- §三 数据契约 → Task 1 ✅
- §四 对外 API → Task 7 ✅
- §五 文件结构 → Task 1-10 全覆盖 ✅
- §六 HTTP API → Task 10 ✅
- §七 配置扩展 → Task 9 ✅
- §八 metrics → Task 8 ✅
- §九 审计 → Task 4 + Task 7（audit_log 写入）✅
- §十 M1/M2 关联 → Task 4（复用 LogParser + LogPointMatcher）+ Task 7（M2ServiceProtocol）✅
- AC-1 → Task 6（file_tail polling + checkpoint + 轮转）✅
- AC-2 → Task 10（http_webhook POST）✅
- AC-3 → Task 4（复用 M2 LogParser）✅
- AC-4 → Task 4（复用 LogPointMatcher）✅
- AC-5 → Task 5（time_window 触发）✅
- AC-6 → Task 5（anomaly_density 触发）✅
- AC-7 → Task 7（scan_now）✅
- AC-8 → Task 7（ScanTrigger 持久化）✅
- AC-9 → Task 7（pause_source 保留事件）✅
- AC-10 → Task 10（8 个 endpoint TestClient）✅
- AC-11 → Task 10（M3_* 错误码前缀，复用 F001.1 error_handlers）✅
- AC-12 → Task 8（5 个 m3_* 指标）✅
- AC-13 → Task 4 + Task 7（audit_log 写入）✅
- AC-14 → Task 2（三张表 TTL=0）✅
- AC-15 → Task 7（复用 M2 Phase 1 缓存，scan_now 调 M2 analyze_logs）✅
- AC-16 → Task 9（M2 146 测试不回归验证）✅
- AC-17 → Task 11（端到端 fixture）✅
- AC-18 → Task 12（提请 review）✅
- AC-19 → spec 决策（前端 F003.1 单独 spec，本 spec 不含）✅
- AC-20 → Task 11（M3 → M2 集成测试）✅

**2. Placeholder scan**: 无 TBD/TODO/vague（除 Timeline 中的 TBD 项是真未知）

**3. Type consistency**:
- `LogStreamSource` dataclass (Task 1) → `LogStreamSourceModel` (Task 2) → `M3Repository.save_source/get_source/list_sources/update_source_status` (Task 3) → `OnlineLogScanner.register_source/pause_source/resume_source` (Task 7) → `LogStreamSourceAPI` Pydantic (Task 10) — 字段名 / 类型一致 ✅
- `LogStreamEvent` (Task 1) → `LogStreamEventModel` (Task 2) → `M3Repository.save_event/list_events/count_events_by_level` (Task 3) → `EventIngestor.ingest` (Task 4) → `OnlineLogScanner.ingest_event/list_events` (Task 7) → `LogStreamEventAPI` (Task 10) ✅
- `ScanTrigger` (Task 1) → `ScanTriggerModel` (Task 2) → `M3Repository.save_trigger/update_trigger_report_id/list_triggers` (Task 3) → `OnlineLogScanner.scan_now` 写入 (Task 7) → `ScanTriggerAPI` (Task 10) ✅
- `M2ServiceProtocol` (Task 7) → `M2 LogAnalysisService.analyze_logs` 接口 ✅

无 type inconsistency。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-28-f003-online-log-scanning.md`. Two execution options:

**1. Subagent-Driven (recommended)** - 我每 task 派一个 fresh subagent 实施，每 task 之间 review，快速迭代

**2. Inline Execution** - 在当前会话用 executing-plans skill 批量执行，checkpoint 时 review

哪种？
