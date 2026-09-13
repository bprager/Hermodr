# OwnTracks Configuration on the iPhone

**Scope:** Hermóðr version 1 commissioning
**Privacy rule:** never commit or paste a real credential, hostname, location, waypoint, screenshot, or device identifier into this repository

This procedure configures OwnTracks as an HTTP client of Hermóðr. The field order below was verified with OwnTracks iOS 26.2.2; screen names can move between releases. Every all-caps value is a placeholder, including `APPROVED_HOST`; never enter a placeholder literally.

## Values the operator supplies

Obtain these values over the approved private channel immediately before setup:

| App value | Hermóðr value | Example used here |
| --- | --- | --- |
| URL | Approved public TLS route plus the exact ingest path | `https://APPROVED_HOST/v1/owntracks` |
| Username | Opaque staged credential `key_id` | `KEY_ID` |
| Password | Contents of that credential's protected secret file | `PASSWORD` |
| Device ID/name | Stable, generic OwnTracks device label | `DEVICE_NAME` |
| Tracker ID | Exact two-character `source_tid` registered for the device | `TT` |

The password is not the SOPS/age recovery secret or the backup passphrase. Do not put credentials in the URL, Notes, a screenshot, an `.otrc` file, or the repository.

## 1. Prepare iOS

1. Install or update OwnTracks from the App Store and open it once.
2. Accept the location prompt. Then open **Settings > Privacy & Security > Location Services > OwnTracks** and select **Always**; leave **Precise Location** on. Apple defines **Always** as permitting background access and Precise Location as the app receiving a specific rather than approximate location ([Apple Location Services](https://support.apple.com/en-gb/guide/iphone/iph3dd5f9be/ios)).
3. Open **Settings > General > Background App Refresh** and enable it for OwnTracks. Apple notes that force-closing an app can prevent background activity until it is opened again ([Apple Background App Refresh](https://support.apple.com/en-ie/118408)). Do not routinely swipe OwnTracks away.
4. For the commissioning exercises, turn off Low Power Mode and Low Data Mode. Both can disable Background App Refresh ([Apple Low Power Mode](https://support.apple.com/en-gb/101604), [Apple Low Data Mode](https://support.apple.com/en-gb/102433)). They may be tested later as explicit degraded conditions.

These settings intentionally allow sensitive background location collection. Stop and use the rollback procedure below if this is not the desired behavior.

## 2. Configure the HTTP connection

1. In OwnTracks, tap the information (`i`) control and open **Settings**.
2. Set **TrackerID** to the exact registered two-character `TT`. Replace the generated **DeviceID** UUID with the assigned stable generic `DEVICE_NAME`.
3. Leave MQTT-only **Host** and **Port** unchanged, **Websockets** off, and **Proto** at `4`.
4. Leave **TLS** on. Set **UserID** to `KEY_ID`, turn **Authentication** on, and enter the protected credential as **Password**.
5. Leave **Secret Encryption Key** blank. Hermóðr terminates TLS but does not implement OwnTracks payload encryption.
6. Set **URL** to exactly `https://APPROVED_HOST/v1/owntracks`. Do not add a trailing slash, query string, username, or password. This URL configures HTTP delivery; the MQTT Host and Port are not the Hermóðr endpoint.
7. Leave **Expert Mode** fields unchanged. Do not add custom headers, remote commands, friends, or sharing for version 1.
8. The `https://` URL must validate through the iPhone's normal TLS trust. Never enable invalid-certificate acceptance or use plain HTTP.

OwnTracks HTTP mode POSTs its JSON messages to the configured URL, supports Basic authentication, treats a `2xx` response as delivered, and queues a message when the endpoint is unreachable. The expected Hermóðr success response is `200` with `[]` ([OwnTracks HTTP](https://owntracks.org/booklet/tech/http/)). The tracker ID is required for HTTP location messages, and the device status reports whether background refresh is available ([OwnTracks JSON](https://owntracks.org/booklet/tech/json/)).

Manual entry is deliberate. OwnTracks supports `.otrc` imports, but those files commonly contain the password. Since iOS app version 26.2.2, external configuration import is disabled by default and must be explicitly enabled with a security warning ([OwnTracks security](https://owntracks.org/booklet/features/security/), [OwnTracks remote configuration](https://owntracks.org/booklet/features/remoteconfig/)). Hermóðr does not require that feature, so leave it disabled.

## 3. Make the first controlled publish

1. Select **Manual** monitoring mode.
2. Select **Publish location now** once while the app is in the foreground.
3. Tell the operator the publish time and any visible error or queue state, but do not send coordinates or a screenshot. OwnTracks may show no success banner or queue count; server-side receipt is authoritative.
4. The operator confirms one accepted event, processing convergence, current aggregate freshness, no pending quarantine, and no sensitive fields in logs.

Do not repeatedly publish while diagnosing a failure. Record only time, HTTP response class, message type, trigger, queue count, and bounded Hermóðr evidence IDs.

## 4. Exercise background modes

After the manual publish is accepted:

1. Select **Significant** mode for the normal commissioning baseline. OwnTracks describes this as lower-power monitoring, typically triggered after a significant movement rather than continuous GPS.
2. Lock the iPhone and complete one ordinary movement large enough to generate an update. Record battery percentage before and after, elapsed time, count of received updates, and maximum delivery delay—never the route or coordinates.
3. Use **Move** mode only for a short, planned route. Its displacement/interval updates consume considerably more battery; OwnTracks documents defaults of 100 metres and 300 seconds.
4. Return to **Significant** mode after the controlled route. **Quiet** disables region events; **Manual** still permits region monitoring, so neither is the normal accepted configuration without explicit approval.

OwnTracks documents the iOS monitoring modes, their battery tradeoffs, and their approximate trigger behavior in [Location](https://owntracks.org/booklet/features/location/) and [iOS](https://owntracks.org/booklet/features/ios/).

## 5. Create one commissioning region

This step requires the owner's choice because the centre, radius, and name disclose a real place.

1. Long-press the map at the chosen location, edit the resulting region, and use a non-descriptive label during the test.
2. Choose a radius large enough to avoid GPS-edge oscillation. Record the radius as acceptance evidence only if the owner approves it.
3. Cross the boundary once in each direction and confirm one enter and one leave transition.
4. Delete the temporary region unless the owner explicitly approves it as a retained known place.

OwnTracks supports circular regions and publishes enter/leave transitions; its iOS waypoint workflow begins with a long press on the map ([OwnTracks waypoints](https://owntracks.org/booklet/features/waypoints/)).

## 6. Test delayed delivery

1. Note the current time and disconnect both Wi-Fi and cellular data without disabling Location Services.
2. Select **Publish location now** once. Record its time and any visible state; OwnTracks may show neither an immediate error nor a queue count.
3. Wait a recorded, bounded interval, restore connectivity, and leave OwnTracks running.
4. Confirm the queued message clears and ask the operator to verify capture time precedes receipt time, processing converges, order is deterministic, and no duplicate canonical effects appear.
5. Repeat only if the first result is ambiguous. OwnTracks retries foreground failures with increasing delays and may receive much less frequent background execution from iOS ([OwnTracks iOS](https://owntracks.org/booklet/features/ios/)).

## 7. Send one device-status report

1. With connectivity restored, use **Map > Info (`i`) > Status Info > Send Debug Status** once.
2. Tell the operator only the send time and visible result. Do not paste the payload or take a screenshot: it has no coordinates but contains a vendor UUID plus device, OS, locale, permission, and capability metadata.
3. The operator confirms a `200`, a timestamp-less `_type=status` shape, processing convergence, and no leakage into general logs or metrics. OwnTracks iOS 26.2.2 omits `tst` from this report; Hermóðr preserves null raw capture time and uses receipt time only as a labelled normalization fallback.

A permanent `4xx` discards this status object. Stop after one failure; repair and deploy the server contract, then explicitly send a fresh status report.

## 8. Finish credential cutover

Once the new credential has succeeded through TLS and all expected message types are accepted, the operator revokes the bootstrap credential with the audited `credential-revoke` command and disables its placeholder device with `device-disable`. The old credential must then receive a generic authentication failure while the iPhone continues to succeed. Never restore the old secret to troubleshoot a client setting.

## Troubleshooting

| Symptom | Safe check |
| --- | --- |
| TLS or certificate error | URL begins with `https://`; hostname is exact; invalid-certificate acceptance remains off; phone clock is correct |
| `401` | Re-enter the opaque username and password; do not send either value in chat or a screenshot |
| `400` for **Send Debug Status** | Stop; the operator checks timestamp-less status compatibility, deploys a repair, and requests one fresh report |
| `413` | Remove unapproved extended data or batching; do not increase the gateway limit during commissioning |
| `415` | Remove custom content-type/header settings |
| `422` or identity mismatch | Verify the URL, tracker ID, supported OwnTracks message type, and phone clock |
| `503` or timeout | Stop repeated publishing; operator checks readiness, storage, and gateway state; leave the queued message intact for the recovery test |
| Foreground succeeds, background does not | Recheck **Always**, **Precise Location**, Background App Refresh, Low Power/Data modes, and whether OwnTracks was force-closed |
| Duplicate display | Preserve the queued state and time evidence; the operator checks Hermóðr idempotency rather than deleting records |

## Rollback and emergency stop

For a reversible client-side rollback, select **Quiet**, remove the Hermóðr password from OwnTracks, and disable OwnTracks background location permission. Tell the operator to revoke the credential. For an emergency server-side stop, the operator follows the endpoint-shutdown runbook; the device may retain queued messages, so do not re-enable the endpoint until their handling is explicitly decided.

The setup is accepted only after the owner approves the monitoring mode, observed battery behavior, event frequency, region configuration, and derived thresholds in the M8 acceptance record.
