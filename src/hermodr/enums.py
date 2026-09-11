"""Bounded values used at storage and observability boundaries."""

from enum import StrEnum


class ErrorCode(StrEnum):
    AUTH_INVALID = "auth_invalid"
    CONFIG_INVALID = "config_invalid"
    CONTRACT_INVALID = "contract_invalid"
    DATABASE_BUSY = "database_busy"
    DATABASE_ERROR = "database_error"
    IDENTITY_MISMATCH = "identity_mismatch"
    INTERNAL = "internal"
    UNSUPPORTED_MESSAGE_TYPE = "unsupported_message_type"


class QualityFlag(StrEnum):
    FUTURE_TIMESTAMP = "future_timestamp"
    IMPLAUSIBLE_SPEED = "implausible_speed"
    LATE = "late"
    MISSING_ACCURACY = "missing_accuracy"
    OUT_OF_ORDER = "out_of_order"
    POOR_ACCURACY = "poor_accuracy"
    SOURCE_TRANSITION_UNCONFIRMED = "source_transition_unconfirmed"


class JobState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class AuditAction(StrEnum):
    BACKUP = "backup"
    CONFIG_ACTIVATE = "config_activate"
    CREDENTIAL_CHANGE = "credential_change"
    DELETE = "delete"
    EMERGENCY_SHUTDOWN = "emergency_shutdown"
    EXPORT = "export"
    MIGRATE = "migrate"
    QUARANTINE_DISPOSITION = "quarantine_disposition"
    REPROCESS = "reprocess"
    RESTORE_TEST = "restore_test"
    RETENTION = "retention"


METRIC_LABEL_VALUES = {
    "file_kind": frozenset({"database", "wal", "shared_memory"}),
    "reason": frozenset(item.value for item in ErrorCode),
    "result": frozenset({"accepted", "duplicate", "rejected", "quarantined", "failed", "success", "retry"}),
    "source_type": frozenset({"location", "transition", "waypoint", "status", "unknown"}),
    "stage": frozenset({"create", "verify", "restore_test"}),
    "state": frozenset(item.value for item in JobState) | frozenset({"current", "stale", "disabled", "unknown"}),
}
