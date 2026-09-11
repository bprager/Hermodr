# M0 Deployment Inventory

**Date:** 2026-09-10
**Method:** read-only local inspection and existing non-interactive gateway SSH access

This inventory records only operational facts needed for architectural decisions. Account names, addresses, keys, configuration contents, mount identifiers, and payload data are omitted.

## Application Environment

| Area | Observed fact | Confidence or limitation |
| --- | --- | --- |
| Platform | Linux x86-64; ext4 workspace on an LVM logical volume | Verified inside the restricted workspace |
| Runtime | Python 3.13.7 is installed; Go is not installed | Verified in workspace PATH |
| SQLite | CLI and Python both report SQLite 3.46.1 | Verified; unsafe for planned WAL concurrency per ADR 0002 |
| Service manager | systemd 259 tools are installed | Live host manager unavailable inside the restricted execution environment |
| Containers | Docker CLI 28.1.1 is installed | Daemon/boot policy not established |
| Time | Workspace timezone is configured; live host synchronization was not observable | Must verify on live host in M3 |
| Storage encryption | LVM and ext4 are visible; no encryption layer was proven | Do not infer encryption from LVM |
| Service identities | Two non-system numeric identities were observed | Names deliberately not recorded; dedicated service identities do not yet exist |
| Backup | No Hermóðr backup exists because there is no service data | Backup mechanism and target remain a production gate |
| Monitoring | No collector/dashboard/alert process was visible in the workspace | Workspace isolation may hide host services |

Non-interactive SSH to the application-host alias failed because its referenced key was unavailable. No credential prompt or privilege request was attempted.

## Gateway Environment

| Area | Observed fact | Confidence or limitation |
| --- | --- | --- |
| Platform | Linux x86-64 with systemd as PID 1 | Verified over existing non-interactive SSH |
| Gateway | A dedicated gateway unit is enabled and active | Configuration/body logs were not inspected |
| Boot behavior | Gateway and node-exporter units are enabled | Verified with systemd |
| Time | NTP is enabled and synchronized; timezone matches the application plan | Verified with systemd time properties |
| Storage | Root is ext4; no active crypttab entry was observed | Absence of a crypttab entry does not prove unencrypted physical storage |
| Monitoring | Node exporter is enabled and active; no Prometheus, dashboard, or alert containers were observed | Collector location remains unknown |
| Backup | No application backup timer or common backup CLI was observed | Package-database backup is not an application-data backup |

## Decision Impact

- Use Python and systemd (ADRs 0001 and 0003).
- Treat storage encryption, monitoring persistence, backup target/key recovery, and live application-host boot ordering as unverified production prerequisites.
- Upgrade or bundle a patched SQLite before any WAL-based multi-process production test.
- Do not deploy or modify either host during M0.

## Reproducible Follow-up Checks

Run these read-only checks from an authorized host session during M3:

```shell
python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'
systemctl is-enabled hermodr-receiver hermodr-processor
systemctl is-active hermodr-receiver hermodr-processor
timedatectl show -p NTP -p NTPSynchronized -p Timezone
findmnt -no FSTYPE,OPTIONS /path/to/hermodr-data
```

Encryption, monitoring retention, and backup recovery require their own provider-specific evidence; filesystem type and the existence of a backup file are insufficient.
