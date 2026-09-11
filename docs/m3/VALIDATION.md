# M3 Operational Baseline Validation

**Validation date:** 2026-09-11
**Activation scope:** synthetic data only

## Repository evidence

The release gate builds the wheel, validates the pinned patched SQLite runtime, runs static/dependency/privacy/Markdown checks, and executes 67 unit and integration tests. Aggregate line coverage is 99.49% (3334/3351), strictly above the required 95%.

Tests cover encrypted backup creation and failure states, archive/digest/integrity/schema/table/identifier reconciliation, isolated restore status, durable metrics, processor heartbeat, CLI boundaries, systemd hardening, gateway privacy, alert families, and the four dashboard rows.

## Live evidence before full-host reboot

- Hardened migration, receiver, processor sentinel, metric-export timer, and backup timer units are enabled on the application host.
- The private readiness endpoint reports ready; the gateway can reach ingestion but cannot connect to operations.
- The TLS route accepted one zero-coordinate synthetic event and returned an opaque ingest ID. SQLite and reconstructed Prometheus metrics both report one pending job.
- Nginx configuration validates, request logs omit secrets and bodies, and public health/metrics requests return 404.
- Encrypted backup creation, verification, and isolated restore report success. Critical backup and database-integrity gauges equal one.
- Prometheus validates and loads 12 Hermodr recording/alert rules from persistent configuration.
- Grafana provisions the dashboard and two delivery bridge rules from persistent configuration; its database reports healthy.
- The gateway host rebooted and its boot-enabled nginx stack returned automatically with `nginx -t` successful.

## Alert delivery finding

The generic contact-point delivery test reached the configured SMTP server but received an authentication rejection. A pre-existing Compose defect that blanked the SMTP host was corrected and the container now receives the protected configured host; the remaining credential rejection requires a valid authoritative SMTP secret. Alert collection, Prometheus evaluation, Grafana evaluation, and routing remain active, but human notification delivery is not yet proven.

## Pending final evidence

The application-host reboot drill must still prove automatic service, metric, dashboard, alert-rule, encrypted-backup, and one-job queue recovery without sending a new event. Until that and successful external notification delivery are recorded, M3 remains in progress and real-device activation remains prohibited.
