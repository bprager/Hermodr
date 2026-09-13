# M3 Operational Baseline Validation

**Validation date:** 2026-09-11
**Activation scope:** synthetic data only

This is point-in-time M3 evidence. M8 subsequently enrolled the first physical iPhone under controlled commissioning; the synthetic-only activation boundary below describes the M3 exit state.

## Repository evidence

The release gate builds the wheel, validates the pinned patched SQLite runtime, runs static/dependency/privacy/Markdown checks, and executes 68 unit and integration tests. Aggregate line coverage is 99.39% (3449/3470), strictly above the required 95%.

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
- A subsequent host reboot changed the boot ID again to `0e04ce12-1c72-4498-a9a6-5bd797c887be`; all five enabled Hermodr units/timers resumed, and both long-running services remained at zero restart attempts after boot.
- After boot, receiver, processor sentinel, metrics timer, and backup timer were enabled and active; readiness returned `ready` automatically.
- Without a new event, raw-event and pending-job counts remained exactly one, all three backup stages remained successful, and database integrity remained `ok`.
- The metrics bridge returned automatically. Prometheus retained 24 samples from before reboot and produced 15 after reboot, all with pending queue value one.
- Across the subsequent reboot, Prometheus retained 15 pre-boot and 26 post-boot pending-queue samples, again with the only observed value equal to one.
- Prometheus reloaded both Hermodr rule groups and 13 rules. Grafana returned a healthy database, the `hermodr-operations` dashboard retained all four rows, and both delivery rules remained provisioned.
- The dedicated filtered node-exporter scrape is the sole current source for `hermodr_*`; the general node scrape drops that prefix, preventing duplicate gauges and notifications. Prometheus's file-discovery target directory is mounted and produces no missing-watch errors.
- A post-reboot isolated restore reconciled schema version 2, all 18 table counts, and all 18 identifier-set fingerprints.
- A controlled receiver outage moved `hermodr_receiver_ready` from one to zero and the durable-ingest alert from absent to pending to firing. Restart returned readiness to one and the alert resolved.
- An append-only deployment audit event was successfully added to the persistent dashboard as an opaque audit-ID annotation. The same workflow supports configuration activation and credential rotation.

## Alert delivery evidence

The supplied age identity matched the configured SOPS recipient and decrypted the authoritative SMTP value. Its value was byte-for-byte identical to the active credential, proving the original upstream authentication rejection was not a synchronization defect. The delivery path was changed to Odin's boot-enabled local Postfix relay, with the stable `odin` hostname mapped to the container host gateway. Grafana uses opportunistic STARTTLS with verification enabled and a pinned public relay certificate; no SMTP credential is required on the relay-trusted deployment network.

A Grafana contact-point test returned receiver status `ok` with zero errors. Postfix logged STARTTLS, accepted one recipient, received upstream `250 OK`, removed the message, and reported an empty queue. The protected live environment and age identity have mode `0600`; the encrypted SOPS source of truth now records the local-relay settings for repeatable deployment.

## Milestone result and remaining constraints

All M3 exit tests pass for the unattended synthetic-only baseline. Real-device activation remains prohibited because it belongs to later commissioning and policy gates, not because of an unfinished M3 test.

The `saga` RAID-5 destination was subsequently approved and its existing boot-managed NFSv4 mount verified writable. The backup workflow now atomically transfers the encrypted archive and repeats verification plus isolated restoration from the off-host copy. Bernd is the designated recovery-key custodian. A 2026-09-12 drill retrieved the Hermóðr-specific age identity from Bitwarden, decrypted the committed SOPS recovery artifact, restored a Saga archive, and removed the identity and temporary plaintext from Odin.

The M3 processor is deliberately a heartbeat sentinel and does not claim, normalize, retry, or dead-letter queued jobs; that is M4 scope. SMTP upstream acceptance does not prove inbox presentation, and the current notification route has no independently monitored secondary channel. Relay certificate rotation requires rebuilding the pinned Grafana trust layer before the certificate's 2034 expiry.
