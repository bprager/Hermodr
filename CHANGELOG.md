# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once software releases begin.

## [Unreleased]

### Added

- Initial product requirements for authenticated, local-first location ingestion and deterministic processing.
- Implementation design covering receiver, processor, durable SQLite queue, canonical outbox, privacy, security, deployment, and testing.
- Milestone-based implementation plan with acceptance traceability.
- Maintained implementation backlog with priorities, dependencies, and acceptance evidence.
- Privacy-neutral project README.
- Immediate version 2 scope for a separately enrolled and isolated second tracked subject.
- Full-path reboot recovery requirements for gateway, receiver, processor, monitoring, dashboards, and alert evaluation.
- Persistent critical-monitoring design with state-derived metric reconstruction after restart.

### Changed

- Made the version 1 credential, schema, processing, policy, audit, and deletion design multi-subject-ready.
- Replaced subject-identifying metric dimensions with aggregate state and worst-case freshness signals plus restricted diagnostics.
- Expanded production acceptance to include full-path reboot and monitoring-continuity drills.

### Security

- Added cross-subject isolation requirements and negative tests throughout authentication, storage, derivation, outbox, export, retention, and deletion.
- Added independent device credential revocation and separately reviewed subject policies.
