# Security

What this stack protects, against what, and how. The database server holds every app's data in the homelab, so
its boundaries are drawn tighter than a single app's.

- [Assets and threats](#assets-and-threats)
- [Trust boundaries](#trust-boundaries)
- [Access to the databases](#access-to-the-databases)
- [Policy](#policy)
- [Hardening](#hardening)
- [Secrets](#secrets)
- [Backups](#backups)

## Assets and threats

| Asset | Threat | Defence |
| --- | --- | --- |
| Every app's data | One app (or whoever takes it over) reading or changing another's | One login per app; each database's `CONNECT` granted to its owner only; MariaDB grants per database; checked by the smoke test |
| The engines | An administrator login from the network | PostgreSQL's `postgres` rejected for every network address (`pg_hba.conf`); MariaDB's root exists for `localhost` only |
| The engines | Logins from anywhere on the LAN | App logins from `DB_CLIENT_SUBNET` only; the exporters' from the stack's own network only; everything else rejected |
| Passwords | Sniffed on the LAN | SCRAM-SHA-256 (PostgreSQL), which never sends the password; TLS offered by both engines |
| Passwords | Leaked from the host | Secret files 0600 in 0700 folders, owned by `PUID`; passed to containers as Docker secrets, to the engines on stdin, never as process arguments or in `.env` |
| The data | Lost: a node, a disk, a bad upgrade, a bad migration | ZFS replication and HA to the second node; nightly dumps copied off the host; weekly whole-VM backups; a backup before every engine upgrade |
| The data | Corrupted silently | PostgreSQL data checksums; ZFS checksums |
| The host | An engine upgraded under the apps without warning | Engines pinned by digest, ignored by Dependabot, upgraded by hand after Diun's alert ([upgrading.md](upgrading.md)) |
| The host | A compromised image | Every image pinned by digest; weekly vulnerability scan; no container has a capability, privilege or the Docker socket |
| The Discord channel | Spam through a leaked webhook | The webhook is a secret file; Diun posts only alerts |

Out of scope: someone with root on the VM or a Proxmox node (they own the data), and the apps' own security.

## Trust boundaries

1. **LAN → the engines' ports.** Only `DB_CLIENT_SUBNET` gets a password prompt; PostgreSQL rejects other
   addresses before authentication. Keep the ports off the internet (the edge forwards nothing to this VM) and, if
   the firewall between VLANs allows it, limit them to the app servers' VLAN there too.
2. **LAN → the exporters' ports.** Unauthenticated, like Argus' other exporters: they publish statistics (database
   names and sizes, connection counts), never rows.
3. **The stack → the internet.** Diun calls the registries and Discord; nothing else calls out.
4. **Registries → the host.** Images are trusted only at the digest a reviewed commit names.
5. **The repository → the host.** A merge to `main` deploys (the pull agent). The required checks (policy, watches,
   smoke test) pass first; engine pins change only in pull requests you make.

## Access to the databases

`pg_hba.conf` (from `PG_HBA` in `compose.yaml`; first match wins):

| Connection | Who | Method |
| --- | --- | --- |
| The socket inside the container | `docker compose exec` (scripts, health check) | trust: only root or the `docker` group on the VM can get there |
| Network, as `postgres` | nobody | reject |
| Network, as `metrics`, to `postgres`, from `STACK_SUBNET` | postgres_exporter | SCRAM |
| Network, any other role, from `DB_CLIENT_SUBNET` | the apps | SCRAM; reaches only the databases it was granted `CONNECT` on |
| Anything else | | reject |

`scripts/db.sh create` makes each database owned by the app's login and revokes `CONNECT` and `TEMPORARY` from
`PUBLIC`, so a login can't even connect to another app's database. MariaDB users are created for
`DB_CLIENT_SUBNET` (address/netmask form) with `ALL PRIVILEGES` on their own databases only; `root` exists for
`localhost`; the exporter's user for `STACK_SUBNET` with `PROCESS`, `REPLICATION CLIENT` and `SELECT`.

## Policy

`scripts/check_compose.py` checks the resolved Compose file in CI, in the release workflow and with `make check`:
every image pinned as `name:tag@sha256:<digest>` and not `latest`, no build, no `privileged`, `no-new-privileges`
set, every capability dropped and none added outside Docker's default set, no host network or PID namespace, no
Docker socket, no devices, and a health check on every service. A service may break a rule only with an
`org.honeybeartech.mnemosyne.allow.<rule>` label giving the reason; none does.

`scripts/check_watches.py` checks that every engine (a service labelled `org.honeybeartech.mnemosyne.engine`) is
watched by Diun at the pinned tag with a pattern that matches it, and ignored by Dependabot.

## Hardening

Every service drops every capability, sets `no-new-privileges`, and runs as `PUID`:`PGID` from the start (no
root init that hands over), with a read-only root filesystem and memory-only `/tmp` and socket directories. None
needs a capability back. No container gets the Docker socket: Diun reads its watch list from a file. The engines
carry no `autoheal` label: restarting a database in the middle of its recovery only starts the recovery over, and
`restart: unless-stopped` covers crashes.

## Secrets

| Secret | Where | Who reads it |
| --- | --- | --- |
| PostgreSQL's superuser password | `CONFIG_ROOT/postgres/secrets/postgres_password` | the image's entrypoint, at the first start only |
| The exporters' passwords | `CONFIG_ROOT/postgres/secrets/metrics_password`, `CONFIG_ROOT/mariadb/secrets/exporter_password`, `CONFIG_ROOT/mysqld-exporter/secrets/my.cnf` | the init scripts at the first start; the exporters |
| MariaDB's root password | `CONFIG_ROOT/mariadb/secrets/root_password` | the entrypoint; `db.sh`, `backup.sh`, `restore.sh` (inside the container) |
| PostgreSQL's TLS key | `CONFIG_ROOT/postgres/tls/server.key` | PostgreSQL |
| The Discord webhook | `CONFIG_ROOT/diun/secrets/discord_webhook` | Diun |
| Each app's password | printed once by `db.sh`; kept only in the app's own settings | the app |

Changing the superuser's or root's password later is done in the engine (`ALTER ROLE` / `ALTER USER`) and in the
file together; the files are read at the first start only. Keep a copy of the files in your password manager.

## Backups

The dumps contain every app's data and the accounts' password hashes. `scripts/backup.sh` writes them 0700/0600;
the copy on the backup server should be readable by the backup user only. `scripts/restore.sh` checks a backup's
`SHA256SUMS` before it touches anything, refuses to overwrite a database without `--replace`, and never restores the
stack's own accounts (their passwords are this installation's).
