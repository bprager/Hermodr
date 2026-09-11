# Monitoring Integration

The checked-in files are additive artifacts for an existing persistent Prometheus and Grafana installation.

1. Mount `hermodr-recording-alerts.yml` under Prometheus's configured rule directory and validate it with `promtool check rules`.
2. Allow `hermodr_.*` through the node-exporter textfile scrape metric relabeling. Do not add subject, device, credential, request, or ingest identifiers as metric labels.
3. Give the Prometheus Grafana datasource the stable UID `hermodr-prometheus`.
4. Mount `hermodr-dashboard.json` in the Grafana dashboard provider directory and `hermodr-grafana-alerts.yml` in its alerting provisioning directory.
5. Configure Grafana's contact point and notification policy through a protected environment file. If that file already supplies `GF_SMTP_*`, do not redeclare those names with empty Compose substitutions because Compose `environment` values override `env_file` values.
6. Point the metrics-export unit at the node-exporter textfile directory with a host-local systemd override for `HERMODR_METRICS_TARGET`; similarly override `HERMODR_READY_URL` when the private operations port differs from its default. Keep host-specific paths out of source control.
7. Reload Prometheus and recreate Grafana only after configuration validation. Verify rule count, dashboard UID/row count, alert-rule count, and a real contact-point test.

`hermodr-annotate` accepts an opaque audit ID and one of `deployment`, `config_activate`, or `credential_change`. It reads Grafana URL and credentials from protected environment values and posts only the audit ID/action to the dashboard. Record the audit event in SQLite first; never invent an annotation without its durable audit row.
