# Hermóðr Implementation Design

**Status:** Implemented through M2; deployment and later milestone sections remain proposed
**Source:** `docs/HERMODR_PRD.md`, version 1.1
**Scope:** Version 1 through guarded outbox publication plus the immediately following two-subject version 2; the Napoleon importer is an external consumer

## 1. Design Summary

Hermóðr should be implemented as one release artifact with four commands:

- `hermodr receiver`: private HTTP receiver; validates and durably appends source envelopes.
- `hermodr processor`: asynchronous deterministic normalizer and derivation worker.
- `hermodr admin`: bounded operator actions such as quarantine inspection, reprocessing, deletion, and backup verification.
- `hermodr migrate`: explicit database migration command run before service readiness.

ADR 0001 selects Python 3.13 or newer for the implementation. It is already available on the application host, meets the expected I/O-bound workload, and provides HTTP, SQLite, hashing, structured-data, and testing foundations without mandatory third-party packages. The domain and storage boundaries remain language-independent.

SQLite in WAL mode is the system of record. Receiver persistence, processor work claiming, normalized records, derivations, audit events, and the canonical outbox live in the same database for the MVP. This permits local atomic transactions and avoids introducing a broker. “Queue-driven” means a durable database work queue with short polling plus wake-up hints; correctness never depends on an in-memory notification.

Version 1 runs with one subject, but its identifiers, credentials, database keys, processing partitions, policy references, and administrative operations are multi-subject-ready. Version 2 immediately enrolls the second subject without destructive migration or shared credentials. Cross-subject joins are forbidden except for explicitly authorized aggregate operations that contain no location evidence.

```text
OwnTracks -> fenrir/TLS -> receiver -> SQLite raw_events + processing_jobs
                                         |
                                         v
                                     processor
                                         |
              observations + derivations + outbox_records
                                         |
                                         v
                          Napoleon importer (out of scope)
```

## 2. Architectural Principles

1. **Acknowledge only durable evidence.** A success response follows a committed raw-event transaction.
2. **Event time is not receipt time.** Both are retained and all timeline derivation uses device event time while operational freshness uses receipt time.
3. **At-least-once work, exactly-once effects.** Jobs may retry; unique keys and transactions make persisted results idempotent.
4. **Raw evidence is immutable.** Corrections are new derived versions or supersessions, never raw mutation.
5. **Uncertainty is data.** Poor accuracy, lateness, gaps, and ambiguity are represented rather than guessed away.
6. **Privacy is part of every interface.** Coordinates and payloads are forbidden from routine logs, metric labels, health responses, and error bodies.
7. **Observability must not become a location side channel.** Cardinality and time-series semantics are reviewed for indirect disclosure.
8. **Safe local operation beats distributed complexity.** One database and explicit processes are sufficient for expected load.
9. **Subject isolation starts in version 1.** A credential maps to a device and subject; client payloads never grant subject authority.
10. **Reboot recovery is a normal path.** Every required service, durable store, monitor, and alert evaluator automatically resumes and reconstructs critical state.

## 2.1 PRD Analysis and Clarifications

The PRD is internally consistent on its main boundary: Hermóðr collects and derives; Napoleon authorizes and projects. The following details are intentionally resolved or left as explicit gates in this design:

| PRD issue or ambiguity | Design treatment |
| --- | --- |
| Unsupported OwnTracks types may be “rejected or quarantined.” | Known unsupported types return `422`; a future type may be quarantined only when a bounded forward-compatibility policy explicitly enables it. |
| The accepted HTTP body shape was unspecified. | ADR 0005 accepts one object, rejects arrays atomically, and ignores zero-length publishes. |
| “Relevant transport metadata” could accidentally retain personal or secret data. | Use a strict allowlist and omit IP addresses and raw user-agent values by default. |
| The idempotency source fields and canonicalization rules are unspecified. | Freeze canonical JSON and a keyed idempotency formula before implementation; do not equate near-duplicate coordinates with retransmission. |
| Location, transition, waypoint, and status messages do not all fit the observation schema. | Use type-specific adapters. Only location-bearing input creates an observation; other types create their explicit canonical or diagnostic representation. Status may lack device time: preserve null raw capture time and label receipt time as the normalized ordering fallback. |
| `failed` and “dead-letter state” could imply two states. | `failed` is the terminal/dead-letter job state; quarantine remains a distinct evidence-review state. |
| Arrival, visit, trip, gap, and confidence algorithms lack exact semantics. | Treat the algorithm specification and fixtures as a versioned deliverable before implementing each derivation. |
| Late data can invalidate already published records. | Recompute bounded windows and append supersession records; never rewrite outbox history. |
| An append-only outbox appears to conflict with bounded deletion. | Delete restricted payloads and append tombstones; require the importer to process and acknowledge downstream deletion. |
| Hermóðr cannot calculate outbox consumer backlog without consumer state. | Expose the outbox head locally; calculate true lag only after the importer checkpoint is made observable. |
| Raw retention can conflict with permanent derived-record provenance. | Retain digest and non-reversible evidence references after raw payload expiry; use explicit holds only for unresolved derivations. |
| Receiver availability cannot be inferred from liveness alone. | Measure with an authenticated synthetic durable-ingest probe that contains no real location. |
| “Last successful iPhone report” is coordinate-free but still behaviorally sensitive. | Export only a singleton freshness signal on a restricted operations endpoint; never label by person or device. |
| Rollback after a forward migration could discard events when restoring backup. | Require application rollback to remain schema-compatible; data restore is a separate reconciled recovery procedure. |
| The PRD leaves OwnTracks Recorder versus a thin receiver open. | Recommend the thin receiver because it directly enforces the specified durability, privacy, idempotency, and observability contracts. |
| Version 1 has one subject but version 2 immediately has two. | Build multi-subject keys and isolation in version 1, then make enrollment and multi-subject acceptance the version 2 increment. |
| Process counters reset on reboot while critical monitoring must continue. | Reconstruct critical gauges from durable state and persist the monitoring time-series database; treat counters as process-lifetime signals. |

