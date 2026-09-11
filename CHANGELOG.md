# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once software releases begin.

## [Unreleased]

### Added

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

- Completed the repository-executable M1 contracts foundation and advanced foundation backlog items HMD-005 through HMD-008 to Done.
- Expanded CI to build the release artifact and validate migrations, canonical contracts, cross-subject isolation, and observable-output privacy.
- Completed the repository-executable M0 decision spike and recorded remaining hardware and policy checks as explicit production gates.
- Changed the provisional success response to OwnTracks-compatible `200 []` and documented zero-length publish handling.
- Replaced the initial Go recommendation with Python 3.13 based on host evidence.
- Made the version 1 credential, schema, processing, policy, audit, and deletion design multi-subject-ready.
- Replaced subject-identifying metric dimensions with aggregate state and worst-case freshness signals plus restricted diagnostics.
- Expanded production acceptance to include full-path reboot and monitoring-continuity drills.

### Security

- Replaced the unresolved SQLite availability prerequisite with an exact version/source allowlist, hardened compile flags, private loader path, and reboot-verification contract.
- Continued rejecting the affected system SQLite library while approving only the pinned fixed private build for production WAL activation.
- Added cross-subject isolation requirements and negative tests throughout authentication, storage, derivation, outbox, export, retention, and deletion.
- Added independent device credential revocation and separately reviewed subject policies.
