"""Privacy-reviewed metric registry and durable-state reconstruction."""

from collections import defaultdict
from dataclasses import dataclass
import math
import re
import sqlite3

from .build import BUILD, BuildInfo
from .enums import JobState, METRIC_LABEL_VALUES


METRIC_NAME = re.compile(r"^hermodr_[a-z0-9_]+$")
SAFE_BUILD_LABEL = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")


@dataclass(frozen=True)
class MetricDefinition:
    kind: str
    labels: tuple[str, ...]


DEFINITIONS = {
    "hermodr_build_info": MetricDefinition("gauge", ("version", "commit", "schema_version")),
    "hermodr_sqlite_build_info": MetricDefinition("gauge", ("version", "source_hash")),
    "hermodr_database_size_bytes": MetricDefinition("gauge", ("file_kind",)),
    "hermodr_filesystem_free_bytes": MetricDefinition("gauge", ()),
    "hermodr_processing_jobs": MetricDefinition("gauge", ("state",)),
    "hermodr_processing_oldest_pending_age_seconds": MetricDefinition("gauge", ()),
    "hermodr_quarantine_events": MetricDefinition("gauge", ("reason",)),
    "hermodr_outbox_sequence": MetricDefinition("gauge", ()),
    "hermodr_reporting_subjects": MetricDefinition("gauge", ("state",)),
    "hermodr_worst_ingest_age_seconds": MetricDefinition("gauge", ()),
    "hermodr_worst_capture_age_seconds": MetricDefinition("gauge", ()),
    "hermodr_backup_status": MetricDefinition("gauge", ("stage",)),
    "hermodr_backup_last_success_timestamp_seconds": MetricDefinition("gauge", ("stage",)),
}


class MetricRegistry:
    def __init__(self):
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)

    def set(self, name: str, value: float, **labels: str) -> None:
        definition = DEFINITIONS.get(name)
        if definition is None or not METRIC_NAME.fullmatch(name):
            raise ValueError("metric_not_allowed")
        if tuple(sorted(labels)) != tuple(sorted(definition.labels)):
            raise ValueError("metric_labels_invalid")
        for label, item in labels.items():
            if not isinstance(item, str):
                raise ValueError("metric_label_value_invalid")
            if name in {"hermodr_build_info", "hermodr_sqlite_build_info"}:
                if not SAFE_BUILD_LABEL.fullmatch(item):
                    raise ValueError("metric_label_value_invalid")
            elif item not in METRIC_LABEL_VALUES[label]:
                raise ValueError("metric_label_value_invalid")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("metric_value_invalid")
        self._values[(name, tuple(sorted(labels.items())))] = numeric

    def build_info(self, build: BuildInfo = BUILD) -> None:
        self.set("hermodr_build_info", 1, **build.labels())

    def sqlite_build_info(self, connection: sqlite3.Connection) -> None:
        source_id = str(connection.execute("SELECT sqlite_source_id()").fetchone()[0])
        self.set(
            "hermodr_sqlite_build_info",
            1,
            version=sqlite3.sqlite_version,
            source_hash=source_id.rsplit(" ", 1)[-1],
        )

    def render(self) -> str:
        lines = []
        for (name, labels), value in sorted(self._values.items()):
            label_text = ""
            if labels:
                label_text = "{" + ",".join(f'{key}="{item}"' for key, item in labels) + "}"
            lines.append(f"{name}{label_text} {value:g}")
        return "\n".join(lines) + ("\n" if lines else "")


def reconstruct_critical_metrics(connection: sqlite3.Connection, now_ms: int) -> MetricRegistry:
    registry = MetricRegistry()
    registry.build_info()
    registry.sqlite_build_info(connection)
    for state in JobState:
        count = connection.execute("SELECT COUNT(*) FROM processing_jobs WHERE state = ?", (state.value,)).fetchone()[0]
        registry.set("hermodr_processing_jobs", count, state=state.value)
    oldest = connection.execute("SELECT MIN(created_at_ms) FROM processing_jobs WHERE state = 'pending'").fetchone()[0]
    registry.set("hermodr_processing_oldest_pending_age_seconds", 0 if oldest is None else max(0, now_ms - oldest) / 1000)
    sequence = connection.execute("SELECT COALESCE(MAX(sequence), 0) FROM outbox_records").fetchone()[0]
    registry.set("hermodr_outbox_sequence", sequence)
    active = connection.execute("SELECT COUNT(*) FROM subjects WHERE status = 'active'").fetchone()[0]
    disabled = connection.execute("SELECT COUNT(*) FROM subjects WHERE status != 'active'").fetchone()[0]
    registry.set("hermodr_reporting_subjects", active, state="unknown")
    registry.set("hermodr_reporting_subjects", disabled, state="disabled")
    newest_receipt, newest_capture = connection.execute(
        """SELECT MIN(last_receipt), MIN(last_capture)
           FROM (
             SELECT s.subject_id, MAX(r.received_at_ms) AS last_receipt,
                    MAX(r.captured_at_ms) AS last_capture
             FROM subjects s
             LEFT JOIN raw_events r
               ON r.subject_id = s.subject_id AND r.synthetic = 0
             WHERE s.status = 'active'
             GROUP BY s.subject_id
           )"""
    ).fetchone()
    registry.set("hermodr_worst_ingest_age_seconds", 0 if newest_receipt is None else max(0, now_ms - newest_receipt) / 1000)
    registry.set("hermodr_worst_capture_age_seconds", 0 if newest_capture is None else max(0, now_ms - newest_capture) / 1000)
    for row in connection.execute("SELECT reason_code, COUNT(*) FROM quarantine WHERE review_state = 'pending' GROUP BY reason_code"):
        registry.set("hermodr_quarantine_events", row[1], reason=row[0])
    for stage in ("create", "verify", "restore_test"):
        status = connection.execute("SELECT state_value FROM operational_state WHERE state_key = ?", (f"backup_{stage}_status",)).fetchone()
        stamp = connection.execute("SELECT state_value FROM operational_state WHERE state_key = ?", (f"backup_{stage}_last_success_ms",)).fetchone()
        registry.set("hermodr_backup_status", 0 if status is None else status[0], stage=stage)
        registry.set("hermodr_backup_last_success_timestamp_seconds", 0 if stamp is None else stamp[0] / 1000, stage=stage)
    return registry
