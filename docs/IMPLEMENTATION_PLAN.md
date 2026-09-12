# Hermóðr Implementation Plan

**Status:** Active; M0 through M2 are repository-complete
**Companion design:** `docs/IMPLEMENTATION_DESIGN.md`

## 1. Delivery Approach

Build in vertical, demonstrable increments. Secure durable ingestion and its operational signals come first; derivation work begins only after crash safety, privacy controls, reboot recovery, backup restoration, and critical monitoring are proven. Version 1 is multi-subject-ready but activates one subject. The two-subject version 2 begins immediately after version 1 acceptance. Every milestone ends with evidence that can be attached to the production-readiness review.

The plan uses these priority levels:

- **P0:** required for safe production activation and PRD acceptance.
- **P1:** required for the complete MVP but can follow initial collection commissioning.
- **P2:** useful hardening or convenience that can follow MVP acceptance.

## 2. Work Breakdown

### M0 — Decision and device-behavior spike

**Goal:** remove client and host uncertainties before contract freeze.

**Status:** Repository-complete on 2026-09-10. Real-device retry/header behavior and infrastructure policy approvals remain explicit commissioning gates.

- P0 Capture sanitized OwnTracks HTTP behavior for location, transition, waypoint, and status messages.
- P0 Verify supported bearer/Basic configuration, retry response behavior, content type, timestamp units, device/subject fields, and whether batching occurs.
- P0 Inventory Odin and fenrir deployment, boot ordering, filesystem encryption, backup, persistent monitoring, time-sync, and service-account standards.
- P0 Decide implementation language/SQLite driver, systemd versus Compose, and the private listener topology.
- P0 Record approved public route, retention values, credential workflow, and backup target/key recovery owner.
- P0 Create synthetic coordinate fixtures and explicitly prohibit production data in the repository.

**Exit evidence:** ADRs 0001–0005; sanitized request fixtures and capture/replay harness; successful synthetic endpoint exchange; host inventory; privacy/retention checklist with external approvals visibly pending.

### M1 — Repository and contracts foundation

**Goal:** create a testable artifact and stable boundaries.

**Status:** Repository-complete on 2026-09-10. The patched SQLite runtime supply is resolved; production activation remains gated on M2/M3 security and deployment work.

- P0 Scaffold `receiver`, `processor`, `admin`, and `migrate` commands with shared configuration, logging, metrics, clock, and identifier packages.
- P0 Add canonical JSON Schemas for observation, transition, visit, trip, coverage gap, place, and outbox envelope.
- P0 Define bounded error, quality-flag, job-state, audit-action, and metric-label enums.
- P0 Add migration framework and initial schema with foreign keys and invariants.
- P0 Make subject/device/credential relationships and every domain key multi-subject-ready; add repository-level subject scoping.
- P0 Define which critical metrics reconstruct from durable state and how the monitoring store survives reboot.
- P0 Add automated formatting, static analysis, unit tests, dependency/license scanning, and secret scanning.
- P0 Generate build metadata and `hermodr_build_info`.

**Exit evidence:** clean CI; migration up from empty database; schema/fixture validation; application starts only with valid non-production config.

**Evidence:** dependency-free reproducible wheel; migration 001; seven versioned contracts and synthetic fixtures; strict command startup checks; subject-isolation repository tests; allowlisted logs and metrics; durable critical-gauge reconstruction; `docs/m1/VALIDATION.md` and `docs/m1/OBSERVABILITY.md`.

### M2 — Secure durable receiver

**Goal:** meet Phase 1 collection requirements without enrichment coupling.

**Status:** Repository-complete on 2026-09-11. Public TLS/rate limiting, boot activation, persistent monitoring, alert delivery, backup/restore, and full-path reboot proof remain M3 gates.