## 3. Components and Boundaries

### 3.1 Fenrir HTTPS gateway

Fenrir owns public TLS, public-route restriction, request-size enforcement, coarse rate limiting, and upstream timeouts. It forwards only `POST /v1/owntracks`. It must not log request bodies, authorization headers, query strings, or upstream responses. Its access log should contain method, normalized route, status, response bytes, duration, and a gateway-generated request ID.

The receiver trusts forwarding headers only from the configured fenrir address. Client IP retention is disabled by default; if needed operationally, store a keyed truncated hash for a short period rather than an address. Fenrir and its monitoring components must be boot-enabled on their host just as Hermóðr components are on Odin.

### 3.2 Receiver

The receiver is responsible only for:

- startup configuration validation and fail-closed authentication;
- request authentication with constant-time secret comparison;
- bounded body reading and strict JSON parsing;
- envelope-level validation and classification;
- server identifiers, timestamps, digest and idempotency computation;
- atomic append of accepted or quarantined evidence and initial processing work;
- deterministic, coordinate-free responses;
- private health, metrics, and structured logs.

It does not resolve places or derive visits synchronously.

### 3.3 Processor

The processor claims durable jobs using short SQLite transactions. It normalizes events, recomputes bounded event-time windows, writes versioned derived records, and appends outbox records in a single transaction. A lease with an expiry makes abandoned work reclaimable. Concurrent processor instances remain safe, although the default deployment uses one.

### 3.4 Administrator interface

The MVP should use a local CLI instead of an HTTP administration API. This reduces attack surface and allows systemd/Unix permissions to protect sensitive actions. Every mutation requires an operator-supplied reason, creates an audit event, and prints identifiers/counts rather than coordinates. Destructive operations support `--dry-run`; deletion additionally requires a generated plan ID followed by an explicit apply step.

### 3.5 Outbox boundary

The outbox is append-only from Hermóðr's perspective. The external Napoleon importer reads committed rows through a read-only, narrowly authorized mechanism selected during integration. Hermóðr never marks knowledge as imported and never connects to Memgraph. The importer owns a checkpoint and its own idempotency.

## 4. External HTTP Contract

### 4.1 Ingestion

`POST /v1/owntracks`

- Required for non-empty bodies: `Content-Type: application/json` or `application/*+json` (an optional UTF-8 charset is allowed).
- Authentication: HTTP Basic over TLS, with opaque credentials scoped server-side to one device and subject.
- Body: one OwnTracks object. Arrays/batches are rejected atomically with `422`; zero-length publishes return `200 []` without persistence.
- New durable event or exact duplicate: `200 OK` with `[]`. Correlation uses a response header containing the opaque ingest ID rather than a custom response body.
- Zero-length body: `200 OK` with `[]`, without creating a raw event.
- Auth failure: `401` with a generic body and `WWW-Authenticate` appropriate to the configured mode.
- Invalid content type or encoding: `415`.
- Too large: `413`.
- Invalid structure or value: `400` with a bounded machine code, never echoed values.
- Unsupported type: `422` with `unsupported_message_type`, or quarantine if configured for a forward-compatible type.
- Storage unavailable or commit failure: `503`; the request is not acknowledged.
- Rate limit at fenrir: `429` with bounded retry guidance.

OwnTracks documents any `2xx` as successfully posted and `200 []` as the typical response. Exact non-`2xx` retry timing must be verified during real-device commissioning.

