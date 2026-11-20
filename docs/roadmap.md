# Roadmap

Reviewed November 2026; it looks a year ahead (to November 2027) and is revised when plans change.

## Done

- [x] PostgreSQL and MariaDB, pinned; exporters for Argus; Diun alerts on Discord for engine releases
- [x] `scripts/db.sh`: per-app logins and databases; nightly dumps copied off the host (encrypted with age); per-database
      restore
- [x] The VM on Proxmox with ZFS replication and HA; the four drills in
      [installing.md](installing.md#drills-before-the-first-app-moves)
- [x] Argus dashboards and an alert for both engines
- [x] DbGate, a structure-only web GUI ([browsing.md](browsing.md))
- [x] The apps that can use an external database moved over, one at a time ([migrating.md](migrating.md))
- [x] Renovate replaces Dependabot: everything but the engines merges by itself after the checks and a 3-day wait;
      the engines are proposed and merged by hand ([dependencies.md](dependencies.md))

## Now

- [ ] A first signed release (`v0.1.0`), then a release whenever the pinned engines or the stack change
- [ ] A shared login for the reverse proxy in front of DbGate, if it is kept published there
- [ ] Watch the upstream apps' releases for the fix that stops them logging their connection string, and say from
      which version in [migrating.md](migrating.md)

## Later

- [ ] Make the engine check in `scripts/check_watches.py` cover all of `renovate.json` (manager-level rules, group
      settings, ignored paths, disabling patterns), or accept that a change to that file is reviewed by hand
- [ ] Remove the idle `dependabot-auto-merge.yml` workflow and the two workflow comments that name Dependabot
      (a workflow change, for the maintainer)

- [ ] Point-in-time recovery for PostgreSQL (WAL archiving with pgBackRest to the backup server), if minutes of loss
      between dumps ever matter
- [ ] A streaming replica on the second node, if failover should lose seconds rather than minutes
- [ ] A CA-signed certificate and `sslmode=verify-full` for the apps that support it
- [ ] Read-only roles in `scripts/db.sh` (for Grafana data sources)
- [ ] The next PostgreSQL major and MariaDB LTS line, by hand, when every app supports them
      ([upgrading.md](upgrading.md))

## Not planned

- A database cluster manager (Patroni, Galera): more moving parts than a homelab's apps need.
- Exposing either engine beyond the servers' VLAN.
- Apps that can't use an external database: they keep their own.
