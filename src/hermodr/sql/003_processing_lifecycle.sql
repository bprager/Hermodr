ALTER TABLE observations ADD COLUMN processed_at_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE observations ADD COLUMN source_type TEXT NOT NULL DEFAULT 'location';
ALTER TABLE observations ADD COLUMN altitude_m REAL;
ALTER TABLE observations ADD COLUMN velocity_mps REAL;
ALTER TABLE observations ADD COLUMN heading_deg REAL;
ALTER TABLE observations ADD COLUMN battery_percent REAL;
ALTER TABLE observations ADD COLUMN trigger TEXT;
ALTER TABLE observations ADD COLUMN connectivity TEXT;
ALTER TABLE observations ADD COLUMN algorithm_config_version TEXT NOT NULL DEFAULT '0000000000000000';

CREATE TABLE normalized_events (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    normalized_event_id TEXT NOT NULL,
    ingest_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('location', 'transition', 'waypoint', 'status')),
    captured_at_ms INTEGER NOT NULL,
    received_at_ms INTEGER NOT NULL,
    processed_at_ms INTEGER NOT NULL,
    schema_version TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    algorithm_config_version TEXT NOT NULL,
    source_digest TEXT NOT NULL CHECK (length(source_digest) = 64),
    canonical_json TEXT NOT NULL CHECK (json_valid(canonical_json)),
    PRIMARY KEY (subject_id, normalized_event_id),
    UNIQUE (subject_id, ingest_id, algorithm_version),
    FOREIGN KEY (subject_id, device_id) REFERENCES devices(subject_id, device_id),
    FOREIGN KEY (subject_id, ingest_id) REFERENCES raw_events(subject_id, ingest_id)
) STRICT;

CREATE INDEX normalized_events_subject_time
    ON normalized_events(subject_id, captured_at_ms, normalized_event_id);

CREATE TABLE retention_policies (
    subject_id TEXT PRIMARY KEY REFERENCES subjects(subject_id),
    raw_days INTEGER NOT NULL CHECK (raw_days > 0),
    normalized_days INTEGER NOT NULL CHECK (normalized_days > 0),
    derived_days INTEGER CHECK (derived_days IS NULL OR derived_days > 0),
    operational_log_days INTEGER NOT NULL CHECK (operational_log_days > 0),
    approved_at_ms INTEGER NOT NULL,
    policy_version TEXT NOT NULL
) STRICT;

CREATE TABLE deletion_plans (
    plan_id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    expected_counts_json TEXT NOT NULL CHECK (json_valid(expected_counts_json)),
    status TEXT NOT NULL CHECK (status IN ('planned', 'applied', 'expired')),
    created_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    applied_at_ms INTEGER,
    CHECK (end_ms >= start_ms),
    CHECK (expires_at_ms > created_at_ms)
) STRICT;

CREATE TABLE outbox_consumers (
    consumer_id TEXT PRIMARY KEY,
    last_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    updated_at_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE outbox_receipts (
    consumer_id TEXT NOT NULL REFERENCES outbox_consumers(consumer_id),
    sequence INTEGER NOT NULL REFERENCES outbox_records(sequence),
    event_id TEXT NOT NULL,
    received_at_ms INTEGER NOT NULL,
    PRIMARY KEY (consumer_id, sequence),
    UNIQUE (consumer_id, event_id)
) STRICT;

CREATE INDEX processing_jobs_claim
    ON processing_jobs(state, next_attempt_ms, subject_id, created_at_ms, job_id);