Relevant transport metadata is limited to request ID, normalized route, content type, content length, selected safe user-agent family, authentication key ID (not secret), and receiver build version.

### 4.2 Health

- `GET /health/live`: process event loop is responsive. It never touches downstream services. Returns `200` unless the process is irrecoverably unhealthy.
- `GET /health/ready`: configuration is valid, migration version is supported, the database can complete a bounded write/read probe, and free disk is above the hard floor. Receiver readiness does not depend on processor backlog or Napoleon.
- Processor exposes the same paths on a separate private binding if deployed with an HTTP probe; otherwise systemd process state plus a database heartbeat is used.

Health bodies expose only status, build, and failing component codes. They never expose paths, SQL errors, configuration values, queue identifiers, or coordinates.

### 4.3 Metrics

`GET /metrics` is served only on a private operations binding. It is not routed by fenrir. Scrape authentication or network policy is required when it is reachable beyond localhost.

## 5. Authentication and Configuration

Configuration is loaded in this precedence order: flags for file location only, a protected config file, then explicitly supported environment overrides. Secrets are indirect references (for example, credential files mounted with mode `0600`) rather than values in command lines or general environment dumps.

Credential records have `key_id`, `subject_id`, `device_id`, secret hash or protected secret reference, `valid_from`, and `valid_until`. Two credentials for the same device may overlap. Authentication establishes the subject/device identity; any payload identity must agree but can never override it. Logs and audit entries identify only `key_id`. Startup fails if there is no currently valid ingestion credential, subject/device registry, writable database, or required privacy configuration.

Configuration is divided into:

- **Runtime configuration:** bindings, limits, polling, log level; changes do not affect derived meaning.
- **Derivation configuration:** place registry and accuracy/dwell/trip/gap thresholds; canonicalized and hashed into `algorithm_config_version`.
- **Policy configuration:** retention and export/deletion behavior; changes are audited.

Every loaded configuration has a non-secret fingerprint surfaced in process-start logs and the build-info metric.

## 6. Persistence Model

Use UTC RFC 3339 timestamps at interfaces and signed integer Unix milliseconds internally. Store latitude/longitude as constrained numeric values; canonical serialization must define decimal precision and field ordering before hashing. Identifiers should be sortable random IDs for ingests and deterministic hash-derived IDs for canonical results.

Every subject-owned table includes a non-null `subject_id` foreign key. Uniqueness and lookup indexes include `subject_id` where identity could otherwise collide, and repository operations require subject scope explicitly. SQLite provides no row-level security, so this invariant is enforced through narrow repository APIs, foreign keys, authorization checks, and cross-subject negative tests.

### 6.1 Core tables

| Table | Purpose and key constraints |
| --- | --- |
| `schema_migrations` | Applied migration ID, checksum, application time. |
| `subjects` | Pseudonymous subject ID, lifecycle status, policy reference, enrollment/revocation timestamps, and minimal authorization record. No routine display name is required. |
| `devices` | Device ID, subject ID, lifecycle status, credential scope, and enrollment/revocation timestamps. |
| `credentials` | Subject/device-scoped key ID, indirect secret reference, and bounded validity interval. No secret value is stored in the schema. |
| `raw_events` | Immutable envelope keyed by `ingest_id`; unique `idempotency_key`; digest, encrypted-or-restricted payload bytes, safe metadata, receipt time, source type, disposition. Update/delete denied in normal application path except retention/deletion workflow. |
| `processing_jobs` | Subject-partitioned job; one active job per ingest/recompute window, with state, attempts, next attempt, lease owner/expiry, bounded error code, timestamps. |
| `observations` | Deterministic `observation_id`, canonical fields, quality flags, raw provenance, schema and algorithm versions. Unique provenance/version constraint. |
| `places` | Versioned configured or proposed geographic areas, sensitivity, approval state, effective interval. Coordinates remain restricted. |
| `transitions` | Source or derived transition with evidence, confidence, state and supersession link. |
| `visits` | Event-time interval, place/cluster reference, confidence, supporting-evidence relation, status and supersession link. |
| `trips` | Event-time movement interval, endpoint references, confidence, status and supersession link. |
| `coverage_gaps` | Evidence boundary interval, reason code, status and supersession link. |
| `record_evidence` | Many-to-many relationship from a derived record/version to observation IDs. |
| `recompute_windows` | Subject, bounded start/end, cause, algorithm version, state and coalescing key. |
| `outbox_records` | Monotonic sequence, stable event ID, aggregate/version, schema, type, privacy class, canonical payload, created time; unique event ID. No in-place update. |
| `quarantine` | Raw ingest reference, bounded reason code/details, review state and timestamps. No duplicated raw payload. |
| `audit_events` | Append-only actor, action, target type/opaque ID, reason, request/run ID, result, time and config/build fingerprint. |
| `service_heartbeats` | Processor/storage maintenance timestamps used for operations checks. |
| `retention_holds` | Subject-scoped records/time ranges temporarily excluded from expiration with reason. |
| `operational_state` | Durable non-sensitive backup, restore, and integrity status used to reconstruct critical gauges after restart. |

