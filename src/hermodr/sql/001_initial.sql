CREATE TABLE subjects (
    subject_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'revoked')),
    policy_ref TEXT NOT NULL,
    authorization_ref TEXT,
    enrolled_at_ms INTEGER NOT NULL CHECK (enrolled_at_ms >= 0),
    revoked_at_ms INTEGER,
    CHECK (revoked_at_ms IS NULL OR revoked_at_ms >= enrolled_at_ms)
) STRICT;

CREATE TABLE devices (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    device_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'revoked')),
    enrolled_at_ms INTEGER NOT NULL CHECK (enrolled_at_ms >= 0),
    revoked_at_ms INTEGER,
    PRIMARY KEY (subject_id, device_id),
    CHECK (revoked_at_ms IS NULL OR revoked_at_ms >= enrolled_at_ms)
) STRICT;

CREATE TABLE credentials (
    subject_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    key_id TEXT NOT NULL,
    secret_ref TEXT NOT NULL,
    valid_from_ms INTEGER NOT NULL,
    valid_until_ms INTEGER,
    PRIMARY KEY (subject_id, key_id),
    FOREIGN KEY (subject_id, device_id) REFERENCES devices(subject_id, device_id),
    CHECK (valid_until_ms IS NULL OR valid_until_ms > valid_from_ms)
) STRICT;

CREATE TABLE raw_events (
    subject_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    ingest_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    source_digest TEXT NOT NULL CHECK (length(source_digest) = 64),
    payload BLOB NOT NULL,
    received_at_ms INTEGER NOT NULL CHECK (received_at_ms >= 0),
    captured_at_ms INTEGER,
    source_type TEXT NOT NULL CHECK (source_type IN ('location', 'transition', 'waypoint', 'status')),
    disposition TEXT NOT NULL CHECK (disposition IN ('accepted', 'quarantined')),
    synthetic INTEGER NOT NULL DEFAULT 0 CHECK (synthetic IN (0, 1)),
    PRIMARY KEY (subject_id, ingest_id),
    FOREIGN KEY (subject_id, device_id) REFERENCES devices(subject_id, device_id)
) STRICT;

CREATE INDEX raw_events_subject_received ON raw_events(subject_id, received_at_ms);

CREATE TABLE processing_jobs (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    job_id TEXT NOT NULL,
    ingest_id TEXT,
    state TEXT NOT NULL CHECK (state IN ('pending', 'processing', 'processed', 'quarantined', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_ms INTEGER NOT NULL,
    lease_owner TEXT,
    lease_expires_ms INTEGER,
    error_code TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (subject_id, job_id),
    FOREIGN KEY (subject_id, ingest_id) REFERENCES raw_events(subject_id, ingest_id),
    CHECK ((state = 'processing') = (lease_owner IS NOT NULL AND lease_expires_ms IS NOT NULL))
) STRICT;

CREATE TABLE observations (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    observation_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    ingest_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    captured_at_ms INTEGER NOT NULL,
    received_at_ms INTEGER NOT NULL,
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90.0 AND 90.0),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180.0 AND 180.0),
    horizontal_accuracy_m REAL CHECK (horizontal_accuracy_m >= 0),
    quality_flags_json TEXT NOT NULL CHECK (json_valid(quality_flags_json)),
    source_digest TEXT NOT NULL CHECK (length(source_digest) = 64),
    PRIMARY KEY (subject_id, observation_id),
    UNIQUE (subject_id, ingest_id, algorithm_version),
    FOREIGN KEY (subject_id, device_id) REFERENCES devices(subject_id, device_id),
    FOREIGN KEY (subject_id, ingest_id) REFERENCES raw_events(subject_id, ingest_id)
) STRICT;

CREATE TABLE places (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    place_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90.0 AND 90.0),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180.0 AND 180.0),
    radius_m REAL NOT NULL CHECK (radius_m > 0),
    sensitivity TEXT NOT NULL CHECK (sensitivity IN ('restricted', 'private')),
    approval_state TEXT NOT NULL CHECK (approval_state IN ('proposed', 'approved', 'rejected')),
    effective_from_ms INTEGER NOT NULL,
    effective_until_ms INTEGER,
    PRIMARY KEY (subject_id, place_id, version),
    CHECK (effective_until_ms IS NULL OR effective_until_ms > effective_from_ms)
) STRICT;

CREATE TABLE transitions (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    transition_id TEXT NOT NULL,
    transition_type TEXT NOT NULL CHECK (transition_type IN ('arrival', 'departure')),
    occurred_at_ms INTEGER NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    status TEXT NOT NULL CHECK (status IN ('provisional', 'confirmed', 'superseded')),
    superseded_by TEXT,
    PRIMARY KEY (subject_id, transition_id),
    FOREIGN KEY (subject_id, superseded_by) REFERENCES transitions(subject_id, transition_id)
) STRICT;

