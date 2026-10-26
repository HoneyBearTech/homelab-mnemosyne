# Changelog

All notable changes to homelab-mnemosyne are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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

### Changed

- PostgreSQL's health check no longer connects: it reads the server's own status (`postmaster.pid` says `ready`)
  and checks that port 5432 is listening. The old check logged into the server as `postgres` over TCP every 30
  seconds and was refused by `pg_hba.conf`, which wrote a connection line and two `FATAL` lines each time (about
  8,600 lines a day) and would have buried real failed logins. Deploying it recreates the `postgres` container.
- `docs/migrating.md`, Steerhouse: the restore leaves out the dump's grants (`--no-privileges`), which name Argus'
  `grafana_ro` before it exists here and stopped `--exit-on-error`; `grafana_ro` is created by hand as in
  Steerhouse's README, then Steerhouse's `analytics-grant` gives it the `analytics` views back. Found in a rehearsal
  against a copy of a live Steerhouse database.
