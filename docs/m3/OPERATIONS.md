# M3 Operations Baseline

This is the deployment contract for the unattended synthetic-only baseline. Host-specific paths, addresses, account names, and secrets belong in protected local configuration, not this repository.

## Runtime topology

- The TLS gateway accepts only `POST /v1/owntracks`, caps bodies at 64 KiB, applies a two-request-per-second rate with a bounded burst, and uses a request log format that excludes authorization, query strings, and bodies.
- The receiver's public listener is peer-filtered to the gateway and localhost by systemd. Health, readiness, and metrics bind to loopback only.
- Migration runs before the receiver and processor. Both long-running units use bounded restart backoff and boot enablement.
- The M3 processor is a heartbeat sentinel. It proves process ordering and reboot recovery but intentionally does not claim jobs; durable job execution starts in M4.
- A persistent systemd timer reconstructs critical metrics from SQLite and atomically publishes them to a node-exporter textfile collector. Prometheus retains series in a named volume.
- Prometheus ingests Hermodr textfile metrics through one dedicated filtered scrape; any general scrape of the same exporter drops `hermodr_*` to prevent duplicate series and notifications.
- Grafana provisions the four-row dashboard and two notification bridge rules from files while its database remains in a named volume. A boot-enabled local SMTP relay provides notification delivery; its public certificate is added to Grafana's trust store so opportunistic STARTTLS retains hostname and chain verification.
- The daily backup timer uses SQLite's online backup API, `PRAGMA integrity_check`, a manifest containing table counts and cryptographic identifier-set fingerprints, GPG AES-256 encryption, verification, and an isolated restore test.

## Critical signals

Restart-safe gauges cover database/WAL/shared-memory size, filesystem free bytes, database integrity, processing jobs by state, oldest pending age, aggregate reporting freshness, quarantine counts, outbox sequence, processor heartbeat, and create/verify/restore-test backup status and timestamps. The exporter adds `hermodr_metrics_bridge_up` so a failed reconstruction cannot leave stale healthy values behind.

Prometheus evaluates durable-ingest availability, 5xx rate, p95 acceptance latency, report freshness, disk/WAL pressure, database integrity, backup freshness, metrics-export health, and processor-sentinel freshness. Grafana bridges firing Prometheus alerts to its configured notification policy.

The SMTP relay is an operational dependency. Monitor its unit and queue, test the contact point after certificate or network changes, and rebuild the pinned Grafana trust layer before the relay certificate expires or rotates. SMTP acceptance proves transfer to the upstream server, not display in a recipient mailbox; production operations should add an independently monitored delivery path.

## Backup guarantees and boundaries

Backup archives contain only `database.sqlite` and `manifest.json`; both are encrypted together. Restore never overwrites the live database. Verification fails on decryption, archive shape, SHA-256, SQLite integrity, schema version, table-count, or identifier-fingerprint disagreement.

The encryption passphrase is a protected `0600` file owned by the service identity. The daily workflow atomically copies each locally verified archive to the approved RAID-5-backed `saga` destination, then verifies and restore-tests the off-host copy. Bernd is the accountable recovery-key custodian. The Hermóðr-specific age identity is held in Bitwarden independently of both Odin and Saga; its completed retrieval drill decrypted the repository SOPS artifact and restore-tested a Saga archive without documenting secret content.

## Deployment artifacts

- `deploy/systemd/`: hardened units, timers, and atomic helper scripts.
- `deploy/fenrir/`: isolated nginx global and location includes.
- `deploy/monitoring/`: Prometheus rules, Grafana delivery rules, provider, and dashboard JSON.
- `docs/runbooks/`: operator recovery procedures.

Validate systemd with `systemd-analyze verify`, nginx with `nginx -t`, Prometheus with `promtool check config` and `promtool check rules`, and Grafana provisioning through its authenticated API before activation.
