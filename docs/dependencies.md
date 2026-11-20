# Dependencies

What the stack runs, how each piece is pinned and updated, and how vulnerabilities in them are handled.

| Dependency | Where | Pinned as | Updated by |
| --- | --- | --- | --- |
| PostgreSQL (`postgres`) | `compose.yaml`, tag also in `diun/images.yml` | tag and digest | Renovate proposes, you merge at a quiet time ([upgrading.md](upgrading.md)) |
| MariaDB (`mariadb`) | `compose.yaml`, tag also in `diun/images.yml` | tag and digest | Renovate proposes, you merge at a quiet time |
| postgres_exporter, mysqld_exporter, Diun, DbGate | `compose.yaml` | tag and digest | Renovate, auto-merged once the checks pass |
| The check and test tools | `requirements-dev.in` → `requirements-dev.txt` | version and hash | Renovate, auto-merged once the checks pass |
| GitHub Actions | `.github/workflows/` | commit SHA (version in a comment) | Renovate, auto-merged once the checks pass |
| CI images | `.github/workflows/` (`docker run`), `.gitlab-ci.yml` | tag and digest | Renovate, auto-merged once the checks pass |

All are open source: PostgreSQL (PostgreSQL License), MariaDB (GPL-2.0), the exporters (Apache-2.0), Diun
(MIT), DbGate's community edition (GPL-3.0).

To update the pinned Python tools by hand, edit `requirements-dev.in` if needed and run
`pip-compile --generate-hashes --strip-extras requirements-dev.in`. Renovate does the same for its updates: it
re-locks `requirements-dev.txt` with that command (read from the file's header), so a tool's new dependencies and
all hashes come with the pull request.

## Tracking dependencies

- **Renovate** ([`renovate.json`](../renovate.json)) checks weekly (Mondays, 06:00 to 10:00 UTC) and opens a pull
  request for each new image version or digest, tool version and Action version. It reads `compose.yaml`,
  `diun/images.yml` (the engines' tags only), `requirements-dev.txt`, the workflows (Actions, and the images that
  `docker run` steps start), and `.gitlab-ci.yml`, and nothing else. Its commits are made through GitHub's API, so
  they're signed, and carry a DCO sign-off. Dependabot alerts stay on; Dependabot no longer opens version updates,
  and `.github/dependabot.yml` is gone. Each rule in `renovate.json` says why in its `description`.
- **Patch, minor and major updates merge automatically**, except the engines': Renovate turns on GitHub's
  auto-merge for each of its pull requests, so they're squash-merged once every required check has passed (CI with
  the Compose policy check and the smoke test, CodeQL, dependency review, DCO). Nothing skips a check, and a failing
  update stays open for the maintainer. Image rebuilds (a new digest under the same tag) merge the same way.
- **The engines never merge by themselves.** PostgreSQL's and MariaDB's pull requests (rebuilds, patches, minor
  versions) wait for the maintainer to merge them at a quiet time, since a new engine version restarts every app's
  database. Only a new major version of an engine is held back until you tick it on the Dependency Dashboard; a new
  MariaDB series within the same major (11.9, say) arrives as an ordinary engine pull request, never auto-merged, for
  you to merge or close ([upgrading.md](upgrading.md)). `scripts/check_watches.py` fails CI unless `renovate.json`
  keeps the engines' never-merge rule last; it catches the usual mistakes, not every setting, so a change to
  `renovate.json` still needs a careful review. Renovate moves
  the engines' tags in `diun/images.yml` in the same pull request as `compose.yaml`; Diun's entries carry no digest,
  so a rebuild changes only `compose.yaml`. Diun's Discord alerts stay.
- **A new version waits three days after its release** (`minimumReleaseAge`, where the registry reports a release
  date; a version whose registry reports none is proposed without the wait), so a release that is pulled or fixed
  within days doesn't reach the server. Fixes for vulnerability alerts skip the wait. An image rebuild skips it too:
  Docker Hub dates a rebuild by the tag's last push, so a tag rebuilt about weekly would never get through the
  Monday-only schedule, and rebuilds are mostly base-image security refreshes, still gated by the required checks.
  The tools in `requirements-dev.txt` move one at a time through ordinary updates and so wait too: Renovate's
  periodic refresh of the whole lock file, which would skip the wait, is switched off.
- **Some pins move together**: the CodeQL actions (`init`, `analyze`, `upload-sarif`) are grouped, so each set
  moves in one pull request.
