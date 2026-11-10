# Assurance case

Why homelab-mnemosyne meets its [security requirements](security.md): the threat model, the trust boundaries, the
secure design principles it follows, and how common weaknesses are countered.

## Threat model

| Asset | Threat | Countered by |
| --- | --- | --- |
| Every app's data | One app (or whoever takes it over) reading or changing another's | One login per app; `CONNECT` on a database revoked from `PUBLIC` and granted to its owner only (PostgreSQL); grants per database (MariaDB); the smoke test proves each app reaches its own databases and no other app's |
| The engines | An administrator login from the network | `pg_hba.conf` rejects `postgres` for every network address; MariaDB's `root` exists for `localhost` only; the smoke test proves both |
| The engines | A login from anywhere on the LAN | App logins only from `DB_CLIENT_SUBNET`, the exporters' and `dbviewer`'s only from `STACK_SUBNET`, everything else rejected |
| Passwords | Sniffed on the network | SCRAM-SHA-256 (PostgreSQL); TLS 1.2 or later offered by both engines |
| Passwords | Leaked through a process list, a log, the repository or a backup | SQL with passwords goes to the engine's client on stdin, never as arguments; secrets are files `0600` in `0700` folders passed as Docker secrets; no secret in `compose.yaml`, `.env` or an example file; gitleaks over the history in CI, push protection; dumps written `0700`/`0600` and encrypted with age before they leave the host |
| Every app's data | Read through the web GUI | DbGate answers on `127.0.0.1` (or one address a `DOCKER-USER` rule limits to the reverse proxy), holds no password, and logs in as `dbviewer`, which has `CONNECT` and no right to read a row; the smoke test proves it sees structure and no data on both engines |
| Every app's data | An engine upgraded under the apps without warning | Engines pinned by digest, ignored by Dependabot, upgraded by hand after Diun's alert; `scripts/check_watches.py` fails CI if an engine isn't watched |
| The host | A compromised or malicious image | Digest pins; versions change only by reviewed pull request; no privileged, capability, host-namespace, device or Docker-socket access, enforced by `scripts/check_compose.py` in CI and before every release; weekly vulnerability scan of every image |
| The data | Lost: a node, a disk, a bad upgrade or migration | ZFS replication and HA to a second node; nightly dumps copied off the host; weekly whole-VM backups; a backup before every engine upgrade; restores exercised by the CI smoke test |
| The data | A crafted or wrong backup overwriting live data | `restore.sh` verifies `SHA256SUMS` first, refuses to overwrite a database without `--replace`, and never restores the stack's own accounts |
| `main` | A bad change deploying by itself | The required checks (policy, watches, smoke test) pass before any merge; the pull agent only fast-forwards; engine changes are made and merged by the owner; rollback is a revert pull request |
| The release | Tampered release files | Keyless-signed `SHA256SUMS`, SLSA provenance, signed tags ([verifying-releases.md](verifying-releases.md)) |
| The CI pipeline | Untrusted pull request input running with credentials | `pull_request` only, read-only token by default, untrusted values only via `env:`, actions pinned by SHA, the Docker Hub token logged out before any image under test starts |
| Operator privacy | Hostnames, addresses, paths or webhook URLs in the public repository | Placeholders only; reviewed in every pull request; gitleaks |

Attackers considered: another app on the LAN or a compromised one; someone on the LAN with no login; a compromised
upstream image or registry tag; a malicious pull request; a tampered or mistaken backup; an honest mistake in an
upgrade. Out of scope: an attacker who already has root or `docker` group access on the VM, root on a Proxmox
node, or write access to `.env` or the engines' data.

## Trust boundaries

1. **LAN → the engines' ports.** Only `DB_CLIENT_SUBNET` gets a password prompt; PostgreSQL rejects other addresses
   before authentication. Neither engine is exposed beyond the servers' VLAN.
