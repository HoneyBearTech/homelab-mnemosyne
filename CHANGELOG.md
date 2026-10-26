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
- `scripts/check_watches.py`: CI fails if an engine is pinned but not watched by Diun at that tag, or not ignored by
  Dependabot.
- Documentation: installing on Proxmox with ZFS replication and HA, moving each of the homelab's apps over,
  upgrading the engines, and rebuilding from the dumps.
