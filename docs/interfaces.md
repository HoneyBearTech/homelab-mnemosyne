# Interfaces

Everything the stack takes in and offers: its settings, the ports the other stacks' apps and Argus use, the files
it keeps under `CONFIG_ROOT`, and its scripts.

## Settings (`.env`)

Every setting is required (`compose.yaml` refuses to start without it) and has an example in
[`.env.example`](../.env.example). `tests/test_settings.py` checks that the two and this table agree.

| Setting | Example | What it is |
| --- | --- | --- |
| `TZ` | `Etc/UTC` | Time zone for the logs and Diun's schedule |
| `PUID`, `PGID` | `1000` | The user and group every service runs as and that owns its folders under `CONFIG_ROOT`; `scripts/db.sh init` must run as this user (or as root) |
| `CONFIG_ROOT` | `/srv/config` | Host directory with one folder per service (below); on the VM's data disk, never inside `/var/lib/docker/volumes` |
| `DB_CLIENT_SUBNET` | `192.0.2.0/24` | The range the apps connect from. PostgreSQL admits app logins from here only; MariaDB users are created for it |
| `STACK_SUBNET` | `172.30.0.0/24` | This stack's Docker network, fixed so the exporters' accounts can be limited to it |
| `PG_PORT` | `5432` | PostgreSQL's published port |
| `MARIADB_PORT` | `3306` | MariaDB's published port |
| `PG_EXPORTER_PORT` | `9187` | postgres_exporter's metrics port, for Argus' Prometheus |
| `MYSQLD_EXPORTER_PORT` | `9104` | mysqld_exporter's metrics port, for Argus' Prometheus |
| `PG_MAX_CONNECTIONS` | `300` | PostgreSQL `max_connections`: every app's pool together, plus headroom |
| `PG_SHARED_BUFFERS` | `2GB` | PostgreSQL `shared_buffers` (about a quarter of the VM's memory) |
| `PG_EFFECTIVE_CACHE_SIZE` | `5GB` | PostgreSQL `effective_cache_size` (what the planner may assume the OS caches) |
| `PG_WORK_MEM` | `8MB` | PostgreSQL `work_mem`, per sort or hash, per query |
| `PG_SHM_SIZE` | `512m` | The postgres container's `/dev/shm` (parallel queries) |
| `MARIADB_BUFFER_POOL_SIZE` | `512M` | MariaDB `innodb_buffer_pool_size` |
| `MARIADB_MAX_CONNECTIONS` | `200` | MariaDB `max_connections` |
| `DIUN_SCHEDULE` | `0 */6 * * *` | When Diun checks the registries (cron, in `TZ`) |

The unattended backup has its own optional settings in `backup.env` (template:
[`backup.env.example`](../backup.env.example)): `BACKUP_DIR`, `BACKUP_KEEP`, `BACKUP_REMOTE`, `BACKUP_REMOTE_KEEP`,
`BACKUP_PING_URL`, and `BACKUP_AGE_RECIPIENT` (an age public key: the copy at `BACKUP_REMOTE` is then only
`backup.tar.age`, the backup directory as one tar archive encrypted to that key, and its `SHA256SUMS`; needs `age`
on the host).

## Ports

| Port (default) | Service | Who connects | Protocol |
| --- | --- | --- | --- |
| 5432 | PostgreSQL | apps on `DB_CLIENT_SUBNET`, each with its own login | PostgreSQL; TLS offered (1.2+), SCRAM passwords |
| 3306 | MariaDB | apps on `DB_CLIENT_SUBNET`, each with its own user | MySQL protocol; TLS offered |
| 9187 | postgres_exporter | Argus' Prometheus | HTTP `/metrics` |
| 9104 | mysqld_exporter | Argus' Prometheus | HTTP `/metrics` |

Diun has no port: it only calls out (the registries, Discord).

## What an app needs

| | PostgreSQL | MariaDB |
| --- | --- | --- |
| Host | the VM's address (or a DNS name for it) | the same |
| Port | `PG_PORT` | `MARIADB_PORT` |
| Login | the one `scripts/db.sh create pg` made | the one `scripts/db.sh create mariadb` made |
| Password | printed once by `db.sh create` (or `db.sh password`) | the same |
| Databases | the ones named to `db.sh create`, owned by the login | the ones named to `db.sh create`, all rights |
| TLS | offered; `sslmode=require` encrypts, `verify-full` also needs the certificate's CA ([installing.md](installing.md#tls)) | offered (a certificate MariaDB makes itself) |

Per-app settings for the homelab's apps are in [migrating.md](migrating.md).

## Files under `CONFIG_ROOT`

| Path | Holds | Created by |
| --- | --- | --- |
| `postgres/config/` | the PostgreSQL cluster (`18/docker/` for PostgreSQL 18) | the image, on the first start |
| `postgres/tls/server.crt`, `server.key` | PostgreSQL's certificate and key (0600) | `scripts/db.sh init` (self-signed), or yours |
| `postgres/secrets/postgres_password`, `metrics_password` | the superuser's and the exporter's passwords | `scripts/db.sh init` |
| `mariadb/config/` | the MariaDB data directory | the image, on the first start |
| `mariadb/secrets/root_password`, `exporter_password` | root's and the exporter's passwords | `scripts/db.sh init` |
| `mysqld-exporter/secrets/my.cnf` | the exporter's login | `scripts/db.sh init` |
| `diun/config/diun.db` | the tags and digests Diun has seen | Diun |
| `diun/secrets/discord_webhook` | the Discord channel's webhook URL | `scripts/db.sh init` (asks for it) |

Every `secrets/` and `tls/` folder is 0700 and every file in it 0600, owned by `PUID`:`PGID`.

## Scripts

| Command | Does |
| --- | --- |
| `scripts/db.sh init [--tls-name NAME]...` | Creates the folders, passwords, exporter login and certificate; asks for the Discord webhook. Never overwrites |
| `scripts/db.sh create pg\|mariadb LOGIN DB...` | A login (if new; its password printed once) and new databases it owns |
| `scripts/db.sh password pg\|mariadb LOGIN` | A new password for a login, printed once |
| `scripts/db.sh list` | Every database on both engines, its owner and size |
| `scripts/backup.sh [DIR]` | Dumps every database and the accounts, without stopping anything |
| `scripts/restore.sh DIR pg\|mariadb DB [--replace]` | Restores one database from a dump |
| `scripts/restore.sh DIR pg-roles\|mariadb-users` | Restores the apps' accounts (onto a new server) |
| `scripts/scheduled-backup.sh` | The nightly run: `backup.sh`, rsync to the backup server (encrypted with age when `BACKUP_AGE_RECIPIENT` is set), pruning, Uptime Kuma push |
| `scripts/check_compose.py` | The image and hardening policy over `docker compose config --format json` |
| `scripts/check_watches.py` | Every engine pin is watched by Diun at that tag and ignored by Dependabot |
| `scripts/smoke-test.sh` | Starts the stack with throwaway settings and proves the above |
