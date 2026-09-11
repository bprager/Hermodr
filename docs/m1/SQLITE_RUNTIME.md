# Approved SQLite Runtime Supply

**Status:** Available and verified
**Pinned release:** SQLite 3.53.4
**Verified:** 2026-09-10

## Resolution

The operating-system package remains SQLite 3.46.1 and is not used for production Hermóðr WAL access. Hermóðr instead builds an isolated shared library from SQLite's [official 3.53.4 archive](https://www.sqlite.org/download.html). This release is newer than the 3.51.3 fix boundary and carries the fix described in SQLite's [WAL-reset documentation](https://www.sqlite.org/wal.html#the_wal_reset_bug) and [release history](https://www.sqlite.org/changes.html).

The immutable supply manifest is `supply-chain/sqlite-runtime.json`. It pins:

- the official HTTPS source URL;
- archive SHA3-256 `454e45f61c6bd75b7420e7190732dea03ce6639c63ada47bbc592f67fc340338`;
- SQLite source ID ending `bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc`;
- compile and configure flags;
- public-domain license classification.

`tools.sqlite_runtime` downloads before building, rejects a checksum mismatch or unsafe archive member, builds into a versioned private prefix, and probes the result in a new Python process. It never replaces the system library.

## Verified capabilities

The local target build and CI require all of these facts:

| Property | Required result |
| --- | --- |
| SQLite version | `3.53.4` exactly |
| Official source ID | Exact manifest match |
| Python thread-safety mode | Nonzero |
| JSON functions | Available |
| Trusted schema default | Off |
| Secure-delete default | On |
| Extension API compatibility | Compiled for Python ABI compatibility |
| Extension loading default | Off, probed before acceptance; never enabled by the application |
| Python production startup guard | Accepted |
| Migration from empty database | Successful |
| Full application test suite | Passed using the private library |

The private build retains SQLite's extension API because some Python distributions link `_sqlite3` against those symbols. SQLite keeps extension loading disabled by default, and Hermóðr never enables it. The private build uses the historical `libsqlite3.so.0` SONAME expected by the existing Python extension. The service launcher must set both an exact `LD_PRELOAD` and a private-first `LD_LIBRARY_PATH` before Python starts. The explicit preload also works with Python distributions whose embedded runtime search path would otherwise win. Changing either value after importing `sqlite3` is too late. M3 systemd units will use the root-owned versioned deployment prefix and run the verifier as a startup prerequisite.

## Commands

```shell
make sqlite-runtime
make sqlite-runtime-check
make sqlite-validated-check
```

The default development prefix is `.runtime/sqlite-3.53.4`, which is ignored by Git. A deployed build belongs in a persistent, root-owned versioned release directory. Re-running the verifier after reboot proves the loader still resolves the approved build. Upgrading SQLite requires a new manifest, source-ID allowlist entry, validation evidence, and changelog entry.
