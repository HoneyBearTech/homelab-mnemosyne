# Changelog

All notable changes to homelab-mnemosyne are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-10

The first release: the Docker Compose stack for Mnemosyne, a shared PostgreSQL and MariaDB for the homelab's apps.
It pins these images by tag and digest:

| Service | Image |
| --- | --- |
| PostgreSQL | `postgres:18.6-trixie` |
| MariaDB (LTS) | `mariadb:11.8.9-noble` |
| postgres_exporter | `prometheuscommunity/postgres-exporter:v0.20.1` |
| mysqld_exporter | `prom/mysqld-exporter:v0.21.0` |
| Diun | `crazymax/diun:4.33.1` |
| DbGate | `dbgate/dbgate:7.3.4` |

### Added

- **One login per app.** `scripts/db.sh` creates the stack's secrets and TLS certificate (`init`), an app's login and
  databases (`create`), new passwords (`password`), DbGate's structure-only login (`viewer`) and an overview
  (`list`). Neither superuser can log in over the network, app logins connect only from `DB_CLIENT_SUBNET`, and every
  database it makes has `CONNECT` revoked from `PUBLIC`, so one app can't open another's database
  ([docs/security.md](docs/security.md#access-to-the-databases)).
- **Backups that restore one app.** `scripts/backup.sh` dumps every database and the accounts without stopping
  anything, and `scripts/restore.sh` brings back one database or the accounts. The nightly run
  (`scripts/scheduled-backup.sh` and a systemd timer) copies the dumps off the host, encrypted with age when
  `BACKUP_AGE_RECIPIENT` is set, so only the private key's holder can read them.
- **Engines upgraded on purpose.** Diun watches both engines' tags and posts to Discord when a release or a rebuild
  appears; Dependabot leaves them alone, and `scripts/check_watches.py` fails CI if an engine is pinned but not
  watched ([docs/upgrading.md](docs/upgrading.md)).
- **Metrics** from both exporters for Prometheus.
- **DbGate**, a web GUI for both engines' structure (tables, columns, keys, indexes, sizes, diagrams) and never their
  rows, as `dbviewer`. It answers on `127.0.0.1` for an SSH tunnel, or on one address for a reverse proxy
  (`DBGATE_BIND_ADDRESS`) that a `DOCKER-USER` rule admits alone ([docs/browsing.md](docs/browsing.md)).
- **Hardening that CI enforces.** Every service drops all capabilities, runs as `PUID`:`PGID` on a read-only root
  filesystem and has a health check; none has the Docker socket. `scripts/check_compose.py` checks the policy on
  every change and in the release workflow.
- **Tests.** Offline unit tests with a coverage floor, and a smoke test on amd64 that starts every service, proves the
  access rules over the network, dumps and restores, and runs the scheduled backup against a stand-in backup server.
- **Documentation**: installing on Proxmox with ZFS replication and HA, moving each app over, upgrading the engines,
  rebuilding from the dumps, browsing, interfaces, security, an assurance case, and how this release is verified.
- **Signed releases**: a signed tag, a cosign-signed `SHA256SUMS`, SLSA provenance and a CycloneDX SBOM listing every
  image and digest ([docs/verifying-releases.md](docs/verifying-releases.md)).

### Changed

- PostgreSQL's health check no longer connects: it reads the server's own status (`postmaster.pid` says `ready`) and
  checks that port 5432 is listening. The old check logged in as `postgres` over TCP every 30 seconds and was refused
  by `pg_hba.conf`, about 8,600 log lines a day that would have buried real failed logins.
- The migration guide ([docs/migrating.md](docs/migrating.md)) now has the Servarr pgloader recipe as it works on
  PostgreSQL 18, the restore for Steerhouse's database without the dump's grants, and a warning that the *arr apps
  write their database password to their start-up log.

### Upgrading

- This is the first release; there is nothing to upgrade from. An installation running `main` from before DbGate
  needs the `DBGATE_PORT` setting and the `CONFIG_ROOT/dbgate/config` folder before it pulls
  ([docs/browsing.md](docs/browsing.md#on-an-installation-from-before-dbgate)).
- Known findings in the pinned images, and why they don't apply here, are in
  [docs/dependencies.md](docs/dependencies.md#current-findings).

[Unreleased]: https://github.com/HoneyBearTech/homelab-mnemosyne/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/HoneyBearTech/homelab-mnemosyne/releases/tag/v0.1.0
