"""Privacy-reviewed metric registry and durable-state reconstruction."""

from collections import defaultdict
from dataclasses import dataclass
import math
import re
from pathlib import Path
import shutil
import sqlite3
from threading import Lock

from .build import BUILD, BuildInfo
from .enums import JobState, METRIC_LABEL_VALUES


METRIC_NAME = re.compile(r"^hermodr_[a-z0-9_]+$")
SAFE_BUILD_LABEL = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
HISTOGRAM_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


@dataclass(frozen=True)
class MetricDefinition:
    kind: str
    labels: tuple[str, ...]


DEFINITIONS = {
    "hermodr_build_info": MetricDefinition("gauge", ("version", "commit", "schema_version")),
    "hermodr_sqlite_build_info": MetricDefinition("gauge", ("version", "source_hash")),
    "hermodr_http_requests_total": MetricDefinition("counter", ("service", "route", "method", "status_class")),
    "hermodr_http_request_duration_seconds": MetricDefinition("histogram", ("service", "route", "method")),
    "hermodr_ingest_events_total": MetricDefinition("counter", ("result", "source_type")),
    "hermodr_validation_failures_total": MetricDefinition("counter", ("reason",)),
    "hermodr_auth_failures_total": MetricDefinition("counter", ("reason",)),
    "hermodr_storage_operations_total": MetricDefinition("counter", ("operation", "result")),
    "hermodr_storage_operation_duration_seconds": MetricDefinition("histogram", ("operation",)),
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
    "hermodr_database_integrity_status": MetricDefinition("gauge", ()),
    "hermodr_processor_heartbeat_age_seconds": MetricDefinition("gauge", ()),
}


class MetricRegistry:
    def __init__(self):
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._histogram_counts: dict[tuple[str, tuple[tuple[str, str], ...]], list[int]] = {}
        self._histogram_sums: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._lock = Lock()

    def _validate(self, name: str, labels: dict[str, str], kind: str | None = None) -> MetricDefinition:
        definition = DEFINITIONS.get(name)
        if definition is None or not METRIC_NAME.fullmatch(name):
            raise ValueError("metric_not_allowed")
        if kind is not None and definition.kind != kind:
            raise ValueError("metric_type_invalid")
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
        return definition

    def set(self, name: str, value: float, **labels: str) -> None:
        self._validate(name, labels)
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("metric_value_invalid")
        with self._lock:
            self._values[(name, tuple(sorted(labels.items())))] = numeric

    def increment(self, name: str, amount: float = 1, **labels: str) -> None:
        self._validate(name, labels, "counter")
        numeric = float(amount)
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError("metric_value_invalid")
        with self._lock:
            self._values[(name, tuple(sorted(labels.items())))] += numeric

    def observe(self, name: str, value: float, **labels: str) -> None:
        self._validate(name, labels, "histogram")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError("metric_value_invalid")
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            counts = self._histogram_counts.setdefault(key, [0] * (len(HISTOGRAM_BUCKETS) + 1))
            for index, boundary in enumerate(HISTOGRAM_BUCKETS):
                if numeric <= boundary:
                    counts[index] += 1
            counts[-1] += 1
            self._histogram_sums[key] += numeric

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
        with self._lock:
            values = tuple(sorted(self._values.items()))
            histograms = tuple(sorted((key, tuple(items)) for key, items in self._histogram_counts.items()))
            histogram_sums = dict(self._histogram_sums)
        for (name, labels), value in values:
            label_text = ""
            if labels:
                label_text = "{" + ",".join(f'{key}="{item}"' for key, item in labels) + "}"
            lines.append(f"{name}{label_text} {value:g}")
        for key, counts in histograms:
            name, labels = key
            label_values = dict(labels)
            for boundary, count in zip(HISTOGRAM_BUCKETS, counts[:-1]):
                bucket_labels = label_values | {"le": f"{boundary:g}"}
                label_text = "{" + ",".join(f'{key}="{item}"' for key, item in sorted(bucket_labels.items())) + "}"
                lines.append(f"{name}_bucket{label_text} {count}")
            infinite = label_values | {"le": "+Inf"}
            label_text = "{" + ",".join(f'{key}="{item}"' for key, item in sorted(infinite.items())) + "}"
            base_labels = "" if not labels else "{" + ",".join(f'{key}="{item}"' for key, item in labels) + "}"
            lines.extend((
                f"{name}_bucket{label_text} {counts[-1]}",
                f"{name}_sum{base_labels} {histogram_sums[key]:g}",
                f"{name}_count{base_labels} {counts[-1]}",
            ))
        return "\n".join(lines) + ("\n" if lines else "")


def reconstruct_critical_metrics(connection: sqlite3.Connection, now_ms: int) -> MetricRegistry:
    registry = MetricRegistry()
    registry.build_info()
    registry.sqlite_build_info(connection)
    integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
    registry.set("hermodr_database_integrity_status", 1 if integrity == "ok" else 0)
    database_name = str(connection.execute("PRAGMA database_list").fetchone()[2])
    if database_name:
        database_path = Path(database_name)
        for suffix, file_kind in (("", "database"), ("-wal", "wal"), ("-shm", "shared_memory")):
            path = Path(database_name + suffix)
            registry.set("hermodr_database_size_bytes", path.stat().st_size if path.exists() else 0, file_kind=file_kind)
        registry.set("hermodr_filesystem_free_bytes", shutil.disk_usage(database_path.parent).free)
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
    heartbeat = connection.execute(
        "SELECT last_success_ms FROM service_heartbeats WHERE service = 'processor'"
    ).fetchone()
    registry.set(
        "hermodr_processor_heartbeat_age_seconds",
        0 if heartbeat is None else max(0, now_ms - heartbeat[0]) / 1000,
    )
    for row in connection.execute("SELECT reason_code, COUNT(*) FROM quarantine WHERE review_state = 'pending' GROUP BY reason_code"):
        registry.set("hermodr_quarantine_events", row[1], reason=row[0])
    for stage in ("create", "verify", "restore_test"):
        status = connection.execute("SELECT state_value FROM operational_state WHERE state_key = ?", (f"backup_{stage}_status",)).fetchone()
        stamp = connection.execute("SELECT state_value FROM operational_state WHERE state_key = ?", (f"backup_{stage}_last_success_ms",)).fetchone()
        registry.set("hermodr_backup_status", 0 if status is None else status[0], stage=stage)
        registry.set("hermodr_backup_last_success_timestamp_seconds", 0 if stamp is None else stamp[0] / 1000, stage=stage)
    return registry