### 6.2 SQLite settings and ownership

- Enable WAL, foreign keys, and a configured busy timeout on every connection.
- Use synchronous mode `FULL` initially; benchmark before considering `NORMAL`.
- Limit writer concurrency and keep write transactions small.
- Run periodic `PRAGMA quick_check`; run full integrity checks during scheduled maintenance or backup verification.
- Keep database, WAL, and shared-memory files on the same persistent filesystem.
- Restrict the data directory to the Hermóðr service account and a separately authorized backup identity.
- Set a maximum WAL size policy and checkpoint it without blocking ingestion for long periods.

### 6.3 Idempotency

Two hashes serve different purposes:

- `source_digest = SHA-256(canonical accepted source object)` provides evidence integrity.
- `idempotency_key = HMAC-SHA-256(instance dedupe key, source identity fields + canonical source object)` prevents an observer with a guessed event from testing raw digests and tolerates transport metadata differences.

If OwnTracks supplies a reliable message identity, it is included. Otherwise canonical payload, registered subject/device mapping, and device timestamp form the key. Exact duplicates point to the first `ingest_id`. Semantically similar but non-identical observations are retained and handled by derivation, not discarded at ingestion.

Key rotation for HMAC must retain prior key IDs for the raw-retention horizon or use a stable dedicated dedupe key protected separately from request credentials.

### 6.4 Job state machine

```text
pending -> processing -> processed
   ^          |             |
   |          +-> pending   +-> pending (explicit reprocess creates new run)
   |              (retry)
   +-------------- lease expiry

pending/processing -> quarantined
pending/processing -> failed (retry budget exhausted; dead-letter condition)
```

Claiming changes `pending` to `processing`, records a lease and increments attempts in one transaction. Work scheduling and event-time ordering are partitioned by subject. Completion inserts all canonical effects and outbox rows and marks the job processed in the same transaction. Error details use a bounded code plus a scrubbed message; raw values never enter job diagnostics. At startup, expired leases are reclaimed and durable pending work resumes automatically.

## 7. Canonical Contracts

Canonical payloads should use versioned JSON Schema stored in the repository. All records contain:

- stable record ID and schema version;
- subject and source identifiers;
- event-time and processing-time fields;
- evidence references and source digest;
- algorithm name/version/config fingerprint;
- quality flags and confidence where meaningful;
- lifecycle status (`provisional`, `confirmed`, or `superseded`) and optional supersession link;
- privacy classification.

Outbox events use a common envelope with `event_id`, `sequence`, `event_type`, `schema_version`, `occurred_at`, `published_at`, `subject_id`, `privacy_class`, `provenance`, and `data`. Contract fixtures are tested against JSON Schema. A new incompatible shape requires a new schema version; changing derivation behavior requires an algorithm version even when schema is unchanged.

M1 freezes version 1 schemas under `contracts/v1` and packages them in the release wheel. The dependency-free validator returns only a JSON path and bounded violation code; it does not echo rejected values.

## 8. Processing and Derivation

### 8.1 Normalization

Adapters are explicit per OwnTracks message type: location, transition, waypoint, and status. Only location-bearing messages create observations. Transition messages create source transitions and may reference the nearest valid observation; waypoint messages update a proposed/config-import workflow rather than silently approving a place; status messages update device diagnostics without becoming location observations.

Quality flags are a bounded enum, including `late`, `future_timestamp`, `poor_accuracy`, `missing_accuracy`, `implausible_speed`, `out_of_order`, and `source_transition_unconfirmed`. Threshold crossings never drop accepted evidence.

### 8.2 Accuracy-aware place resolution

Treat reported horizontal accuracy as an uncertainty radius. An observation supports a known place when its uncertainty circle sufficiently overlaps the place radius under a configured rule. An observation whose uncertainty overlaps multiple places is ambiguous. Low-quality points cannot independently confirm arrival or departure.

The first implementation should use local great-circle distance and explicit tests at poles, the antimeridian, radius boundaries, and overlapping places. External geocoding remains absent.

### 8.3 Event-time windows

Each accepted location event schedules a recompute window around its captured time. Windows are expanded by the maximum dwell/trip/gap horizon and coalesced only within the same subject. A late or out-of-order point recomputes only that subject's affected bounded interval plus adjacent derived records. Existing active derivations in that interval are compared with newly computed results:

- identical deterministic record: no new outbox event;
- changed record: old version becomes superseded and a replacement plus supersession event is appended;
- newly unsupported record: it becomes superseded with a reason; it is not deleted.

