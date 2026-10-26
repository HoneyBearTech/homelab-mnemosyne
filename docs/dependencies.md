# Dependencies

What the stack runs, how each piece is pinned and updated, and how vulnerabilities in them are handled.

| Dependency | Where | Pinned as | Updated by |
| --- | --- | --- | --- |
| PostgreSQL (`postgres`) | `compose.yaml` | tag and digest | hand, after Diun's alert ([upgrading.md](upgrading.md)) |
| MariaDB (`mariadb`) | `compose.yaml` | tag and digest | hand, after Diun's alert |
| postgres_exporter, mysqld_exporter, Diun | `compose.yaml` | tag and digest | Dependabot, auto-merged once the checks pass |
| The check and test tools | `requirements-dev.txt` | version and hash | Dependabot |
| GitHub Actions, CI images | `.github/workflows/`, `.gitlab-ci.yml` | commit SHA / digest | Dependabot (Actions); by hand (CI images) |

All are open source: PostgreSQL (PostgreSQL License), MariaDB (GPL-2.0), the exporters (Apache-2.0), Diun
(MIT).

## Choosing an engine version

- **PostgreSQL**: the newest major that every app on the server supports, on its newest minor release. The image
  is Debian-based (`-trixie`); the Debian release changes only with a major upgrade, and `diun/images.yml`'s
  pattern with it.
- **MariaDB**: the current long-term support line (11.8), on its newest patch. The image is Ubuntu-based
  (`-noble`).

## Vulnerabilities

The weekly scan (`.github/workflows/scan.yml`) scans every pinned image and posts the findings to code scanning.
For the exporters and Diun, fixes arrive through Dependabot. For the engines, a finding in the base image is
usually fixed by an upstream rebuild of the same tag, which Diun reports as "has been updated": take it as a
[rebuild](upgrading.md#a-rebuild-a-patch-or-a-minor-release). A finding in the engine itself is fixed by its next
minor release. A finding in a component the engines never use from the network (a helper binary in the image, say)
is recorded with the reason it doesn't apply.
