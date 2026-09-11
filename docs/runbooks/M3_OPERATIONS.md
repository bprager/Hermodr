# M3 Operations Runbook

Use a unique run ID for every intervention and retain command output in the restricted incident record. Never paste credentials, payloads, coordinates, direct identifiers, or database content into tickets or chat.

## Restart and reboot recovery

1. Check the migration, receiver, processor, metrics timer, backup timer, gateway, Prometheus, and Grafana units.
2. Check receiver readiness on loopback and confirm the public gateway exposes neither health nor metrics.
3. Confirm `hermodr_metrics_bridge_up == 1`, database integrity equals one, processor heartbeat is current, and durable queue counts match SQLite.
4. Restart one component at a time. For a host reboot, record boot ID, queue count, newest restore-tested backup timestamp, and dashboard UID before reboot; compare them after automatic recovery without sending a new event.
5. Escalate if the queue count decreases before M4, any acknowledged ingest ID disappears, metrics do not resume, or alert evaluation is absent.

## Credential rotation

1. Create a new `0600` secret outside source control and add a new credential row with a bounded overlap interval.
2. Run `receiver --check`, test the new credential through TLS using a synthetic zero-coordinate event, and verify the old credential still works during overlap.
3. Expire the old database record, restart the receiver only if its file reference changed, prove old rejection and new acceptance, then delete the old secret.
4. Record the opaque key ID, run ID, reason, result, build, and configuration fingerprint in the restricted audit record. Never record the secret.

## Storage pressure or WAL growth

1. Stop synthetic probes and check filesystem-free and database/WAL gauges.
2. Preserve the database and WAL together. Do not copy or delete a live WAL independently.
3. Run a passive checkpoint assessment, free unrelated recoverable storage, then take and restore-test an encrypted backup.
4. Restart only after readiness passes. Do not weaken `synchronous=FULL` or the disk floor during an incident.

## Suspected corruption

1. Stop the receiver and processor; keep restricted files unchanged.
2. Copy the database, WAL, and shared-memory files into restricted evidence storage.
3. Run `PRAGMA integrity_check` on an isolated copy. Never attempt repair on the only copy.
4. If invalid, follow the restore procedure and keep corrupt evidence until incident review permits deletion.

## Backup and isolated restore

1. Run `hermodr admin backup-create` with a new archive path and protected passphrase file.
2. Run `backup-verify`, then `restore-test`, against that same archive.
3. Require success for decryption, SHA-256, integrity, schema, table counts, and every identifier-set fingerprint.
4. For disaster recovery, stop writers, preserve current files, decrypt and verify into a separate directory, obtain explicit restoration authority, then atomically install the verified database with service ownership. Never point the restore test at the live path.

## No-report alert

1. Confirm receiver readiness, gateway reachability, and last real receipt/capture ages.
2. Check aggregate device/subject state without exposing an identity in metrics or general logs.
3. Treat client power, permissions, connectivity, and upload delay as unknown until checked through the restricted diagnostic path.
4. Do not generate a real-location event merely to clear the alert; synthetic probes are distinct.

## Emergency endpoint shutdown

1. Stop and disable the receiver to terminate acceptance, then remove or disable only the gateway location include and validate/reload nginx.
2. Confirm the public route is unavailable and operations remains unreachable from the gateway.
3. Leave database, backups, monitoring history, and audit evidence intact.
4. Re-enable only after the incident owner approves and the restart checklist passes.

## Notification delivery failure

1. Run the Grafana contact-point test and retain only status/error class, not recipient details.
2. If SMTP rejects authentication, keep alert evaluation active, mark delivery degraded, and rotate the protected SMTP credential from its authoritative secret store.
3. Repeat until the integration reports success and verify receipt out of band.
