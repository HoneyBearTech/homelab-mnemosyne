# Moving an app onto the shared server

One app at a time, each a small change you can undo: the app's old database stays where it was until the app has run
well on the new one for a couple of weeks. The other stacks' repositories get the app's new settings (in their
gitignored `<service>.env`, never in `compose.yaml`), each in its own pull request.

- [The pattern](#the-pattern)
- [Which apps, on which engine](#which-apps-on-which-engine)
- [The *arr apps (Sonarr, Radarr, Lidarr, Prowlarr)](#the-arr-apps-sonarr-radarr-lidarr-prowlarr)
- [Bazarr](#bazarr)
- [Seerr](#seerr)
- [Steerhouse](#steerhouse)
- [Spoolman](#spoolman)
- [Grafana](#grafana)
- [Uptime Kuma](#uptime-kuma)
- [What stays where it is](#what-stays-where-it-is)

## The pattern

1. **Create its login and databases** on this server, and keep the password it prints for step 3:

   ```sh
   scripts/db.sh create pg sonarr sonarr_main sonarr_log
   ```

2. **Back the app up** on its own host (that stack's `scripts/backup.sh`), and stop it.
3. **Point it at the new database** (its settings below) and start it once against the empty database, so the app
   creates its own tables. Stop it again.
4. **Copy the data** (pgloader, or a dump for an app already on PostgreSQL), with the app's own preparations.
5. **Start it and check** what you care about in it: the library, the history, the settings, the logins.
6. **Keep the old database file** (SQLite) in the app's folder for two weeks, then delete it.

Rollback at any point: stop the app, take its database settings back out, start it on the old file. Anything it
wrote to the new database in between is lost to it.

**Rehearse each kind first.** Run steps 3 to 5 against a copy of the app's SQLite file and a throwaway database
(`db.sh create pg rehearsal rehearsal_main`) before the real move; drop the rehearsal afterwards
(`docker compose exec -T postgres psql -U postgres -c 'DROP DATABASE rehearsal_main' -c 'DROP ROLE rehearsal'`).

## Which apps, on which engine

| App | Engine | Databases | Copy the data with |
| --- | --- | --- | --- |
| Steerhouse | PostgreSQL | `steerhouse` | a dump (it is already on PostgreSQL 18) |
| Prowlarr | PostgreSQL | `prowlarr_main`, `prowlarr_log` | pgloader (unsupported upstream: rehearse) |
| Sonarr, Sonarr 4K | PostgreSQL | `sonarr_main`, `sonarr_log`; `sonarr4k_main`, `sonarr4k_log` | the same |
| Radarr, Radarr 4K | PostgreSQL | `radarr_main`, `radarr_log`; `radarr4k_main`, `radarr4k_log` | the same |
| Lidarr | PostgreSQL | `lidarr_main`, `lidarr_log` | the same |
| Bazarr, Bazarr 4K | PostgreSQL | `bazarr`; `bazarr4k` | pgloader, per Bazarr's guide |
| Seerr | PostgreSQL | `seerr` | pgloader, per Seerr's guide |
| Spoolman | PostgreSQL | `spoolman` | pgloader (no upstream guide: rehearse) |
| Grafana (Argus) | PostgreSQL | `grafana` | none: start fresh, Argus provisions the dashboards |
| Uptime Kuma | MariaDB | `uptime_kuma` | none: see below; recommended to stay on SQLite |

A suggested order: Steerhouse (a plain dump and restore), Prowlarr (the smallest *arr, a rehearsal for the others),
Radarr, Sonarr and Lidarr one at a time (each 4K instance after its sibling), then Bazarr, Seerr, Spoolman, Grafana.

## The *arr apps (Sonarr, Radarr, Lidarr, Prowlarr)

Each needs two databases, created beforehand (the app won't): a main one and a log one. Its settings, from the
environment (they override `config.xml`; the prefix is the app's name):

```sh
SONARR__POSTGRES__HOST=<this server>
SONARR__POSTGRES__PORT=5432
SONARR__POSTGRES__USER=sonarr
SONARR__POSTGRES__PASSWORD=<from db.sh>
SONARR__POSTGRES__MAINDB=sonarr_main
SONARR__POSTGRES__LOGDB=sonarr_log
```

The Servarr wiki's own guide (`wiki.servarr.com/<app>/postgres-setup`) is the reference, and it is blunt: moving an
existing SQLite database is **unsupported**, and its pgloader steps were written for PostgreSQL 14 (for 18 it says to
start fresh). They do work on this server's PostgreSQL 18, with three changes, as a rehearsal and the move of
Prowlarr showed (identical row counts in every table, the app's housekeeping vacuum running as the database's owner):

1. **Settings.** The app reads them from the environment (above) or from its `config.xml` (`PostgresHost`,
   `PostgresPort`, `PostgresUser`, `PostgresPassword`, `PostgresMainDb`, `PostgresLogDb`); `config.xml` needs no
   change to its stack. Keep a copy of the old `config.xml`, and never overwrite that copy if a step is run twice
   (`cp -n`).
2. **First start.** Stop the app cleanly, so its `.db` file has no `-wal` beside it, copy it here, and start the app
   once on the empty databases: it creates its tables (both databases at its current migration). Stop it again.
3. **Empty every table** in the main database, not only the ones the guide lists: the first start fills some
   (`VersionInfo`, `ScheduledTasks`, the default profiles), and loading "data only" into them would collide:

   ```sh
   echo "DO \$\$ BEGIN EXECUTE (SELECT 'TRUNCATE ' || string_agg(format('%I.%I', schemaname, tablename), ', ')
     || ' RESTART IDENTITY' FROM pg_tables WHERE schemaname = 'public'); END \$\$;" |
     docker compose exec -T postgres psql -U postgres -d sonarr_main -v ON_ERROR_STOP=1
   ```

4. **Copy the data with the Servarr maintainers' pgloader build**, run here so it reaches the database from inside
   the clients' range, with `sslmode=disable`: pgloader insists on verifying the certificate under `require`, and
   ignores its own `--no-ssl-cert-verification`; this connection never leaves the server. The password comes from an
   env file (`PGPASSWORD=…`, mode 600), not the command line:

   ```sh
   docker run --rm --network host --env-file pg.env -v "$PWD/sonarr.db:/app.db:ro" ghcr.io/roxedus/pgloader \
     --with "quote identifiers" --with "data only" /app.db "postgresql://sonarr@<this server>/sonarr_main?sslmode=disable"
   ```

   pgloader resets every sequence itself, so the guide's `setval` statements aren't needed; check that none is
   behind its table's highest id, and compare each table's row count with the `.db` file before starting the app.
5. **Start it and check** its own counts (for Prowlarr: indexers, apps, history) and its log. The log database isn't
   copied: it starts empty.

If the rehearsal fails for an app, the fallbacks are to leave it on SQLite (nothing else depends on it moving) or to
start it fresh on PostgreSQL and rebuild it (import lists and a rescan restore the library; the history is lost).

## Bazarr

Settings (they override `config.yaml`):

```sh
POSTGRES_ENABLED=true
POSTGRES_HOST=<this server>
POSTGRES_PORT=5432
POSTGRES_DATABASE=bazarr
POSTGRES_USERNAME=bazarr
POSTGRES_PASSWORD=<from db.sh>
PGSSLCERT=/tmp/postgresql.crt   # the linuxserver.io image runs as PUID; libpq otherwise looks in a home it can't read
```

Bazarr's guide (`wiki.bazarr.media`, PostgreSQL Database) copies the data with pgloader: after the first start on
the empty database, empty `system`, `table_settings_languages` and `table_settings_notifier` (don't drop any
table), then pgloader with `quote identifiers`, `data only` and the timestamp casts it lists.

## Seerr

```sh
DB_TYPE=postgres
DB_HOST=<this server>
DB_PORT=5432
DB_USER=seerr
DB_PASS=<from db.sh>
DB_NAME=seerr
DB_USE_SSL=true
DB_SSL_REJECT_UNAUTHORIZED=false   # the self-signed certificate; with your CA's, set DB_SSL_CA_FILE instead
```

Seerr's guide (`docs.seerr.dev`, Configuring the Database) copies the data with its patched pgloader image, `data
only` and `quote identifiers`, after one start on the empty database.

## Steerhouse

Already on PostgreSQL 18, in its own container on its host: a dump and a restore, no pgloader.

```sh
# On Steerhouse's host, with Steerhouse stopped (its database still running):
docker compose exec -T steerhouse-postgres pg_dump -U steerhouse --format=custom steerhouse >steerhouse.dump
# Copy steerhouse.dump to this server, then here:
scripts/db.sh create pg steerhouse steerhouse
docker compose exec -T postgres pg_restore -U postgres -d steerhouse --no-owner --no-privileges --role=steerhouse \
  --exit-on-error <steerhouse.dump
```

`--no-privileges` leaves out the dump's grants: they name roles from the old server, such as Argus' `grafana_ro`,
which don't exist here yet, and `--exit-on-error` would stop at the first of them. Steerhouse's own command gives
them back (below).

Then change Steerhouse's `database_url` secret to this server (with `sslmode=require`), start it, and once it's
settled remove its own database service in its stack's repository. Argus' read-only role, `grafana_ro`, moves with
it. Steerhouse never creates roles, and its login here is no superuser, so create the role by hand as in
Steerhouse's README (`CREATE ROLE grafana_ro LOGIN PASSWORD '…' NOINHERIT CONNECTION LIMIT 10`, its `ALTER ROLE …
SET`s, and `GRANT CONNECT ON DATABASE steerhouse`; the SQL on stdin, so the password stays out of the process
list), then let Steerhouse grant it the `analytics` views: `python -m app.cli analytics-grant grafana_ro` in its
backend, and `analytics-check grafana_ro` to confirm. Point Argus' data source at this server.

## Spoolman

```sh
SPOOLMAN_DB_TYPE=postgres
SPOOLMAN_DB_HOST=<this server>
SPOOLMAN_DB_PORT=5432
SPOOLMAN_DB_NAME=spoolman
SPOOLMAN_DB_USERNAME=spoolman
SPOOLMAN_DB_PASSWORD_FILE=<a file holding the password>
```

Spoolman has no migration guide. Its database is small, so the pattern with pgloader (`data only`, `quote
identifiers`) after one start is the way; rehearse it first.

## Grafana

```sh
GF_DATABASE_TYPE=postgres
GF_DATABASE_HOST=<this server>:5432
GF_DATABASE_NAME=grafana
GF_DATABASE_USER=grafana
GF_DATABASE_PASSWORD__FILE=<a file holding the password>
GF_DATABASE_SSL_MODE=require
```

Argus provisions its dashboards and data sources as code, so Grafana starts fresh on PostgreSQL and loses only what
was made in its UI (users, API keys, preferences). Keep in mind that Argus' dashboards then go dark whenever this
server is down, which is when you'd want to look at them; staying on SQLite is a fair choice.

## Uptime Kuma

Uptime Kuma 2.x supports an external MariaDB, chosen in its first-run setup; there is no documented move of an
existing SQLite installation, so it would mean re-creating the monitors. More importantly, Uptime Kuma is what tells
you when this server is down. On this server's MariaDB it would go down with it and say nothing. Keep it on its own
SQLite; MariaDB stays ready for an app that needs it.

## What stays where it is

These keep their own embedded database or data files; none of them can use an external one: Plex, Tautulli, Kometa
and its helpers, Tdarr, SABnzbd, qBittorrent, Heimdall, Dozzle, Recyclarr, Portainer, PeaNUT, the Minecraft server.
Prometheus and Loki keep their own time-series storage. Nginx Proxy Manager could use either engine, but it is being
replaced by Traefik, which has no database. GitLab keeps the PostgreSQL its Linux package installs and upgrades with
it: it needs specific PostgreSQL majors (16.5 or later for GitLab 18) on its own schedule.