### 8.4 Derivation pipeline

1. Order usable observations by `(captured_at, received_at, observation_id)`.
2. Segment evidence at explicit coverage gaps, configured maximum silence, or irreconcilable ambiguity.
3. Resolve place candidates using distance and accuracy.
4. Form provisional presence intervals; require configured dwell/evidence rules for confirmation.
5. Reconcile source transitions as evidence, not unquestioned truth.
6. Emit arrivals/departures and visits with supporting observation IDs.
7. Form trips between compatible visit endpoints when movement evidence is sufficient.
8. Emit explicit coverage gaps where continuity cannot be supported.

All numeric thresholds, tie breakers, rounding rules, and confidence calculations must be documented and fixture-tested before the corresponding feature is accepted. Confidence is a bounded deterministic score with an explanation code, not a statistical probability unless it is calibrated as one.

## 9. Privacy and Security Design

- Separate public ingestion and private operations listeners. No admin or metrics route exists on the public listener.
- Use non-root receiver and processor services, a read/write service data identity, and a read-only importer identity.
- Apply systemd hardening or equivalent container controls: no new privileges, read-only root filesystem, private temporary storage, explicit writable data path, restricted address families, and a minimal capability set.
- Never accept subject/device identity directly as authority. Map allowlisted source identifiers to configured pseudonymous IDs.
- Enforce subject predicates in repository methods rather than relying on callers; test that credentials, evidence, jobs, derivations, outbox, export, retention, and deletion cannot cross subject boundaries.
- Centralize log redaction and test it with raw coordinate, address, authorization, query-string, and malformed-payload canaries.
- Error responses return stable codes and request IDs only.
- Encrypt backup artifacts before they leave Odin. SQLite page-level encryption is a separate decision; filesystem permissions and encrypted host storage are assumed but must be verified.
- Audit credential/config changes at the operational workflow boundary; since Hermóðr cannot observe an out-of-band file edit, deployment tooling must call `hermodr admin audit-change` or write an equivalent signed audit record.
- Bounded deletion plans enumerate affected raw, canonical, evidence, quarantine, outbox, and derived records. Because outbox is append-only, deletion publishes tombstones and removes restricted payload rows according to policy; downstream deletion acknowledgement belongs to the importer contract.

## 10. Observability Design

### 10.1 Service objectives and indicators

| Objective | Indicator | Initial target/window |
| --- | --- | --- |
| Receiver availability | Successful non-auth synthetic requests / scheduled probes, excluding planned maintenance | 99.5% monthly |
| Durable acceptance latency | Time from request start through raw commit for accepted requests | p95 < 500 ms over 30 days |
| Durability | Acknowledged ingest IDs present and integrity-valid after restart/restore tests | 100% in tests; zero known production loss |
| Processing freshness | `now - oldest pending received_at` | < 5 min normally; configurable |
| Outbox freshness | `now - oldest unconsumed sequence time`, measured by importer checkpoint | < 15 min after importer is introduced |
| Source reporting freshness | Both `now - last real ingest received_at` and `now - greatest captured_at` | warning thresholds are user-approved and mode-aware |
| Backup recoverability | Latest backup successfully restored and integrity-checked in isolation | at least monthly and before production activation |

Availability is measured with a synthetic, non-sensitive request authenticated by a dedicated probe credential and mapped to a registered synthetic subject/device. Its committed raw record is explicitly marked synthetic, excluded from domain derivation/outbox publication, and given short retention. Plain liveness probes do not prove durable ingestion, while deliberately quarantining probes would pollute quarantine monitoring.

### 10.2 Metrics contract

All metric names use the `hermodr_` prefix. Labels are bounded enums only. Never label by subject, device, ingest ID, request ID, coordinate, place, exception text, filesystem path, or HTTP user agent.