- **Left to be bumped by hand**: Python's minor version (3.14, in `pyproject.toml`, the `setup-python` steps and the
  GitLab job image: Renovate proposes new 3.14 patch releases, not 3.15), and the smoke test's
  `runs-on: ubuntu-24.04` label (it matches the server's Ubuntu release). `dependabot/fetch-metadata` isn't updated
  either: only the idle `.github/workflows/dependabot-auto-merge.yml` uses it, and nothing triggers that workflow
  any more.
- **Renovate's pull requests run CI with the Docker Hub secret**, like any other pull request in the repository
  (Actions bumps included), so image pulls count against the maintainer's account; the smoke test logs out before
  any container starts.
- **A merge deploys.** The maintainer's server follows `main` with a pull agent, so every merge, the automatic ones
  included, reaches it within minutes. The nightly backup is behind a major update that migrates data.
- **Dependency review** blocks a pull request that adds or changes a Python or Actions dependency with a known
  vulnerability of moderate severity or higher, or a license outside the allowlist.

## Choosing an engine version

- **PostgreSQL**: the newest major that every app on the server supports, on its newest minor release. The image
  is Debian-based (`-trixie`); the Debian release changes only with a major upgrade, and `diun/images.yml`'s
  pattern with it.
- **MariaDB**: the current long-term support line (11.8), on its newest patch. The image is Ubuntu-based
  (`-noble`).

## Vulnerabilities

The weekly scan (`.github/workflows/scan.yml`) scans every pinned image and posts the findings to code scanning.
For the exporters, Diun and DbGate, fixes arrive through Renovate. For the engines, a finding in the base image is
usually fixed by an upstream rebuild of the same tag, which Renovate proposes and Diun reports as "has been updated":
take it as a [rebuild](upgrading.md#a-rebuild-a-patch-or-a-minor-release). A finding in the engine itself is fixed by
its next minor release. A finding in a component the engines never use from the network (a helper binary in the
image, say) is recorded with the reason it doesn't apply.

### Current findings

Triaged on 2026-11-10. Every pinned image was scanned again with the weekly scan's settings (Trivy 0.75.0,
`linux/amd64`, HIGH and CRITICAL, fixed only), and where a verdict depended on what an image contains or runs, the
pinned image was inspected (its entry scripts and binaries) rather than assumed. Code scanning shows 98 open alerts;
it opens one alert per finding and file, and `gosu` is the same file in both engine images, so the scans find more:
**123 findings, 4 of them critical** (one CVE or advisory in one image). Every image is already on its newest
upstream release, so no bump closes any of them; the alerts stay open and each closes by itself when upstream ships
the fix. None was dismissed.

| Image | Findings (critical) | Verdict | Action |
| --- | --- | --- | --- |
| PostgreSQL `18.6-trixie` | 30 (1) | **Not reachable**, except zlib. 26 are the Go standard library in `gosu` 1.24.6, which the entrypoint runs only when the container starts as root, to drop to the `postgres` user; this stack runs it as `PUID`:`PGID`, so `gosu` never runs. 2 are zlib (CVE-2026-85091 and CVE-2026-76844): only the operator's own dumps pass through it, never data from the network. 2 are `apt`, which nothing runs | **Wait for upstream.** `gosu` 1.20 (2026-10-25) is out; the image still ships 1.19. The tag has been rebuilt since the pin; the rebuild closes the `apt` findings only, so it isn't worth an engine restart by itself ([upgrading.md](upgrading.md#a-rebuild-a-patch-or-a-minor-release)) |
| MariaDB `11.8.9-noble` | 28 (1) | **Not reachable.** 26 are the same `gosu` (it runs `mariadbd` as `mysql` only when started as root, which this stack never does); 2 are `apt` and `libapt-pkg`, which nothing runs | **Wait for upstream.** The tag has been rebuilt since the pin; the rebuild closes none of them |
| Diun `4.33.1` | 33 (3) | **Not reachable.** Diun is configured with the file provider and the Discord notifier only. The 3 critical and 7 high findings are `amqp091-go`, the RabbitMQ notifier's client, which isn't configured; `x/crypto/ssh` (10), `x/mod/sumdb` (2) and `grpc` (3) belong to features this configuration never uses. The remaining `x/net` and `x/text` findings (8) are in the HTTP client, which only talks to the registries and Discord: a hostile response could at most make it fail a check, and it has no listening port | **Wait for upstream.** 4.33.1 is the newest release (2026-10-24); Renovate proposes the next |
| postgres_exporter `v0.20.1` | 19 | **Reachable from the stack's network, as denial of service only.** Go 1.26.4's standard library and `x/net` in the process that serves `/metrics` on the servers' VLAN (unauthenticated, like the other exporters). Nothing it serves is data, and the unit restarts by itself | **Wait for upstream.** The newest release (2026-07-08) predates the fixes; Renovate proposes the next |
| mysqld_exporter `v0.21.0` | 1 | The same kind: `x/net/html` (CVE-2026-78661); a library the exporter links; it serves metrics only and fetches no web pages | **Wait for upstream** |
| DbGate `7.3.4` | 12 | **Not reachable.** 10 are packages inside npm's own `node_modules` (`brace-expansion`, `pacote`, `picomatch`, `sigstore`, `ip-address`): npm is never run, since the container starts `node` on a read-only filesystem. 2 are `apt` and `libapt-pkg`, which nothing runs | **Wait for upstream** |

**Every critical finding:**

| Component (image) | CVE | Fixed in | Verdict |
| --- | --- | --- | --- |
| `amqp091-go` v1.11.0 (Diun) | CVE-2026-77405, CVE-2026-77408, CVE-2026-77411 (TLS minimum version, silent truncation, frame desynchronisation) | 1.13.0 | **Doesn't apply.** The code is in the binary, but nothing here configures a RabbitMQ notifier, so it never runs |
| Go standard library 1.24.6 (`gosu`, both engine images) | CVE-2025-68121 (`crypto/tls` session resumption) | Go 1.24.13 | **Doesn't apply.** `gosu` doesn't use TLS, and doesn't run when the container starts as a non-root user |

The engines' rebuilds are the owner's call (merging one restarts every app's database); this section changes
nothing in `compose.yaml`.
