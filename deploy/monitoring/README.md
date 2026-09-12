# Monitoring Integration

The checked-in files are additive artifacts for an existing persistent Prometheus and Grafana installation.

1. Mount `hermodr-recording-alerts.yml` under Prometheus's configured rule directory and validate it with `promtool check rules`.
2. Allow `hermodr_.*` through exactly one node-exporter textfile scrape. If a dedicated filtered job scrapes the same exporter as a general node job, drop `hermodr_.*` from the general job so gauges and alerts are not duplicated. Do not add subject, device, credential, request, or ingest identifiers as metric labels.
3. Give the Prometheus Grafana datasource the stable UID `hermodr-prometheus`.
4. Mount `hermodr-dashboard.json` in the Grafana dashboard provider directory and `hermodr-grafana-alerts.yml` in its alerting provisioning directory.
5. Configure Grafana's contact point and notification policy through a protected environment file. If that file already supplies `GF_SMTP_*`, do not redeclare those names with empty Compose substitutions because Compose `environment` values override `env_file` values. Do not pass the service secret file to Compose as an interpolation environment when values can contain dollar signs; use the service-level raw `env_file` support.
6. Prefer a boot-enabled host-local relay for unattended delivery. Give the container a stable hostname mapping to the host gateway, restrict relay permission to the deployment network, require STARTTLS, and retain hostname verification. When the relay uses a private or self-signed certificate, build Grafana with `grafana-mail-trust.Dockerfile` and supply its public certificate as `mail-relay.crt`; never set `GF_SMTP_SKIP_VERIFY=true` merely to make a delivery test pass.
7. Point the metrics-export unit at the node-exporter textfile directory with a host-local systemd override for `HERMODR_METRICS_TARGET`; similarly override `HERMODR_READY_URL` when the private operations port differs from its default. Keep host-specific paths out of source control.
8. Reload or recreate Prometheus and Grafana only after configuration validation. Bind-mounted files replaced atomically may require container recreation because an existing container can retain the old inode. Verify one current series per critical gauge, rule count, dashboard UID/row count, alert-rule count, contact-point API success, relay acceptance, and an empty mail queue.

`hermodr-annotate` accepts an opaque audit ID and one of `deployment`, `config_activate`, or `credential_change`. It reads Grafana URL and credentials from protected environment values and posts only the audit ID/action to the dashboard. Record the audit event in SQLite first; never invent an annotation without its durable audit row.