| Metric | Type | Allowed labels | Purpose |
| --- | --- | --- | --- |
| `hermodr_build_info` | gauge | `version`, `commit`, `schema_version` | Release identity; value is 1. |
| `hermodr_sqlite_build_info` | gauge | `version`, `source_hash` | Loaded native-library identity; value is 1 and an unexpected identity fails production startup. |
| `hermodr_http_requests_total` | counter | `service`, `route`, `method`, `status_class` | Receiver traffic and failure rate. |
| `hermodr_http_request_duration_seconds` | histogram | `service`, `route`, `method` | End-to-end request latency. |
| `hermodr_ingest_events_total` | counter | `result`, `source_type` | `accepted`, `duplicate`, `rejected`, `quarantined`, `failed`. |
| `hermodr_validation_failures_total` | counter | `reason` | Bounded validation reason codes. |
| `hermodr_auth_failures_total` | counter | `reason` | Missing/invalid/expired credential without key identity. |
| `hermodr_storage_operations_total` | counter | `operation`, `result` | Commit, checkpoint, integrity check and maintenance outcomes. |
| `hermodr_storage_operation_duration_seconds` | histogram | `operation` | Storage latency and contention. |
| `hermodr_database_size_bytes` | gauge | `file_kind` | Database/WAL size; no path label. |
| `hermodr_filesystem_free_bytes` | gauge | none | Capacity at the data volume. |
| `hermodr_processing_jobs` | gauge | `state` | Current durable queue state. |
| `hermodr_processing_oldest_pending_age_seconds` | gauge | none | Backlog age, more actionable than depth alone. |
| `hermodr_processing_attempts_total` | counter | `result`, `stage`, `reason` | Processor success/retry/failure by bounded code. |
| `hermodr_processing_duration_seconds` | histogram | `stage`, `result` | Normalization and derivation latency. |
| `hermodr_recompute_windows_total` | counter | `cause`, `result` | Late-data and operator reprocessing behavior. |
| `hermodr_quarantine_events` | gauge | `reason` | Reviewable inventory by bounded reason. |
| `hermodr_outbox_records` | gauge | `event_type` | Total unpublished/unconsumed only if importer checkpoint is visible; otherwise expose total sequence and document semantics. |
| `hermodr_outbox_sequence` | gauge | none | Highest committed sequence for importer lag calculation. |
| `hermodr_reporting_subjects` | gauge | `state` | Aggregate enrolled subjects in `current`, `stale`, `disabled`, or `unknown` state. |
| `hermodr_worst_ingest_age_seconds` | gauge | none | Greatest age of last authenticated, structurally valid real-device contact across active subjects; retries do not advance it. |
| `hermodr_worst_capture_age_seconds` | gauge | none | Greatest age of latest captured event across active subjects, preventing delayed backlog from appearing current. |
| `hermodr_last_processed_timestamp_seconds` | gauge | none | Processor progress heartbeat. |
| `hermodr_retention_actions_total` | counter | `record_type`, `result` | Retention execution health. |
| `hermodr_backup_status` | gauge | `stage` | Last known success (1/0) for create/verify/restore-test. |
| `hermodr_backup_last_success_timestamp_seconds` | gauge | `stage` | Backup freshness. |

Histograms use fixed buckets derived from the latency SLO and expected local operation. Metrics tests gather the registry and assert that forbidden canary values are absent. No metric is labeled by subject, device, credential, person, or place. The aggregate ingest/capture freshness metrics still disclose activity timing, so access is restricted. A duplicate retry does not update source-contact freshness, and an old delayed event can update receipt freshness without updating latest capture time; dashboards and alerts show both. A restricted `hermodr admin reporting-status` command maps an aggregate warning to affected pseudonymous subjects without exposing coordinates.

Critical gauges are calculated from durable database state on every scrape or refreshed at startup before readiness succeeds. Prometheus-compatible time-series storage, dashboard state, and alert rules live on persistent volumes. Process counters are allowed to reset and are interpreted with `process_start_time_seconds`; availability, backlog, freshness, outbox, backup, integrity, and storage alerts never depend solely on an in-memory counter.

### 10.3 Structured logs

Emit JSON to stdout/journald with:

- timestamp, level, service, event name, message;
- build version and configuration fingerprint at startup;
- request ID and ingest ID where relevant;
- job/run ID and bounded stage/result/reason;
- duration and attempt count;
- authentication key ID only after successful authentication;
- stack trace only at error level and only after scrubbed error wrapping.

Forbidden fields and values include payload/body, latitude, longitude, altitude, addresses, place labels, authorization/cookie headers, secret material, raw SQL parameters, client IP, exact device/subject IDs, and arbitrary exception strings from parsers or drivers. Use a logging facade with an allowlist of field names; do not rely on a denylist alone.

Routine successful ingestion is sampled or summarized after initial commissioning, while state changes, quarantine, errors, admin operations, and audit events are never sampled. Request IDs originate at fenrir when valid and are replaced when malformed.

### 10.4 Tracing and correlation

Distributed tracing is optional for the single-host MVP. Correlation IDs in logs plus histogram metrics are enough initially. If OpenTelemetry is enabled later:

- sampling is low and local/export is disabled by default;
- span attributes use the same field allowlist as metrics;
- bodies, database statements/parameters, URLs with queries, device IDs, and location-bearing record names are excluded;
- trace context from the public client is not trusted; fenrir creates or sanitizes it.

### 10.5 Dashboards

Provide a checked-in dashboard definition with four rows:

1. **Ingestion:** accepted/rejected/duplicate/quarantine rates, p50/p95/p99 commit latency, auth failures, and both ingest-contact and captured-event age.
2. **Processing:** job states, oldest pending age, processing rate/duration, retry reasons, late-event/recompute rate.
3. **Storage/outbox:** database and WAL size, free bytes, storage errors/latency, outbox head/checkpoint lag.
4. **Reliability:** readiness, restarts, last backup/create/verify/restore-test success, integrity checks, and current alerts.

Dashboard annotations should mark deployments, configuration-version changes, credential rotations, migrations, reprocessing, and restores. Annotation content uses audit IDs, not secrets or location details.

### 10.6 Initial alert rules

Thresholds are configuration defaults and require commissioning against normal iOS behavior.

| Alert | Initial condition | Severity/action |
| --- | --- | --- |
| `HermodrReceiverUnavailable` | synthetic durable-ingest probe fails for 5 minutes | page/operator; inspect fenrir, receiver, storage |
| `HermodrReceiverErrorRate` | 5xx > 2% of requests for 10 minutes and at least 5 requests | urgent; avoid low-traffic noise |
| `HermodrIngestLatencyHigh` | p95 > 500 ms for 15 minutes with sufficient samples | warning |
| `HermodrNoRecentReport` | one or more active subjects are stale according to both receipt and capture thresholds | aggregate warning phrased as tracking/connectivity only; restricted CLI identifies subject |
| `HermodrStaleDelayedUpload` | receiver contact is recent but latest captured event remains old | warning that delayed evidence is arriving |
| `HermodrProcessorBacklog` | oldest pending > 15 minutes or rising for 30 minutes | warning; page if > 2 hours |
| `HermodrProcessingDeadLetters` | failed job inventory > 0 for 10 minutes | warning and quarantine/dead-letter review |
| `HermodrQuarantineGrowth` | inventory increases above learned baseline or oldest exceeds review SLA | warning |
| `HermodrStorageLow` | free < 20% warning; < 10% critical, plus time-to-full prediction | operator action |
| `HermodrDatabaseErrors` | commit/integrity failure > 0 | critical; readiness should fail where appropriate |
| `HermodrWalGrowth` | WAL exceeds configured absolute/relative bound for 15 minutes | warning |
| `HermodrOutboxBacklog` | importer sequence lag/age exceeds integration SLO | warning; disabled before importer exists |
| `HermodrBackupStale` | no verified backup within configured interval | warning |
| `HermodrRestoreTestStale` | no successful isolated restore within 35 days | warning |
| `HermodrClockSkew` | future-timestamp flags exceed small count/rate window | warning; investigate phone/Odin time |

Alerts must link to a specific runbook section. Alerts based on absence require `for` durations and inhibit during declared maintenance. A no-report alert must say: “No Hermóðr report has been received; tracking or connectivity may be interrupted. This does not establish the subject’s location or safety.”

### 10.7 Audit trail

Audit events are durable domain records, not application logs. They cover authentication-key lifecycle (key ID only), config and derivation-version activation, migration, export, quarantine disposition, reprocessing, retention, deletion, backup, restore test, and emergency shutdown. A chained hash over canonical audit entries makes accidental or casual alteration detectable; backup verification checks the chain.

### 10.8 Operational runbooks

Before production, check in executable procedures for:

- receiver/processor restart and post-restart durability verification;
- credential creation, overlap rotation, client cutover, and revocation;
- quarantine and dead-letter review without printing raw coordinates by default;
- bounded reprocessing with dry-run impact count and algorithm version;
- encrypted backup, integrity verification, isolated restore, and recovery-key access;
- storage pressure and runaway WAL response;
- database corruption response (stop writes, preserve files, restore; never ad-hoc repair first);
- prolonged no-report diagnosis and safe wording;
- bounded subject/time deletion, tombstone propagation, and downstream confirmation;
- emergency public endpoint shutdown at fenrir while preserving local data.
- full-path reboot validation and diagnosis when services, scrapes, dashboards, or alert evaluation do not resume.

## 11. Backup, Restore, Retention, and Deletion

Use SQLite's online backup API or a transactionally consistent snapshot, never a blind copy of a live database file. Each backup receives an encrypted artifact, manifest, application/schema version, timestamp, size, and cryptographic checksum. Verification consists of decrypting into an isolated directory, opening it with the target release, running integrity and migration-compatibility checks, and periodically executing a complete restore drill.

Retention runs in small transactions and records counts and time bounds in the audit trail. Raw deletion is suspended when an active derived record still requires its evidence, represented by a hold. The design must specify whether retained derived records keep source digests after raw expiration; the recommendation is yes, while dropping the raw payload and preserving non-reversible provenance.

User deletion is stronger than ordinary retention: it creates a reviewed plan, supersedes or deletes dependent derived records as policy requires, removes restricted payloads, emits outbox tombstones, and produces an audit result that does not itself retain deleted location facts.

