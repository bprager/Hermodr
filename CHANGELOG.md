# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once software releases begin.

## [Unreleased]

### Added

- Audited credential staging and revocation commands that validate protected secret files and refuse to revoke a subject's final usable credential.
- Atomic encrypted-backup replication to the approved RAID-5-backed `saga` destination, followed by verification and isolated restoration of the off-host copy.
- A Hermóðr-specific SOPS/age-encrypted backup-passphrase recovery artifact and custodian runbook; only ciphertext and its public recipient are committed.

- Transactional subject-partitioned processing with durable leases, reboot reclamation, bounded retry/dead-letter handling, deterministic normalization, quality flags, and canonical outbox publication.
- Accuracy-aware versioned places plus deterministic event-time visits, transitions, trips, coverage gaps, recomputation, source-transition reconciliation, and supersession events.
- Approved default retention controls, explicit evidence holds, count-checked two-step deletion, idempotent tombstones, and audit-chain verification during backup and restore checks.
- Guarded outbox consumer checkpoints, receipts, compatibility validation, forbidden-projection rejection, replay tests, and a graph-client-free fake importer.
- Reconstructed recomputation, retention-overdue, deletion-plan, and outbox-checkpoint metrics with dashboard panels and alert rules.
- Audited administrative commands and processing/lifecycle runbooks for reprocessing, retention, deletion, and audit verification.

- Synthetic-only M3 deployment with hardened boot-enabled migration, receiver, processor-sentinel, metric-export, and encrypted-backup units and persistent timers.
- Restricted TLS gateway route with method/body/time/rate limits, sanitized access logging, peer filtering, and private-route denial tests.
- Persistent Prometheus collection with 13 recording/alert rules and a four-row Grafana operations dashboard plus notification bridge rules.
- GPG AES-256 SQLite online backups with encrypted manifests, integrity checks, schema/table/identifier reconciliation, and isolated restore testing.
- Restart, rotation, storage-pressure, corruption, restore, no-report, endpoint-shutdown, and notification-failure runbooks.
- M3 backup, recovery, processor-sentinel, deployment-artifact, and CLI tests while retaining greater-than-95-percent aggregate coverage.
- Append-only operational audit IDs and persistent Grafana annotations for deployments, configuration activation, and credential rotation.
- M2 secure durable receiver with separate ingestion and private operations listeners.
- Protected-file HTTP Basic credentials bound to active device and subject records, including overlapping rotation windows and cross-subject rejection tests.
- Strict request size, media type, encoding, JSON, timestamp, coordinate, message-type, and source-identity validation with deterministic responses.
- Canonical raw evidence, SHA-256 source digests, keyed idempotency, safe transport metadata, and atomic processing-job creation.
- Exact-duplicate acknowledgement, future-timestamp quarantine, graceful in-flight drain, liveness, and storage-backed readiness.
- Bounded receiver counters and latency histograms plus database, WAL, shared-memory, filesystem, queue, quarantine, freshness, outbox, and backup gauges.
- M2 crash-boundary, privacy-canary, dual-listener, authentication, conformance, and synchronous-FULL load tests with 100% aggregate line coverage.
- M2 validation and observability documentation with explicit deployment and reboot limitations.
- M1 dependency-free reproducible wheel with `receiver`, `processor`, `admin`, and `migrate` command boundaries.
- Versioned strict SQLite migration framework and multi-subject-ready initial schema with scoped repository APIs.
- Canonical JSON Schemas and synthetic golden fixtures for observations, transitions, visits, trips, coverage gaps, places, and outbox envelopes.
- Deterministic identifiers, canonical hashing, bounded domain enums, strict configuration loading, and build metadata.
- Allowlist-only structured logging and metric facade with durable critical-gauge reconstruction.
- M1 observability/reboot contract and automated validation evidence.
- Enforced standard-library-only dependency and license inventory with external-import scanning.
- Reproducible private SQLite 3.53.4 supply with official archive checksum, exact source-identity validation, and application-linked CI testing.
- Synthetic OwnTracks HTTP capture/replay harness covering supported message types, duplicates, ordering, body shapes, content types, empty publishes, and transient retry responses.
- Standard-library test suite and CI with a strict greater-than-95-percent line coverage gate.
- ADRs selecting Python, guarded SQLite, systemd, Basic-over-TLS authentication, and a single-object HTTP contract.
- M0 protocol findings, privacy checklist, and redacted deployment inventory.
- Initial product requirements for authenticated, local-first location ingestion and deterministic processing.
- Implementation design covering receiver, processor, durable SQLite queue, canonical outbox, privacy, security, deployment, and testing.
- Milestone-based implementation plan with acceptance traceability.
- Maintained implementation backlog with priorities, dependencies, and acceptance evidence.
- Privacy-neutral project README.
- Immediate version 2 scope for a separately enrolled and isolated second tracked subject.
- Full-path reboot recovery requirements for gateway, receiver, processor, monitoring, dashboards, and alert evaluation.
- Persistent critical-monitoring design with state-derived metric reconstruction after restart.

