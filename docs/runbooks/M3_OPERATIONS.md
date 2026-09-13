# M3 Operations Runbook

Use a unique run ID for every intervention and retain command output in the restricted incident record. Never paste credentials, payloads, coordinates, direct identifiers, or database content into tickets or chat.

## Restart and reboot recovery

1. Check the migration, receiver, processor, metrics timer, backup timer, gateway, Prometheus, and Grafana units.
2. Check receiver readiness on loopback and confirm the public gateway exposes neither health nor metrics.
3. Confirm `hermodr_metrics_bridge_up == 1`, database integrity equals one, processor heartbeat is current, and durable queue counts match SQLite.
4. Restart one component at a time. For a host reboot, record boot ID, queue count, newest restore-tested backup timestamp, and dashboard UID before reboot; compare them after automatic recovery without sending a new event.
5. Escalate if any acknowledged ingest ID disappears, a nonzero queue fails to drain after processor recovery, metrics do not resume, or alert evaluation is absent.

## Credential rotation

1. If this is a new physical device, enroll its internal generic identifier and exact two-character OwnTracks tracker ID through the audited command boundary; never edit the device table directly:

   ```shell
   hermodr --config /etc/hermodr/config.json admin device-enroll \
     --subject-id SUBJECT --device-id DEVICE --source-tid TT \
     --reason-code commissioning --run-id RUN
   ```

2. Create a new `0600` secret outside source control. Stage it through the audited command boundary; never edit the credential table directly:

   ```shell
   hermodr --config /etc/hermodr/config.json admin credential-stage \
     --subject-id SUBJECT --device-id DEVICE --key-id NEW_KEY \
     --secret-ref /protected/path --reason-code rotation --run-id RUN
   ```

3. Run `receiver --check`, test the new credential through TLS, and verify the old credential still works during overlap.
4. Revoke the old credential only after the new path succeeds; the command refuses to remove the final usable credential:

   ```shell
   hermodr --config /etc/hermodr/config.json admin credential-revoke \
     --key-id OLD_KEY --reason-code rotation_complete --run-id RUN
   ```
5. Prove old rejection and new acceptance, then delete the old secret file. If the old credential belonged to a retired placeholder device, disable that device only after revocation:

   ```shell
   hermodr --config /etc/hermodr/config.json admin device-disable \
     --subject-id SUBJECT --device-id OLD_DEVICE \
     --reason-code commissioning_complete --run-id RUN
   ```

   The command refuses to disable a device with a time-usable credential.
6. Record the opaque key/device ID, run ID, reason, result, build, and configuration fingerprint in the restricted audit record. Never record the secret.

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
2. Confirm the host-local relay is enabled and active, Grafana resolves its stable relay hostname to the host gateway, STARTTLS succeeds, and the relay trusts only the intended deployment network.
3. If certificate verification fails, compare the live relay certificate fingerprint and hostname with the pinned public certificate. Replace and rebuild the trust layer only after authenticating the new certificate; never disable verification as a shortcut.
4. If an authenticated upstream relay rejects credentials, keep alert evaluation active, mark delivery degraded, and rotate the protected credential from its authoritative secret store.
5. Repeat until Grafana reports success, the relay records upstream acceptance, its queue is empty, and receipt is verified out of band.