## 12. Deployment Design

Recommend systemd for Odin unless the existing host deployment standard strongly favors Compose. Receiver and processor use separate units, identities or permission profiles, restart policies, resource limits, and writable paths. Units are enabled at boot, ordered after durable mounts and required networking, use bounded restart backoff, and do not report ready until migrations and storage checks pass. Fenrir, the monitoring collector, dashboard, and alert evaluator receive equivalent boot-enable and persistent-storage verification on their respective hosts. A deployment sequence is:

1. Install the versioned artifact beside the current version.
2. Stop or drain receiver only for migrations that cannot coexist.
3. Create and verify a pre-migration encrypted backup.
4. Run `hermodr migrate` and record its audit event.
5. Start processor, then receiver; wait for readiness and a synthetic durable-ingest probe.
6. Observe error, latency, queue, WAL, and disk signals through a soak window.
7. Keep the prior binary available. Application rollback must tolerate the current schema; otherwise restore is a separately approved data rollback and risks newer data.

Migrations are forward-only in application logic. “Reversible through backup restoration” means restore to an isolated location first and explicitly reconcile any raw events received after the backup; never automatically overwrite newer evidence.

## 13. Testing Strategy

- **Unit/property tests:** strict parsers, coordinate and timestamp boundaries, canonical hashing, distance math, deterministic IDs, state transitions, retry schedules, redaction.
- **Golden contract tests:** sanitized OwnTracks fixtures to canonical JSON and JSON Schema validation.
- **Storage integration tests:** real SQLite WAL database, concurrent claims, crashes around commit/ack boundaries, lock contention, migrations, retention holds.
- **Determinism tests:** randomized input order and duplicate injection produce byte-identical active canonical state and stable outbox effects.
- **Scenario tests:** known-place arrival/departure, overlap ambiguity, poor accuracy, gaps, late data, antimeridian/pole cases, algorithm supersession.
- **Privacy tests:** secret/coordinate canaries passed through all errors and fixtures; scan logs, metrics, health responses, snapshots, and test reports.
- **Failure-injection tests:** disk full, read-only database, slow fsync, corrupt test copy, expired lease, receiver termination during commit, processor termination during outbox transaction.
- **Performance tests:** at least 10 requests/second with fsync and metrics enabled; report p50/p95/p99 and resource usage.
- **Restore tests:** encrypted backup restored into an isolated path, integrity checked, service started, and sampled ingest/outbox IDs reconciled.
- **Reboot tests:** reboot each host and then the complete path; verify automatic gateway, receiver, processor, monitoring, dashboard, and alert recovery, lease reclamation, queued work progress, persistent time series, and reconstruction of state-derived metrics before any new device event.
- **Subject-isolation tests:** attempt cross-subject authentication, reads, derivation evidence, outbox publication, retention, export, and deletion; all must fail closed without leaking existence.
- **External contract tests:** fenrir route/method/body limits and a fake Napoleon importer with independent checkpoint/idempotency.

No production coordinates or credentials appear in fixtures. Test coordinates are conspicuously synthetic and geographically non-sensitive.

## 14. Decisions Required Before Production

| Decision | Recommendation | When required |
| --- | --- | --- |
| Authentication mode | Decided: Basic over TLS; credential maps to device and subject | ADR 0004 |
| Single vs batch body | Decided: one object; reject arrays; ignore empty publish | ADR 0005 |
| Deployment | Decided: systemd on Odin | ADR 0003 |
| SQLite driver/build | Decided: Python `sqlite3` with exact-allowlisted private SQLite 3.53.4 runtime | ADR 0002 and `docs/m1/SQLITE_RUNTIME.md` |
| Public hostname/path | Preserve `/v1/owntracks`; choose hostname operationally | Fenrir integration |
| Retention defaults | PRD values, explicitly approved for version 1 and separately reviewed for version 2 | Each production gate |
| Derivation thresholds | Calibrate with synthetic route, then user-approved real-device trial | Phase 2 acceptance |
| No-report thresholds | Mode-aware, likely multiple expected-report intervals; never safety wording | Commissioning |
| Backup target/key recovery | Encrypted off-host target with documented recovery custodian | Before real data |
| Raw receiver choice | Thin Hermóðr receiver; Recorder adds a second contract and storage path | Foundation decision |
| At-rest protection | Verify encrypted Odin volume; evaluate database-level encryption if not present | Security review |

## 15. Explicit Deferrals

- Memgraph writes and Napoleon importer implementation.
- External reverse geocoding.
- Automatic discovered-place approval.
- Remote administration API.
- Distributed tracing backend.
- Subjects beyond the two-subject version 2 scope.
- PostgreSQL, broker, or separate outbox database.