- P0 Implement separate public ingestion and private operations listeners.
- P0 Implement authentication, rotation overlap, allowlists, size/content/encoding/JSON validation, and deterministic response codes.
- P0 Bind every credential to one registered device and subject; reject payload identity mismatches.
- P0 Implement raw canonicalization, digest, keyed idempotency, safe transport metadata, and atomic `raw_events` plus `processing_jobs` commit.
- P0 Implement exact-duplicate behavior and suspicious-event quarantine.
- P0 Implement graceful drain: stop accepting, finish bounded in-flight commits, then exit.
- P0 Add live/ready checks and fail readiness on storage/migration/hard disk-floor failures.
- P0 Add receiver metrics, allowlist-only structured logs, and redaction/canary tests.
- P0 Load-test at 10 requests/second with synchronous durability enabled.

**Exit evidence:** crash-boundary test proves no acknowledged loss; p95 acceptance below 500 ms at target load; duplicate and validation matrix passes; no sensitive canary appears in observable output.

**Evidence:** schema migration 002; dual-listener receiver; protected secret references and overlapping credentials; atomic ingest repository; bounded metrics/logging; 61-test suite at 100% line coverage; `docs/m2/VALIDATION.md` and `docs/m2/OBSERVABILITY.md`.

### M3 — Deployment, reboot, monitoring, and recovery baseline

**Goal:** make collection safe to leave unattended before accepting real data.

**Status:** Complete on 2026-09-11 for the synthetic-only baseline. Services, TLS routing, persistent monitoring, rules/dashboard, certificate-verified notification delivery, encrypted restore-tested backups, audit-ID annotations, alert firing/resolution, and both host reboot drills passed. Production-policy, off-host recovery, and real-device commissioning remain later gates.

- P0 Create hardened, boot-enabled receiver/processor systemd units or Compose services with persistent data, dependency ordering, bounded restart backoff, and private bindings.
- P0 Create fenrir route with TLS, request/method limits, rate limiting, sanitized access logs, and synthetic event test.
- P0 Add Prometheus scrape configuration/recording rules and the four-row Hermóðr dashboard.
- P0 Persist monitoring time series, dashboard configuration, and alert rules; automatically resume scrape and evaluation after reboot.
- P0 Reconstruct queue, freshness, outbox, backup, integrity, and storage gauges from durable state before readiness.
- P0 Add alerts for durable-ingest availability, 5xx rate, latency, report freshness, disk/WAL, database errors, and backup freshness.
- P0 Implement encrypted backup, manifest, integrity verification, and isolated restore commands/workflows.
- P0 Write restart, token rotation, storage pressure, corruption, restore, no-report, and endpoint-shutdown runbooks.
- P0 Run a restore drill before real-device activation.
- P0 Run component-host and full-path reboot drills, including work queued before reboot and no new event after reboot.
- P1 Add deployment/config/credential-rotation dashboard annotations from audit IDs.

**Exit evidence:** test alert delivery; dashboard screenshots or exported test results; successful isolated restore with reconciled IDs; automatic full-path reboot recovery with critical metrics and alerts active; completed runbook exercise; fenrir cannot reach operations routes.

**Evidence:** 68-test suite at 99.39% line coverage; live gateway and application-host reboot drills; 13 loaded Prometheus rules; four-row dashboard and two delivery bridge rules; firing-to-resolved receiver alert; certificate-verified Grafana contact-point delivery accepted by the upstream SMTP server; encrypted backup and isolated restore reconciliation across schema version, 18 table counts, and 18 identifier fingerprints; `docs/m3/VALIDATION.md` and `docs/runbooks/M3_OPERATIONS.md`.

### M4 — Normalization and durable worker

**Goal:** turn evidence into deterministic canonical records safely.

- P0 Implement transactional leases, reclaim, bounded exponential retry with jitter, dead-letter failure, and processor heartbeat.
- P0 Partition work claiming, event ordering, and recomputation by subject and reclaim expired leases automatically after boot.
- P0 Implement adapters for all supported message types with golden fixtures.
- P0 Preserve device and receipt time, accuracy, provenance, source digest, schema version, and algorithm/config versions.
- P0 Implement bounded quality flags for late/future/poor-accuracy/out-of-order/implausible movement inputs.
- P0 Insert observation and outbox effects idempotently in the job completion transaction.
- P0 Add processor metrics, backlog age, retry/dead-letter alerts, and operator diagnostics.
- P0 Prove processor restart and concurrent-worker safety.

