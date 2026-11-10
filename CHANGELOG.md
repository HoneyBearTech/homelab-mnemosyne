# Changelog

All notable changes to homelab-mnemosyne are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `docs/assurance-case.md` (threat model, trust boundaries, secure design principles, common weaknesses), an
  "Actors and actions" section in the architecture, and a roadmap that looks a year ahead.
- The stack: PostgreSQL 18.6 and MariaDB 11.8.9 (LTS), pinned by digest; postgres_exporter and mysqld_exporter for
  Argus; Diun watching both engines and posting new releases and rebuilds to Discord.
- `scripts/db.sh`: the stack's secrets and certificate (`init`), per-app logins and databases (`create`), new
  passwords (`password`), and an overview (`list`).
- `scripts/backup.sh` and `scripts/restore.sh`: dumps of every database and the accounts without stopping anything;
  restore one database, or the apps' accounts, from them. The nightly run (`scripts/scheduled-backup.sh`, the systemd
  timer) copies the dumps off the host, as on the other stacks.
- An encrypted copy off the host for the scheduled backup, as on homelab-ares: with `BACKUP_AGE_RECIPIENT` (an age
  public key) in `backup.env`, only `backup.tar.age` and its `SHA256SUMS` leave the host, and only the private key's
  holder can read them (`age -d -i <key> backup.tar.age | tar -x`). Needs `age` on the host; optional, and without it
  the dumps are copied as before. The smoke test now runs the scheduled backup against a stand-in backup server and
  checks that only the archive leaves, that the key opens it into the whole backup, and that another key doesn't.
- `scripts/check_watches.py`: CI fails if an engine is pinned but not watched by Diun at that tag, or not ignored by
  Dependabot.
- Documentation: installing on Proxmox with ZFS replication and HA, moving each of the homelab's apps over,
  upgrading the engines, and rebuilding from the dumps.
- DbGate, a web GUI for both engines (`dbgate`, Dependabot-managed): every database's tables, columns, keys,
  indexes, sizes and ER diagrams. It answers on `127.0.0.1` only (reach it through an SSH tunnel; `DBGATE_PORT`),
  runs as `PUID`:`PGID` on a read-only root filesystem, holds no password, and logs in as `dbviewer`
  (`scripts/db.sh viewer pg|mariadb`), which connects from the stack's network only and sees structure, never rows.
- `DBGATE_BIND_ADDRESS`: DbGate can be published on the VM's address for a reverse proxy instead of `127.0.0.1`,
  with a `DOCKER-USER` rule so only the proxy reaches it and the proxy's access list as its login
  (docs/browsing.md). Optional: without it nothing changes.
  `db.sh create` grants `dbviewer` each new PostgreSQL database; the smoke test proves it sees a table's columns and
  can't read the table on both engines ([docs/browsing.md](docs/browsing.md)).

### Upgrading

- DbGate adds a required setting, `DBGATE_PORT`, and a folder, `CONFIG_ROOT/dbgate/config`. On an installation
  from before it, add both before the merge deploys, or the deploy stops at `docker compose config` and changes
  nothing ([docs/browsing.md](docs/browsing.md#on-an-installation-from-before-dbgate)).

### Changed

- PostgreSQL's health check no longer connects: it reads the server's own status (`postmaster.pid` says `ready`)
  and checks that port 5432 is listening. The old check logged into the server as `postgres` over TCP every 30
  seconds and was refused by `pg_hba.conf`, which wrote a connection line and two `FATAL` lines each time (about
  8,600 lines a day) and would have buried real failed logins. Deploying it recreates the `postgres` container.
- `docs/migrating.md`, Steerhouse: the restore leaves out the dump's grants (`--no-privileges`), which name Argus'
  `grafana_ro` before it exists here and stopped `--exit-on-error`; `grafana_ro` is created by hand as in
  Steerhouse's README, then Steerhouse's `analytics-grant` gives it the `analytics` views back. Found in a rehearsal
  against a copy of a live Steerhouse database.
- `docs/migrating.md`, the *arr apps: the Servarr pgloader recipe as it works on PostgreSQL 18, from a rehearsal and
  the move of Prowlarr: settings in `config.xml`, empty every table after the first start, pgloader with
  `sslmode=disable` from this server (it rejects a self-signed certificate under `require`), no `setval` list.