CREATE TABLE visits (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    visit_id TEXT NOT NULL,
    place_id TEXT,
    started_at_ms INTEGER NOT NULL,
    ended_at_ms INTEGER,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    status TEXT NOT NULL CHECK (status IN ('provisional', 'confirmed', 'superseded')),
    superseded_by TEXT,
    PRIMARY KEY (subject_id, visit_id),
    FOREIGN KEY (subject_id, superseded_by) REFERENCES visits(subject_id, visit_id),
    CHECK (ended_at_ms IS NULL OR ended_at_ms >= started_at_ms)
) STRICT;

CREATE TABLE trips (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    trip_id TEXT NOT NULL,
    started_at_ms INTEGER NOT NULL,
    ended_at_ms INTEGER NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    status TEXT NOT NULL CHECK (status IN ('provisional', 'confirmed', 'superseded')),
    superseded_by TEXT,
    PRIMARY KEY (subject_id, trip_id),
    FOREIGN KEY (subject_id, superseded_by) REFERENCES trips(subject_id, trip_id),
    CHECK (ended_at_ms >= started_at_ms)
) STRICT;

CREATE TABLE coverage_gaps (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    gap_id TEXT NOT NULL,
    started_at_ms INTEGER NOT NULL,
    ended_at_ms INTEGER NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('silence', 'accuracy', 'ambiguity')),
    status TEXT NOT NULL CHECK (status IN ('provisional', 'confirmed', 'superseded')),
    superseded_by TEXT,
    PRIMARY KEY (subject_id, gap_id),
    FOREIGN KEY (subject_id, superseded_by) REFERENCES coverage_gaps(subject_id, gap_id),
    CHECK (ended_at_ms >= started_at_ms)
) STRICT;

CREATE TABLE record_evidence (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    record_type TEXT NOT NULL CHECK (record_type IN ('transition', 'visit', 'trip', 'coverage_gap')),
    record_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    PRIMARY KEY (subject_id, record_type, record_id, observation_id),
    FOREIGN KEY (subject_id, observation_id) REFERENCES observations(subject_id, observation_id)
) STRICT;

CREATE TABLE recompute_windows (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    window_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    cause TEXT NOT NULL CHECK (cause IN ('late_data', 'operator', 'algorithm_change')),
    algorithm_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'processing', 'processed', 'failed')),
    coalescing_key TEXT NOT NULL,
    PRIMARY KEY (subject_id, window_id),
    UNIQUE (subject_id, coalescing_key),
    CHECK (end_ms >= start_ms)
) STRICT;

CREATE TABLE outbox_records (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    event_id TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL CHECK (aggregate_version > 0),
    schema_version TEXT NOT NULL,
    event_type TEXT NOT NULL,
    privacy_class TEXT NOT NULL CHECK (privacy_class = 'restricted'),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    created_at_ms INTEGER NOT NULL,
    UNIQUE (subject_id, event_id)
) STRICT;

CREATE TABLE quarantine (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    quarantine_id TEXT NOT NULL,
    ingest_id TEXT NOT NULL,
    reason_code TEXT NOT NULL CHECK (reason_code IN ('auth_invalid', 'config_invalid', 'contract_invalid', 'database_busy', 'database_error', 'identity_mismatch', 'internal', 'unsupported_message_type')),
    details_code TEXT,
    review_state TEXT NOT NULL CHECK (review_state IN ('pending', 'released', 'discarded')),
    created_at_ms INTEGER NOT NULL,
    reviewed_at_ms INTEGER,
    PRIMARY KEY (subject_id, quarantine_id),
    FOREIGN KEY (subject_id, ingest_id) REFERENCES raw_events(subject_id, ingest_id)
) STRICT;

CREATE TABLE audit_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT NOT NULL UNIQUE,
    subject_id TEXT REFERENCES subjects(subject_id),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    run_id TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('success', 'failure')),
    occurred_at_ms INTEGER NOT NULL,
    config_fingerprint TEXT NOT NULL,
    build_version TEXT NOT NULL,
    previous_hash TEXT,
    entry_hash TEXT NOT NULL UNIQUE
) STRICT;

CREATE INDEX audit_events_subject_time ON audit_events(subject_id, occurred_at_ms);

CREATE TABLE service_heartbeats (
    service TEXT PRIMARY KEY CHECK (service IN ('receiver', 'processor', 'maintenance')),
    last_success_ms INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('healthy', 'degraded', 'failed'))
) STRICT;

CREATE TABLE retention_holds (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    hold_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    reason_code TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    released_at_ms INTEGER,
    PRIMARY KEY (subject_id, hold_id),
    CHECK (end_ms >= start_ms)
) STRICT;

CREATE TABLE operational_state (
    state_key TEXT PRIMARY KEY,
    state_value INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
) STRICT;
