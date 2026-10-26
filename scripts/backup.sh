#!/usr/bin/env bash
# Dump every database on both engines into one backup directory, without stopping anything: each dump is a consistent
# snapshot of its database (pg_dump's own transaction; mariadb-dump --single-transaction for InnoDB), taken while the
# apps keep working.
#
#   scripts/backup.sh [DIR]     (default: backups/<date>-<time> in the checkout)
#
# DIR gets, readable only by its owner:
#   postgres/globals.sql         roles (with their password hashes) and role settings: pg_dumpall --globals-only
#   postgres/<db>.dump           each database, pg_dump's custom format (compressed; scripts/restore.sh reads it)
#   mariadb/users.sql            users and grants: mariadb-dump --system=users
#   mariadb/<db>.sql.gz          each database, with its routines, triggers and events
#   VERSION                      the engines' versions and this checkout's commit
#   SHA256SUMS                   written last: a backup without it is incomplete, and restore.sh refuses it
#
# The databases are listed at run time, so a new app's are backed up the night after scripts/db.sh creates them.
# scripts/scheduled-backup.sh runs this nightly and copies the result off the host.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=scripts/lib.sh
. "$root/scripts/lib.sh"

dir=${1:-$root/backups/$(date +%Y%m%d-%H%M%S)}
if [ -e "$dir" ] && [ -n "$(ls -A "$dir" 2>/dev/null)" ]; then
  echo "error: $dir already exists and isn't empty" >&2
  exit 1
fi
umask 077
mkdir -p "$dir/postgres" "$dir/mariadb"

# A deploy recreating an engine mid-dump would fail it; wait for one in progress, then hold it off.
deploy_lock

for service in postgres mariadb; do
  if [ "$(compose ps --status running --quiet "$service")" = "" ]; then
    echo "error: $service isn't running; nothing to dump" >&2
    exit 1
  fi
done

echo "PostgreSQL"
compose exec -T postgres pg_dumpall -U postgres --globals-only >"$dir/postgres/globals.sql"
while IFS= read -r db; do
  [ -n "$db" ] || continue
  echo "  $db"
  # </dev/null: compose exec forwards stdin, which would otherwise swallow the rest of the list.
  compose exec -T postgres pg_dump -U postgres --format=custom --compress=6 "$db" >"$dir/postgres/$db.dump" </dev/null
done < <(pg_sql -d postgres -tA <<<"SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres'
  ORDER BY 1;")

echo "MariaDB"
mariadb_dump() {
  # shellcheck disable=SC2016 # expanded by the container's shell
  compose exec -T mariadb sh -c 'MYSQL_PWD=$(cat /run/secrets/mariadb_root_password) exec mariadb-dump -uroot "$@"' \
    mariadb-dump "$@"
}
# --insert-ignore makes it CREATE USER IF NOT EXISTS, so a restore skips the users that exist.
mariadb_dump --system=users --insert-ignore >"$dir/mariadb/users.sql" </dev/null
while IFS= read -r db; do
  [ -n "$db" ] || continue
  echo "  $db"
  mariadb_dump --single-transaction --quick --routines --triggers --events --databases "$db" </dev/null |
    gzip -6 >"$dir/mariadb/$db.sql.gz"
done < <(maria_sql -N -B <<<"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME NOT IN
  ('mysql', 'sys', 'information_schema', 'performance_schema') ORDER BY 1;")

{
  echo "postgres: $(pg_sql -d postgres -tA <<<'SHOW server_version;')"
  echo "mariadb: $(maria_sql -N -B <<<'SELECT VERSION();')"
  echo "repo: $(git -C "$root" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "taken: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"$dir/VERSION"

(cd "$dir" && find . -type f ! -name 'SHA256SUMS*' | sort | sed 's|^\./||' | while IFS= read -r f; do sha256 "$f"; done \
  >SHA256SUMS.tmp && mv SHA256SUMS.tmp SHA256SUMS)
echo "Backup in $dir ($(du -sh "$dir" | cut -f1 | tr -d ' '))"
