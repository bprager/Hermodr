# Hermóðr Backlog

**Last reviewed:** 2026-09-11
**Source of truth:** this file
**Statuses:** `Ready`, `Blocked`, `In Progress`, `Done`, `Deferred`

## Maintenance Rules

- Add or update an item whenever scope, priority, dependency, or acceptance evidence changes.
- Move completed outcomes to `Done`; do not delete history.
- Add notable user- or operator-visible results to `CHANGELOG.md` under `Unreleased` in the same change.
- Link implementation commits, ADRs, test reports, or operational evidence in the Evidence column.
- Keep real coordinates, secrets, production payloads, addresses, and direct personal identifiers out of backlog text and evidence filenames.

## Now — Decision and Foundation

| ID | Release | Priority | Status | Work | Dependency | Acceptance evidence |
| --- | --- | --- | --- | --- | --- | --- |
| HMD-001 | V1 | P0 | Done | Capture sanitized source-client payload and retry behavior for every supported message type. | Disposable test endpoint | `docs/m0/OWNTRACKS_HTTP_FINDINGS.md`; synthetic harness and fixtures |
| HMD-002 | V1 | P0 | Done | Inventory gateway and application hosts for boot ordering, storage encryption, time sync, service identities, backup, and monitoring. | Host access | `docs/m0/HOST_INVENTORY.md`; inaccessible facts explicitly listed |
| HMD-003 | V1 | P0 | Done | Decide implementation language, SQLite driver, deployment mode, authentication mode, and request body shape. | HMD-001, HMD-002 | ADRs 0001–0005 |
| HMD-004 | V1 | P0 | Blocked | Approve retention defaults, public route, backup destination, and recovery-key ownership. | External policy/infrastructure authority | `docs/m0/PRIVACY_RETENTION_CHECKLIST.md`; three approvals pending |
| HMD-005 | V1 | P0 | Done | Scaffold receiver, processor, admin, and migration commands. | HMD-003 | Reproducible wheel; `docs/m1/VALIDATION.md` |
| HMD-006 | V1 | P0 | Done | Create multi-subject-ready schema, migrations, invariants, and subject-scoped repository APIs. | HMD-003 | Migration and cross-subject tests in `tests/test_m1_foundation.py` |
| HMD-007 | V1 | P0 | Done | Define canonical JSON Schemas, deterministic identifiers, hashing, bounded errors, and quality flags. | HMD-001 | `contracts/v1`; synthetic golden contract suite |
| HMD-008 | V1 | P0 | Done | Build the allowlist-only logging and metric facade with sensitive-canary tests. | HMD-005 | `docs/m1/OBSERVABILITY.md`; privacy tests |
| HMD-036 | V1 | P0 | Done | Supply and verify an approved WAL-reset-fixed SQLite runtime without replacing the system library. | HMD-003 | `docs/m1/SQLITE_RUNTIME.md`; pinned manifest; runtime CI |

## Next — Secure Collection and Operations

| ID | Release | Priority | Status | Work | Dependency | Acceptance evidence |
| --- | --- | --- | --- | --- | --- | --- |
| HMD-009 | V1 | P0 | Done | Implement credential-to-device-to-subject authentication and safe rotation. | HMD-006 | `docs/m2/VALIDATION.md`; authentication/isolation matrix |
| HMD-010 | V1 | P0 | Done | Implement strict validation, raw canonicalization, digest, idempotency, and atomic durable acknowledgement. | HMD-006, HMD-007 | `docs/m2/VALIDATION.md`; crash and duplicate tests |
| HMD-011 | V1 | P0 | Done | Implement quarantine, deterministic responses, graceful drain, liveness, and storage-backed readiness. | HMD-010 | `docs/m2/VALIDATION.md`; receiver conformance suite |
| HMD-012 | V1 | P0 | Done | Meet the durable-ingest latency and throughput targets on target storage. | HMD-010 | `docs/m2/VALIDATION.md`; synchronous-FULL load gate |
| HMD-013 | V1 | P0 | Done | Deploy boot-enabled hardened services and the restricted HTTPS gateway route. | HMD-002, HMD-011 | `docs/m3/VALIDATION.md`; validated systemd/nginx activation |
| HMD-014 | V1 | P0 | In Progress | Deploy persistent metric collection, dashboard, alert rules, and durable synthetic-ingest probing. | HMD-008, HMD-013 | Collection/evaluation/firing/recovery pass; external SMTP authentication blocks delivery proof |
| HMD-015 | V1 | P0 | Done | Reconstruct critical gauges from durable state at startup. | HMD-006, HMD-014 | `docs/m3/VALIDATION.md`; restart test without new input |
| HMD-016 | V1 | P0 | Done | Implement encrypted backup, integrity verification, and isolated restore. | HMD-006, HMD-013 | `docs/m3/VALIDATION.md`; reconciled restore report |
| HMD-017 | V1 | P0 | Done | Exercise component and full-path reboots with queued work, persistent metrics, dashboards, and alert evaluation. | HMD-013–HMD-016 | `docs/m3/VALIDATION.md`; both hosts and pre-boot queue/history verified |
| HMD-018 | V1 | P0 | Done | Write and exercise restart, credential, storage, corruption, backup, no-report, and emergency-shutdown runbooks. | HMD-013–HMD-017 | `docs/runbooks/M3_OPERATIONS.md`; restart/backup/alert/emergency-stop paths exercised |