**Exit evidence:** every supported fixture normalizes deterministically; forced crashes/retries create no duplicate canonical effects; processor never attempts a Memgraph connection.

**Evidence:** transactional worker and source-adapter suite; reboot-persistent recompute state; processor systemd network restriction; `docs/m7/VALIDATION.md`.

### M5 — Event-time derivation and reprocessing

**Goal:** produce uncertainty-preserving places, transitions, visits, trips, and gaps.

- P0 Implement versioned local place registry and accuracy-aware great-circle matching.
- P0 Specify and test exact arrival, departure, dwell, trip segmentation, gap, overlap, and confidence rules.
- P0 Implement recompute-window scheduling/coalescing and stable event-time ordering.
- P0 Implement provisional/confirmed/superseded lifecycle and outbox supersession events.
- P0 Implement source-transition reconciliation and ambiguity handling.
- P0 Implement bounded CLI reprocessing with dry-run, reason, audit entry, and impact counters.
- P0 Test late/out-of-order input against controlled route fixtures and prove deterministic convergence.
- P1 Add proposed place clusters without automatic approval.

**Exit evidence:** controlled route produces expected visits and coverage gaps; shuffled/duplicated delivery produces identical active state; algorithm-version change preserves and supersedes provenance correctly.

**Evidence:** controlled-route, ambiguity, source-transition, late-event, subject-isolation, and algorithm-change tests in `tests/test_m5_m7_lifecycle.py`; `docs/m7/VALIDATION.md`.

### M6 — Retention, deletion, and operational completion

**Goal:** close the sensitive-data lifecycle.

- P0 Implement transactional retention with evidence holds and small batches.
- P0 Implement subject-policy-aware retention and two-step bounded deletion plan/apply by subject and time range across all stores.
- P0 Define and emit outbox tombstones; verify fake importer deletion acknowledgement.
- P0 Implement audit-chain verification and include it in backup checks.
- P0 Complete quarantine/dead-letter, reprocessing, retention, and deletion runbooks.
- P0 Verify operational-log retention independently of location-data retention.
- P1 Add safe export manifests if needed for acceptance evidence; do not add general location export unless approved.

**Exit evidence:** dry-run counts match applied deletion, restricted payloads are absent afterward, tombstones are idempotent, held evidence is preserved, and every action is auditable without retaining deleted location facts.

**Evidence:** retention-hold, stale-plan, exact-count, payload-removal, tombstone, and audit-tamper tests; backup audit-chain verification; `docs/runbooks/M4_M7_OPERATIONS.md`.

### M7 — Guarded outbox integration

**Goal:** prove the boundary to Napoleon without coupling Hermóðr to Memgraph.

- P0 Publish documented, versioned outbox envelope and compatibility policy.
- P0 Provide least-privilege read access or a bounded export mechanism to a fake importer.
- P0 Implement consumer checkpoint and idempotency in the test importer fixture.
- P0 Add observable outbox head/checkpoint lag without high-cardinality labels.
- P0 Verify rejected schema version, restricted entity type, replay, supersession, uncertainty, and tombstone behavior.
- P1 Hand the contract to the separately owned Napoleon importer project.

**Exit evidence:** end-to-end synthetic ingest reaches fake approved projection exactly once; forbidden projection is rejected; Hermóðr runtime has no Memgraph dependency or credential.

**Evidence:** versioned envelope validation, durable checkpoint/receipt replay suite, forbidden-type and unapproved-place policy, idempotent tombstone test, and graph-client-free fake importer; `docs/m7/VALIDATION.md`.

### M8 — Real-device commissioning and production gate

**Goal:** validate actual iOS behavior and obtain explicit approvals.

