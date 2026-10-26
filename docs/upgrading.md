# Upgrading

Two kinds of update reach this stack, and they are handled differently.

- **The exporters, Diun, the check tools and the Actions** are Dependabot's, as in every homelab stack: a pull
  request, the required checks, auto-merge, and the pull agent deploys it. Compose recreates only the service whose
  image changed, so the engines don't restart.
- **The two engines** (PostgreSQL, MariaDB) are pinned by hand. Every app in the homelab depends on them, and
  restarting either one, even for a patch, drops every app's connections. Dependabot ignores them;
  [Diun](../diun/images.yml) posts to Discord instead, and an upgrade is a pull request you make and merge at a
  quiet time. `scripts/check_watches.py` fails CI if the pin and the watch disagree.

- [What Diun's messages mean](#what-diuns-messages-mean)
- [A rebuild, a patch or a minor release](#a-rebuild-a-patch-or-a-minor-release)
- [PostgreSQL: a new major](#postgresql-a-new-major)
- [MariaDB](#mariadb)
- [Before any engine upgrade](#before-any-engine-upgrade)

## What Diun's messages mean

| Message | Means | Do |
| --- | --- | --- |
| `postgres:18.6-trixie` **has been updated** | The pinned tag was rebuilt upstream (new digest, same PostgreSQL): usually Debian security fixes | [A rebuild](#a-rebuild-a-patch-or-a-minor-release), within a week or two |
| `postgres:18.7-trixie` **is available** | A new minor release: bug and security fixes, same data format | [A minor release](#a-rebuild-a-patch-or-a-minor-release), soon; read the release notes |
| `postgres:19.0-trixie` **is available** | A new major | Nothing yet. [A major](#postgresql-a-new-major), once your apps support it and it has had a few minor releases |
| `mariadb:11.8.10-noble` **is available**, or `11.8.9-noble` **has been updated** | A patch of the LTS line, or a rebuild | [A patch](#a-rebuild-a-patch-or-a-minor-release) |
| `mariadb:12.x.y-noble` **is available** | A newer series | Only when it is the next LTS: [MariaDB](#mariadb) |

A message about another watched tag than the pin (an older minor rebuilt, say) needs nothing.

## A rebuild, a patch or a minor release

The data format doesn't change, so the new image opens the existing data as it is.

1. On your workstation, find the new digest (`docker buildx imagetools inspect postgres:18.7-trixie`, the top-level
   `Digest`), and in one branch change the tag and digest in `compose.yaml` and the tag in `diun/images.yml`'s
   `name`. For a rebuild only the digest changes.
2. Read the release notes ([PostgreSQL](https://www.postgresql.org/docs/release/),
   [MariaDB](https://mariadb.com/kb/en/release-notes/)): a minor release sometimes asks for a `REINDEX` or another
   step after the upgrade.
3. Open the pull request; CI runs the smoke test against the new image.
4. At a quiet time, [take a backup](#before-any-engine-upgrade) and merge. The pull agent deploys within a couple of
   minutes: the engine stops (its stop grace period lets it checkpoint), starts on the new image, and the apps
   reconnect. MariaDB runs `mariadb-upgrade` itself when its version changed (`MARIADB_AUTO_UPGRADE`).
5. Check: `docker compose ps` healthy, `scripts/db.sh list`, a look at an app or two, `pg_up`/`mysql_up` in Argus.

Rollback: a revert pull request. Going back a minor release is safe for PostgreSQL; for MariaDB a patch downgrade
within the LTS line usually is, but restore from the backup if it complains.

## PostgreSQL: a new major

A new major can't open the old one's data directory: the data is dumped and restored into a fresh cluster. At this
size (a few GB) that takes minutes, and it is the procedure this stack tests (backup and restore run in the smoke
test).

Wait until: every app on the server supports the new major (the *arr apps list theirs in the Servarr wiki; check
Seerr, Bazarr, Grafana, Spoolman and Steerhouse too), and the major has had a minor release or two (x.1, x.2).

1. Prepare the pull request as for a minor (tag, digest, `diun/images.yml`), and change the major in
   `diun/images.yml`'s pattern if it needs it. Don't merge yet.
2. Plan an hour when the apps may be down. Stop them, or accept that they log errors and retry.
3. On the VM:

   ```sh
   cd ~/homelab-mnemosyne
   CONFIG_ROOT=$(sed -n 's/^CONFIG_ROOT=//p' .env)
   scripts/backup.sh ~/pg-major-dump                   # nothing stopped; every database and the roles
   docker compose stop postgres-exporter postgres
   mv "$CONFIG_ROOT/postgres/config" "$CONFIG_ROOT/postgres/config.18"
   mkdir "$CONFIG_ROOT/postgres/config"
   ```

4. Merge the pull request (or check out its branch on the VM and `docker compose up -d --wait`). The new major
   initialises an empty cluster and runs `initdb/postgres/` (the exporter's role).
5. Restore the roles, then every database:

   ```sh
   scripts/restore.sh ~/pg-major-dump pg-roles
   for f in ~/pg-major-dump/postgres/*.dump; do scripts/restore.sh ~/pg-major-dump pg "$(basename "$f" .dump)"; done
   scripts/db.sh list
   ```

6. Start the apps and check each one. Keep `config.18` and the dump until you're satisfied.

Rollback: stop PostgreSQL, put `config.18` back, revert the pull request. Writes made on the new major in between
are lost unless dumped first.

## MariaDB

The stack follows MariaDB's long-term support lines (11.8 now; five years of community support). Diun reports every
newer series, but only an LTS is worth moving to: the series in between are supported for about a quarter each.

Moving to the next LTS is an in-place upgrade: MariaDB opens the older data and `MARIADB_AUTO_UPGRADE` runs
`mariadb-upgrade` (after saving the system tables in the data directory). Do it as
[a minor](#a-rebuild-a-patch-or-a-minor-release), one LTS at a time, after reading the upgrade notes for that series and checking that the apps on it support it. A downgrade
to the older series isn't supported: the way back is the backup.

## Before any engine upgrade

- `scripts/backup.sh` (or check that last night's ran: the push monitor, `ls backups/`).
- A failover in the middle of an upgrade brings the VM back on the other node with the checkout and data of the
  last replication: finish (or roll back) the upgrade there as you would have on the first node.
- Merging deploys. With the pull agent on this host, a merge is the upgrade; merge only when you're ready for the
  restart.
