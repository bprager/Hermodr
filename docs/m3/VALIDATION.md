# M3 Operational Baseline Validation

**Validation date:** 2026-09-11
**Activation scope:** synthetic data only

## Repository evidence

The release gate builds the wheel, validates the pinned patched SQLite runtime, runs static/dependency/privacy/Markdown checks, and executes 68 unit and integration tests. Aggregate line coverage is 99.39% (3444/3465), strictly above the required 95%.

Tests cover encrypted backup creation and failure states, archive/digest/integrity/schema/table/identifier reconciliation, isolated restore status, durable metrics, processor heartbeat, CLI boundaries, systemd hardening, gateway privacy, alert families, and the four dashboard rows.

## Live evidence before full-host reboot

- Hardened migration, receiver, processor sentinel, metric-export timer, and backup timer units are enabled on the application host.
- The private readiness endpoint reports ready; the gateway can reach ingestion but cannot connect to operations.
- The TLS route accepted one zero-coordinate synthetic event and returned an opaque ingest ID. SQLite and reconstructed Prometheus metrics both report one pending job.
- Nginx configuration validates, request logs omit secrets and bodies, and public health/metrics requests return 404.
- Encrypted backup creation, verification, and isolated restore report success. Critical backup and database-integrity gauges equal one.
- Prometheus validates and loads 13 Hermodr recording/alert rules from persistent configuration.
- Grafana provisions the dashboard and two delivery bridge rules from persistent configuration; its database reports healthy.
- The gateway host rebooted and its boot-enabled nginx stack returned automatically with `nginx -t` successful.

## Full-path reboot and alert evidence

- The application host changed boot ID from `9cef0fdb-8fec-4d4a-8abb-ce37eb56934f` to `1255e66a-37fa-437d-918f-e75fcdb250d8`.
- After boot, receiver, processor sentinel, metrics timer, and backup timer were enabled and active; readiness returned `ready` automatically.
- Without a new event, raw-event and pending-job counts remained exactly one, all three backup stages remained successful, and database integrity remained `ok`.
- The metrics bridge returned automatically. Prometheus retained 24 samples from before reboot and produced 15 after reboot, all with pending queue value one.
- Prometheus reloaded both Hermodr rule groups and 13 rules. Grafana returned a healthy database, the `hermodr-operations` dashboard retained all four rows, and both delivery rules remained provisioned.
- A post-reboot isolated restore reconciled schema version 2, all 18 table counts, and all 18 identifier-set fingerprints.
- A controlled receiver outage moved `hermodr_receiver_ready` from one to zero and the durable-ingest alert from absent to pending to firing. Restart returned readiness to one and the alert resolved.
- An append-only deployment audit event was successfully added to the persistent dashboard as an opaque audit-ID annotation. The same workflow supports configuration activation and credential rotation.

## Alert delivery finding

The generic contact-point delivery test reached the configured SMTP server but received an authentication rejection. A pre-existing Compose defect that blanked the SMTP host was corrected and the container now receives the protected configured host; the remaining credential rejection requires a valid authoritative SMTP secret. Alert collection, Prometheus evaluation, Grafana evaluation, and routing remain active, but human notification delivery is not yet proven.

## Remaining acceptance gate

Successful external notification delivery is the only unfinished M3 exit test. Real-device activation remains prohibited until a valid SMTP credential is synchronized from the authoritative secret store and a repeated Grafana contact-point test reports success.

Off-host backup replication and recovery-key custody also remain production constraints. The discovered off-host mount is read-only, and the local encryption passphrase resides on the application host; current archives provide tested local recovery but not host-loss recovery.
