#!/usr/bin/env bash
# Restore one database, or the accounts, from a backup scripts/backup.sh made. One app at a time: nothing else on
# the engine is touched.
#
#   scripts/restore.sh DIR pg DB [--replace]        a PostgreSQL database, with its owner and grants
#   scripts/restore.sh DIR mariadb DB [--replace]   a MariaDB database
#   scripts/restore.sh DIR pg-roles                 the apps' PostgreSQL roles (missing ones created; existing ones
#                                                   get the backup's attributes and password hash back)
#   scripts/restore.sh DIR mariadb-users            the apps' MariaDB users and grants (missing ones created;
#                                                   existing ones keep their password)
#
# The stack's own accounts (postgres, metrics; root, healthcheck, exporter, mariadb.sys) are never restored: their
# passwords are this installation's secrets, which a backup from another server doesn't match.
#
# A database that exists is left alone unless --replace is given; then it is dropped first, closing its connections
# (stop the app before, so it doesn't reconnect into a half-restored database). A PostgreSQL database's owner must
# exist: restore pg-roles first when restoring onto a new server. The backup's SHA256SUMS must be present and match.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=scripts/lib.sh
. "$root/scripts/lib.sh"

usage() {
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

[ $# -ge 2 ] || usage
dir=${1%/}
what=$2
db=${3:-}
replace=false
if [ "${4:-}" = --replace ]; then replace=true; elif [ -n "${4:-}" ]; then usage; fi
case $what in
  pg | mariadb)
    [ -n "$db" ] || usage
    if ! [[ $db =~ ^[a-z][a-z0-9_]{0,62}$ ]]; then
      echo "error: '$db' isn't a database name scripts/db.sh would have made" >&2
      exit 2
    fi
    ;;
  pg-roles | mariadb-users) [ -z "$db" ] || usage ;;
  *) usage ;;
esac

if [ ! -f "$dir/SHA256SUMS" ]; then
  echo "error: $dir has no SHA256SUMS: not a complete backup" >&2
  exit 1
fi
echo "Checking $dir"
(cd "$dir" && if command -v sha256sum >/dev/null; then sha256sum --quiet -c SHA256SUMS; else shasum -a 256 -q -c SHA256SUMS; fi)

deploy_lock

case $what in
  pg)
    file=$dir/postgres/$db.dump
    [ -f "$file" ] || {
      echo "error: the backup has no PostgreSQL database $db" >&2
      exit 1
    }
    exists=$(pg_sql -d postgres -tA <<<"SELECT count(*) FROM pg_database WHERE datname = '$db';")
    if [ "$exists" != 0 ]; then
      if ! $replace; then
        echo "error: $db exists; add --replace to drop it and restore the backup's" >&2
        exit 1
      fi
      echo "Dropping $db (closing its connections)"
      pg_sql -d postgres <<<"DROP DATABASE \"$db\" WITH (FORCE);"
    fi
    echo "Restoring $db"
    # --create makes the database with the owner, settings and grants it had (CONNECT revoked from PUBLIC included).
    compose exec -T postgres pg_restore -U postgres --dbname=postgres --create --exit-on-error <"$file"
    ;;
  mariadb)
    file=$dir/mariadb/$db.sql.gz
    [ -f "$file" ] || {
      echo "error: the backup has no MariaDB database $db" >&2
      exit 1
    }
    exists=$(maria_sql -N -B <<<"SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '$db';")
    if [ "$exists" != 0 ]; then
      if ! $replace; then
        echo "error: $db exists; add --replace to drop it and restore the backup's" >&2
        exit 1
      fi
      echo "Dropping $db"
      maria_sql <<<"DROP DATABASE \`$db\`;"
    fi
    echo "Restoring $db"
    # The dump creates the database itself (mariadb-dump --databases).
    gzip -dc "$file" | maria_sql
    ;;
  pg-roles)
    echo "Restoring PostgreSQL's roles"
    # The dump's CREATE ROLE fails for a role that exists, and its ALTER ROLE then sets the backup's attributes and
    # password: so not ON_ERROR_STOP. The stack's own roles are left out.
    grep -vE '^(CREATE|ALTER) ROLE (postgres|metrics)( |;)|^GRANT pg_monitor TO metrics' "$dir/postgres/globals.sql" |
      compose exec -T postgres psql -X -q -U postgres -d postgres
    ;;
  mariadb-users)
    echo "Restoring MariaDB's users and grants"
    # Accounts appear as 'user'@'host' or `user`@`host`, depending on the statement.
    grep -vE "[\`'](root|healthcheck|exporter|mariadb\.sys)[\`']@" "$dir/mariadb/users.sql" | maria_sql
    ;;
esac
echo "Done."
