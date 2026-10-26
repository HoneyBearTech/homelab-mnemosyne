# Architecture

```text
                          the servers' VLAN
  app hosts ──────────── 5432 ──┐                ┌── 9187 ─── Argus' Prometheus
  (Sonarr, Seerr, …)     3306 ──┤                ├── 9104 ───┘
                                ▼                │
              ┌──────────── the VM (Proxmox, HA) ─┴────────────────────────┐
              │  postgres ◄── postgres-exporter        diun ──► registries │
              │  mariadb  ◄── mysqld-exporter               └──► Discord   │
              │  CONFIG_ROOT on the data disk (ZFS zvol)                   │
              └───────────────┬─────────────────────────────┬──────────────┘
                 ZFS replication, every few minutes      nightly dumps (rsync/SSH),
                 → the other node (HA restarts it there)  weekly vzdump → backup server
```

## Services

| Service | Image | Role |
| --- | --- | --- |
| `postgres` | `postgres` (Debian trixie) | The shared PostgreSQL. One login and its own databases per app |
| `mariadb` | `mariadb` (Ubuntu noble, LTS line) | The shared MariaDB, for apps that only speak MySQL |
| `postgres-exporter` | `prometheuscommunity/postgres-exporter` | PostgreSQL's metrics for Argus, as the `pg_monitor` role `metrics` |
| `mysqld-exporter` | `prom/mysqld-exporter` | MariaDB's metrics for Argus |
| `diun` | `crazymax/diun` | Watches the two engines' tags; posts new releases and rebuilds to Discord |

All five share one Docker network with a fixed range (`STACK_SUBNET`), so the engines can admit the exporters by
address. The engines publish their ports on the VM's address for the apps; the exporters publish theirs for Argus.

## Data flow

- **Apps → engines.** Each app connects with its own login from its own host (`DB_CLIENT_SUBNET`), over TLS when
  it asks for it.
- **Engines → disk.** Each engine's data is under `CONFIG_ROOT/<service>/config` on the VM's data disk, a zvol on
  the node's ZFS pool.
- **Disk → the other node.** Proxmox replicates the VM's disks every few minutes; HA restarts the VM from the
  latest copy if its node fails.
- **Engines → backups.** `scripts/backup.sh` dumps every database nightly (nothing stopped);
  `scripts/scheduled-backup.sh` copies the dumps to the backup server (one archive encrypted with age, when
  `BACKUP_AGE_RECIPIENT` is set). Proxmox backs up the whole VM weekly.
- **Registries → Discord.** Diun compares the pinned tags and newer ones with what it saw last time and posts the
  differences.

## Why these choices

- **One VM, two engines, no replication between databases.** The homelab's apps are small and tolerate a few
  minutes of lost writes; Proxmox's disk replication with HA gives a second copy and automatic restart without a
  database cluster to run. A streaming replica (or Patroni) would cut the loss to seconds at the cost of a second
  database VM and its failover logic: [roadmap](roadmap.md).
- **Containers, pinned by digest.** The same pattern as the homelab's other stacks: the server can be rebuilt from
  this repository, and every version change is a reviewed commit.
- **Engines upgraded by hand.** Every app depends on them; a restart is an outage for all of them at once.
- **Dumps, not file copies, for backups.** A dump restores one app's database without touching the others, and
  restores into a newer major; the replica and the vzdump cover the whole server.