**Status:** In progress. Post-M4–M7 reboot recovery is verified and audited credential staging/revocation controls are repository-complete. Off-host recovery approval, real-device evidence, tuning, and signed acceptance remain open.

- P0 Activate with a rotatable production credential and verify revocation of the bootstrap credential.
- P0 Observe significant-change and selected-geofence behavior across connectivity loss and delayed upload.
- P0 Tune alert, accuracy, dwell, trip, gap, and rate-limit thresholds from observed behavior.
- P0 Confirm dashboard, alert routing, log redaction, data permissions, clock sync, backup freshness, and restore evidence.
- P0 Demonstrate every PRD acceptance criterion using an evidence checklist.
- P0 Obtain Bernd's explicit approval of battery behavior, event frequency, known-place setup, and retention.

**Exit evidence:** signed production-readiness checklist, acceptance test report, approved configuration fingerprint, and rollback/emergency shutdown rehearsal.

### M9 — Two-subject version 2 (starts immediately after M8)

**Goal:** enroll Quinn and prove that adding a second subject preserves privacy, correctness, recoverability, and operational visibility.

- P0 Record the required guardian authorization and age-appropriate assent or consent, using only the minimum necessary enrollment metadata.
- P0 Approve a separate version 2 access, retention, notification, export, deletion, and Napoleon-projection policy.
- P0 Enroll the second subject/device with independent credentials and demonstrate isolated rotation and revocation.
- P0 Execute cross-subject negative tests for authentication, storage queries, processing evidence, derived records, outbox, export, retention, and deletion.
- P0 Replace any version 1 singleton freshness presentation with aggregate reporting-subject state and worst-case freshness; diagnose affected subjects only through the restricted CLI.
- P0 Run aggregate-load, delayed-upload, processor-fairness, backup/restore, and full-path reboot tests with both subjects active.
- P0 Demonstrate deletion of one subject without changing the other subject's evidence or observability state.

**Exit evidence:** version 2 acceptance report, approved policy/enrollment audit records, complete isolation-test evidence, independent credential-revocation proof, and successful two-subject reboot/restore drill.

## 3. Recommended Repository Layout

```text
src/hermodr/                 production Python package
src/hermodr/commands/        receiver, processor, admin, migrate entry points
src/hermodr/config/          typed config, validation, fingerprints
src/hermodr/httpingest/      HTTP contract and middleware
src/hermodr/auth/            credential verification and rotation
src/hermodr/store/           SQLite repositories and transactions
src/hermodr/owntracks/       strict source adapters
src/hermodr/canonical/       canonical models and serialization
src/hermodr/processor/       claims, retry, normalization orchestration
src/hermodr/derive/          place/visit/trip/gap algorithms
src/hermodr/outbox/          envelope and append operations
src/hermodr/admin/           audited operator workflows
src/hermodr/observability/   logging, metrics, health, redaction
migrations/                  ordered SQL migrations
schemas/                     versioned JSON Schemas
testdata/synthetic/          non-sensitive golden fixtures
tools/owntracks_spike/       disposable M0 protocol harness
deploy/systemd/              service units and hardening
deploy/fenrir/               example route, no secrets
deploy/monitoring/           dashboards, rules, scrape examples
docs/runbooks/               operational procedures
docs/adr/                    architectural decisions
```

## 4. Critical Dependency Order

```text
Device/host spike
  -> contracts + migrations + observability primitives
  -> durable receiver
  -> deployment/backup/monitoring production baseline
  -> durable processor + normalization
  -> derivation + bounded reprocessing
  -> retention/deletion
  -> guarded importer contract
  -> version 1 real-device commissioning
  -> immediate version 2 subject enrollment + isolation acceptance
```

Schema, logging privacy, and metric-label conventions are foundation work because changing them late risks migrations, data leakage, and broken dashboards. Backup and restore precede real data. Visit/trip algorithms do not block safe Phase 1 collection.

