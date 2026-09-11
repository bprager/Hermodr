# M1 Dependency and License Report

**Verified:** 2026-09-10

| Scope | Direct third-party packages | Transitive third-party packages |
| --- | ---: | ---: |
| Runtime | 0 | 0 |
| Build backend | 0 | 0 |
| Test and static-analysis gate | 0 | 0 |

Hermóðr M1 uses Python 3.13 standard-library modules only. `pyproject.toml` declares an empty runtime dependency list and an empty build-system requirement list. The checked-in build backend creates a standards-compliant wheel without fetching tools or packages.

`make dependency-check` fails if the declared dependency list or the standard-library-only license policy changes. The AST static-analysis gate also fails on an import whose top-level module is neither part of Python's reported standard library nor this repository. Adding a third-party dependency therefore requires an explicit manifest change, license review, locked version strategy, and update to this report.

The Python runtime is governed by the Python Software Foundation License. Runtime installation and operating-system component license inventory remain deployment evidence for M3; this report makes no claim about packages installed on a host outside the release artifact.