### Changed

- Advanced the database schema to version 6 for normalized evidence, derivation metadata, retention policies, deletion plans, consumer receipts, payload expiration, and reboot-persistent recompute windows.
- Made the boot-enabled processor drain durable work and recomputation instead of serving only as a heartbeat sentinel.
- Completed the version 1 policy approvals and independent recovery drill: retention defaults, public route, RAID-5-backed `saga` destination, Bernd as custodian, and verified Bitwarden/SOPS recovery with no identity copy retained on Odin.

- Completed the synthetic-only M3 operational baseline after certificate-verified Grafana delivery through a boot-enabled local relay received upstream SMTP acceptance with an empty queue.
- Made SMTP configuration durable in the encrypted source of truth, tightened live secret-file permissions, and pinned the local relay certificate into the Grafana trust store without disabling verification.
- Documented local-relay health, queue, certificate-rotation, raw environment parsing, and secondary-notification limitations.
- Eliminated duplicate Hermodr metric and alert series by assigning them to one filtered scrape, and mounted the existing Prometheus file-discovery targets to stop repeated watch errors.
- Corrected the live Grafana Compose environment precedence that previously blanked configured SMTP connection values.
- Completed gateway and application-host reboot drills with an unchanged queued event, monitoring history spanning reboot, restored dashboard/rules, and a firing-to-resolved durable-ingest alert exercise.
- Advanced secure-collection backlog items HMD-009 through HMD-012 to Done and made M3 deployment/recovery work the active next milestone.
- Advanced the database schema to version 2 with safe receiver metadata, registered source identifiers, globally unique credential key IDs, and one processing job per ingest.
- Changed `hermodr receiver` from a startup-only scaffold into the runnable receiver service while retaining `--check` validation.
- Completed the repository-executable M1 contracts foundation and advanced foundation backlog items HMD-005 through HMD-008 to Done.
- Expanded CI to build the release artifact and validate migrations, canonical contracts, cross-subject isolation, and observable-output privacy.
- Completed the repository-executable M0 decision spike and recorded remaining hardware and policy checks as explicit production gates.
- Changed the provisional success response to OwnTracks-compatible `200 []` and documented zero-length publish handling.
- Replaced the initial Go recommendation with Python 3.13 based on host evidence.
- Made the version 1 credential, schema, processing, policy, audit, and deletion design multi-subject-ready.
- Replaced subject-identifying metric dimensions with aggregate state and worst-case freshness signals plus restricted diagnostics.
- Expanded production acceptance to include full-path reboot and monitoring-continuity drills.

### Security

- Added constant-time credential comparison, fail-closed secret permission/length checks, generic authentication failures, payload identity checks, and stable deduplication secrets outside source control.
- Ensured public routes cannot expose private health or metrics endpoints and tested observable output against credential, coordinate, and parser-error canaries.
- Replaced the unresolved SQLite availability prerequisite with an exact version/source allowlist, hardened compile flags, private loader path, and reboot-verification contract.
- Continued rejecting the affected system SQLite library while approving only the pinned fixed private build for production WAL activation.
- Added cross-subject isolation requirements and negative tests throughout authentication, storage, derivation, outbox, export, retention, and deletion.
- Added independent device credential revocation and separately reviewed subject policies.