## Later — Processing and Data Lifecycle

| ID | Release | Priority | Status | Work | Dependency | Acceptance evidence |
| --- | --- | --- | --- | --- | --- | --- |
| HMD-019 | V1 | P0 | Ready | Implement subject-partitioned leases, retries, dead-letter handling, heartbeat, and reboot reclamation. | HMD-006 | Crash/concurrency suite |
| HMD-020 | V1 | P0 | Ready | Normalize every supported source type with provenance and algorithm/config versions. | HMD-007, HMD-019 | Golden fixture suite |
| HMD-021 | V1 | P0 | Ready | Implement accuracy-aware place resolution and versioned place registry. | HMD-020 | Geospatial boundary suite |
| HMD-022 | V1 | P0 | Ready | Specify and implement transitions, visits, trips, gaps, confidence, and ambiguity rules. | HMD-021 | Controlled-route scenarios |
| HMD-023 | V1 | P0 | Ready | Implement bounded recomputation, deterministic convergence, and supersession. | HMD-022 | Shuffled/duplicate/late-event suite |
| HMD-024 | V1 | P0 | Ready | Implement canonical append-only outbox and fake importer conformance tests. | HMD-020, HMD-023 | End-to-end importer report |
| HMD-025 | V1 | P0 | Ready | Implement subject-policy retention, evidence holds, audited two-step deletion, and outbox tombstones. | HMD-024 | Retention/deletion report |
| HMD-026 | V1 | P0 | Ready | Complete version 1 real-device commissioning and acceptance. | HMD-001–HMD-025 | Signed acceptance checklist |

## Immediate Follow-on — Two-Subject Version 2

| ID | Release | Priority | Status | Work | Dependency | Acceptance evidence |
| --- | --- | --- | --- | --- | --- | --- |
| HMD-027 | V2 | P0 | Blocked | Approve second-subject enrollment, access, retention, notification, export, deletion, and downstream-projection policy. | HMD-026 | Approved policy and enrollment audit |
| HMD-028 | V2 | P0 | Blocked | Enroll the second subject/device with independent credential rotation and revocation. | HMD-027 | Enrollment and revocation proof |
| HMD-029 | V2 | P0 | Blocked | Execute cross-subject negative tests across the entire data lifecycle. | HMD-028 | Isolation test report |
| HMD-030 | V2 | P0 | Blocked | Validate aggregate monitoring and restricted affected-subject diagnosis. | HMD-028 | Metric privacy and alert report |
| HMD-031 | V2 | P0 | Blocked | Run two-subject load, fairness, delayed-upload, backup/restore, deletion, and full-path reboot drills. | HMD-029, HMD-030 | Version 2 operations report |
| HMD-032 | V2 | P0 | Blocked | Complete version 2 acceptance and activation. | HMD-027–HMD-031 | Signed version 2 checklist |

## Deferred

| ID | Release | Priority | Status | Work | Dependency | Acceptance evidence |
| --- | --- | --- | --- | --- | --- | --- |
| HMD-033 | Future | P2 | Deferred | Add local reverse geocoding. | Explicit privacy approval | Design and privacy review |
| HMD-034 | Future | P2 | Deferred | Add user-facing place correction and annotation. | Stable derivation contract | Product acceptance |
| HMD-035 | Future | P2 | Deferred | Evaluate PostgreSQL when measured scale requires it. | Capacity evidence | Migration ADR |