## 5. Cross-Cutting Definition of Done

Every story that changes behavior is complete only when:

- requirements and canonical/error contracts are updated;
- success, boundary, failure, restart, and idempotency cases are tested as applicable;
- required services and critical monitoring recover automatically in a full-path reboot test;
- subject-scoped behavior includes a cross-subject negative test;
- logs/metrics/health output pass sensitive-canary scans;
- new metrics have bounded labels, documented semantics, dashboard placement, and alert consideration;
- operator-visible failure includes a stable reason code and runbook link;
- configuration changes are typed, validated, fingerprinted, and documented;
- migrations are tested from the last supported release and against restored backup copies;
- administrative mutation has dry-run where appropriate, reason capture, and audit coverage;
- no direct Memgraph, external geocoder, OpenClaw, Mimir, or LLM dependency is introduced.

## 6. Acceptance Traceability

| PRD area | Primary milestones | Verification artifact |
| --- | --- | --- |
| Receiver RCV-001–015 | M1–M3 | API matrix, crash test, load report, privacy scan |
| Processor PRC-001–018 | M4–M5 | golden/scenario tests, convergence and crash reports |
| Napoleon contract | M7 | fake importer conformance suite |
| Security SEC-001–012 | M0–M3, M6 | threat review, permission test, audit/deletion evidence |
| Reliability | M2–M3, M8 | latency/load results, restart and restore exercises |
| Observability/operations | M1–M3, all later milestones | metric contract, dashboard, alert tests, runbooks |
| Deployment | M0, M3 | hardened unit/config review and rollback rehearsal |
| Version 1 acceptance | M8 | criterion-by-criterion signed checklist |
| Version 2 second-subject acceptance | M9 | enrollment policy, isolation suite, reboot/restore and deletion evidence |

## 7. First Implementation Backlog

The first engineering iteration should contain only work that reduces foundational risk:

1. Use the completed M0 synthetic capture/replay matrix to validate real-device behavior during commissioning.
2. Apply ADRs 0001–0005 for language, patched SQLite, authentication, deployment, and body shape.
3. Freeze canonical time/ID/hash/error conventions and metric-label policy.
4. Create the initial schema and migration test harness.
5. Implement the observability facade with allowlisted fields and sensitive canary tests.
6. Implement subject-scoped repository APIs and credential-to-device-to-subject authority mapping.
7. Implement a minimal authenticated receiver transaction and duplicate path.
8. Kill the receiver at controlled commit points to validate acknowledgement semantics.
9. Reboot with queued work and prove critical state metrics reconstruct without new input.
10. Benchmark durable acceptance at 10 requests/second.

Do not begin place/visit/trip derivation until items 1–9 pass. They establish the evidence, isolation, recovery, and privacy guarantees every later algorithm depends on.

## 8. Planning Risks

- **Actual OwnTracks wire behavior differs from assumed examples.** Resolve in M0 and preserve captured sanitized fixtures.
- **SQLite lock or fsync behavior misses latency target on Odin storage.** Benchmark early; tune connection ownership/checkpointing before considering weaker durability or PostgreSQL.
- **Observability leaks behavioral timing even without coordinates.** Restrict access to metrics and audit logs; do not expose per-device series.
- **A reboot restarts applications but silently loses monitoring continuity.** Persist the monitoring store and reconstruct critical gauges from the database; exercise the whole path, not only each process.
- **Version 1 assumptions leak into version 2.** Require multi-subject keys and repository scoping from M1, plus cross-subject negative tests in every data lifecycle.
- **Derivation semantics expand without precise rules.** Treat every threshold and tie-breaker as a versioned contract with fixtures.
- **Append-only outbox conflicts with deletion.** Establish tombstone and downstream acknowledgement contract before importer implementation.
- **Backup exists but cannot be restored.** Alert on verified/restore-tested freshness, not merely file creation.
- **Rollback after migration could discard new raw events.** Require schema-compatible application rollback; treat data restore as an explicit recovery workflow.
