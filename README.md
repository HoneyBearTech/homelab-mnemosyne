# homelab-mnemosyne

[![CI](https://github.com/HoneyBearTech/homelab-mnemosyne/actions/workflows/ci.yml/badge.svg)](https://github.com/HoneyBearTech/homelab-mnemosyne/actions/workflows/ci.yml)
[![CodeQL](https://github.com/HoneyBearTech/homelab-mnemosyne/actions/workflows/codeql.yml/badge.svg)](https://github.com/HoneyBearTech/homelab-mnemosyne/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/HoneyBearTech/homelab-mnemosyne/badge)](https://scorecard.dev/viewer/?uri=github.com/HoneyBearTech/homelab-mnemosyne)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/15951/badge)](https://www.bestpractices.dev/projects/15951)
[![OpenSSF Baseline](https://www.bestpractices.dev/projects/15951/baseline)](https://www.bestpractices.dev/projects/15951)

Docker Compose stack for Mnemosyne, the homelab's shared database server: one PostgreSQL and one MariaDB that the
other stacks' apps use instead of each keeping its own database, on a Proxmox VM that replicates to a second node
and restarts there if its node fails. Version-pinned and kept as code, like the homelab's other servers.

- **One login per app.** `scripts/db.sh create pg sonarr sonarr_main sonarr_log` gives an app its own role and
  databases that no other app can connect to. Neither superuser can log in over the network.
- **Engines upgraded on purpose.** PostgreSQL and MariaDB are pinned by digest and left alone by Dependabot. Diun
  watches their tags and posts to Discord when a new release or a rebuild of the pinned tag appears; the upgrade is
  a pull request made by hand ([docs/upgrading.md](docs/upgrading.md)).
- **Backups that restore one app.** Nightly dumps of every database, taken without stopping anything and copied off
  the host (encrypted with age, when `BACKUP_AGE_RECIPIENT` is set); `scripts/restore.sh` brings back one database,
  or all of them onto a new server.
- **Metrics for Argus** from postgres_exporter and mysqld_exporter.

> [!WARNING]
> Every app that moves here depends on this one server. Do the drills in
> [docs/installing.md](docs/installing.md#drills-before-the-first-app-moves) (a restore, the nightly copy, a
> failover, a Discord alert) before the first app moves, and move apps one at a time
> ([docs/migrating.md](docs/migrating.md)).

## Documentation

- [Quick start](docs/quick-start.md): the stack running in five commands
- [Installing](docs/installing.md): the VM, ZFS replication and HA, the stack, TLS, backups, Argus, the drills
- [Migrating](docs/migrating.md): moving each app over, with its settings; what stays where it is
- [Upgrading](docs/upgrading.md): what Diun's messages mean; rebuilds, minors, a PostgreSQL major, MariaDB's LTS
- [Interfaces](docs/interfaces.md): every setting, port, file and script
- [Architecture](docs/architecture.md), [Security](docs/security.md), [Rebuilding](docs/rebuilding.md),
  [Dependencies](docs/dependencies.md), [Verifying releases](docs/verifying-releases.md), [Roadmap](docs/roadmap.md)

## Contributing and support

See [CONTRIBUTING.md](CONTRIBUTING.md), [SUPPORT.md](SUPPORT.md) and [SECURITY.md](SECURITY.md). Licensed under
the terms in [LICENSE](LICENSE).
