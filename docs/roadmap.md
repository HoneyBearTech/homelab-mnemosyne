# Roadmap

## Now

- [x] PostgreSQL and MariaDB, pinned; exporters for Argus; Diun alerts on Discord for engine releases
- [x] `scripts/db.sh`: per-app logins and databases; nightly dumps off the host; per-database restore
- [ ] The VM on Proxmox with ZFS replication and HA; the four drills in [installing.md](installing.md#drills-before-the-first-app-moves)
- [ ] The apps moved over one at a time ([migrating.md](migrating.md))
- [ ] Argus dashboards and alerts for both engines

## Later

- [ ] Point-in-time recovery for PostgreSQL (WAL archiving with pgBackRest to the backup server), if minutes of loss
      between dumps ever matter
- [ ] A streaming replica on the second node, if failover should lose seconds rather than minutes
- [ ] A CA-signed certificate and `sslmode=verify-full` for the apps that support it
- [ ] Read-only roles in `scripts/db.sh` (for Grafana data sources)

## Not planned

- A database cluster manager (Patroni, Galera): more moving parts than a homelab's apps need.
- Exposing either engine beyond the servers' VLAN.
- Apps that can't use an external database: they keep their own.