2. **LAN → the exporters' ports.** Unauthenticated, like the homelab's other exporters; they publish statistics,
   never rows.
3. **The VM's users, or the reverse proxy → DbGate.** Reaches structure only, and only with `dbviewer`'s password.
4. **The stack → the internet.** Diun calls the registries and the Discord webhook; nothing else calls out.
5. **Registries → host.** Images are trusted only at the digest a reviewed commit names.
6. **Repository → host.** A merge to `main` deploys through a pull agent that only fast-forwards; the required
   checks pass first.
7. **Pull requests → CI.** Fork pull requests get a read-only token and no secrets.

## Secure design principles

- **Least privilege**: every container drops every capability, runs unprivileged with `no-new-privileges` and a
  read-only root filesystem, and gets no Docker socket; each app's login reaches its own databases only; the
  exporters and `dbviewer` hold the least their job needs; CI tokens are read-only, raised per job.
- **Fail-safe defaults**: the policy check fails on anything it doesn't recognise as allowed, and an exception
  needs a reason in the file; the engines reject a connection no rule admits; `db.sh` validates every name against
  `^[a-z][a-z0-9_]{0,62}$` before it reaches SQL; `restore.sh` won't overwrite without `--replace`.
- **Complete mediation**: every change to what runs passes through a pull request and the same checks; every
  network connection to an engine passes `pg_hba.conf` or MariaDB's account rules.
- **Economy of mechanism**: one Compose file, upstream images unchanged, one standard-library checker per rule set.
- **Separation of privilege**: secrets live in files on the host, settings in `.env`, configuration in git; the
  age private key isn't on the VM; the superuser can't connect over the network.
- **Open design**: the configuration, the access rules, the policy and the release process are public.

## Common weaknesses

| Weakness | Where it could arise | How it's countered |
| --- | --- | --- |
| CWE-494 (code downloaded without integrity check) | Image pulls | Digest pins; signed release checksums |
| CWE-798 / CWE-312 (hard-coded or cleartext credentials) | Compose `environment:`, `.env`, docs, process arguments | Secrets only as files; passwords on stdin; gitleaks; push protection |
| CWE-250 (unnecessary privileges) | Container settings, Docker socket access | Policy rules `privileged`, `no-new-privileges`, `cap-drop`, `cap-add`, `host-*`, `docker-socket`, `devices` |
| CWE-284 / CWE-863 (improper access control) | Cross-app database access; network superuser | `CONNECT` revoked from `PUBLIC`; per-database grants; superuser rejected from the network; proved by the smoke test and `tests/test_settings.py` |
| CWE-89 (SQL injection) | `scripts/db.sh` building SQL from a name | Names validated against a strict pattern before use |
| CWE-22 (path traversal) | Restoring a backup | `restore.sh` verifies the checksummed manifest and validates archive names |
| CWE-532 (sensitive information in logs) | Scripts and containers logging passwords | Passwords never in arguments; the one known upstream case (an app logging its own connection string) is documented in [migrating.md](migrating.md) |
| CWE-1104 (unmaintained third-party components) | Images, tools, Actions | Dependabot weekly (the engines by hand, with Diun's alerts); weekly image scan ([dependencies.md](dependencies.md)) |
| CWE-77/78 (injection) | Workflows, scripts | Untrusted values only via `env:`; actionlint and shellcheck; CodeQL for Actions |

## Evidence

- CI on every change: ruff (with the bandit rules), yamllint, actionlint, gitleaks over the history, shellcheck,
  pytest with a 90 % branch-coverage floor, `docker compose config`, the policy check and the watch check, and a
  smoke test on amd64 that starts every pinned image, waits for its health check, creates logins and databases,
  proves the access rules, dumps, changes and restores, and runs the scheduled backup against a stand-in backup
  server.
- A weekly Trivy scan of every pinned image into code scanning; CodeQL (Python and Actions) on every pull request
  and weekly; OpenSSF Scorecard weekly; dependency review on every pull request.
