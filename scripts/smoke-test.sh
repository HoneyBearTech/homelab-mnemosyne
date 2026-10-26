#!/usr/bin/env bash
# Smoke test of the stack: start every service in compose.yaml with throwaway settings and secrets, wait until each
# one reports healthy, then prove what the stack promises:
#   - scripts/db.sh gives an app a login and databases, and the app can use them over the network (PostgreSQL with
#     TLS required, MariaDB) from DB_CLIENT_SUBNET;
#   - an app's login reaches only its own databases, and neither superuser (postgres, root) can log in over the
#     network, even with the right password;
#   - creating more databases for an existing login keeps its password, and `db.sh password` replaces it;
#   - both exporters are logged in to their engine (pg_up 1, mysql_up 1);
#   - scripts/backup.sh dumps everything without stopping it, and scripts/restore.sh brings one database back
#     (refusing to overwrite without --replace).
# CI runs it on every change; `make smoke` runs it locally. It never touches a real installation on the same Docker
# host: its own Compose project, settings from .env.example with CONFIG_ROOT in a temporary directory, no fixed
# container names, no published ports, its own network range, and a dummy Discord webhook (Diun posts nothing on its
# first check). Everything it created is removed on exit.
set -euo pipefail

project=homelab-mnemosyne-smoke
timeout=${SMOKE_TIMEOUT:-300}
root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=scripts/lib.sh
. "$root/scripts/lib.sh"

work=$(mktemp -d)
settings=$(grep -E '^[A-Z][A-Z0-9_]*=' "$root/.env.example")
while IFS='=' read -r key _; do unset "$key"; done <<<"$settings"
unset COMPOSE_PROFILES
export COMPOSE_PROJECT_NAME=$project
export COMPOSE_FILE=$root/compose.yaml:$work/override.yaml
export COMPOSE_ENV_FILES=$work/env
export MNEMOSYNE_DISCORD_WEBHOOK=https://discord.com/api/webhooks/0/smoke-test
# Outside the ranges Docker hands out by default (172.17-31, 192.168), so it is free on a CI runner.
subnet=${SMOKE_SUBNET:-10.213.47.0/24}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    compose ps --all || true
    compose logs --no-color --tail 50 || true
  fi
  compose down --remove-orphans --volumes --timeout 30 || true
  rm -rf "$work" 2>/dev/null || echo "note: couldn't remove $work entirely" >&2
  exit "$status"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

{
  printf '%s\n' "$settings" | grep -vE '^(CONFIG_ROOT|PUID|PGID|STACK_SUBNET|DB_CLIENT_SUBNET)='
  echo "CONFIG_ROOT=$work/config"
  echo "PUID=$(id -u)"
  echo "PGID=$(id -g)"
  echo "STACK_SUBNET=$subnet"
  # The test's clients run on the stack's own network.
  echo "DB_CLIENT_SUBNET=$subnet"
} >"$work/env"

# No fixed names and no published ports, so a real installation on this host is never in the way.
{
  echo "services:"
  for service in $(docker compose -f "$root/compose.yaml" --env-file "$work/env" config --services); do
    printf '  %s:\n    container_name: !reset null\n    ports: !reset []\n' "$service"
  done
} >"$work/override.yaml"

echo "== Secrets and certificate"
"$root/scripts/db.sh" init --tls-name smoke.test

echo "== Starting every service"
compose up -d --wait --wait-timeout "$timeout"

network=${project}_default
pg_image=$(compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["postgres"]["image"])')
maria_image=$(compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["mariadb"]["image"])')

# psql from another container on the network, as an app would connect; $1 is the password, $2 the connection string.
pg_client() {
  docker run --rm -i --network "$network" -e PGPASSWORD="$1" "$pg_image" \
    psql -X -q -v ON_ERROR_STOP=1 -tA "$2" "${@:3}"
}
maria_client() {
  docker run --rm -i --network "$network" -e MYSQL_PWD="$1" "$maria_image" mariadb -h mariadb "${@:2}"
}

echo "== PostgreSQL: an app's login and databases"
pw=$("$root/scripts/db.sh" create pg smoke smoke_main smoke_log)
[[ $pw =~ ^[0-9a-f]{48}$ ]] || fail "db.sh create didn't print a password"
pg_client "$pw" "host=postgres dbname=smoke_main user=smoke sslmode=require" \
  <<<"CREATE TABLE t (x int); INSERT INTO t VALUES (42);" || fail "the app can't use its database over TLS"
[ "$(pg_client "$pw" "host=postgres dbname=smoke_main user=smoke sslmode=require" -c 'SHOW ssl;')" = on ] ||
  fail "the connection isn't encrypted"
pg_client "$pw" "host=postgres dbname=smoke_log user=smoke sslmode=require" -c 'SELECT 1' >/dev/null ||
  fail "the app can't reach its second database"

other=$("$root/scripts/db.sh" create pg other other_main)
if pg_client "$pw" "host=postgres dbname=other_main user=smoke sslmode=require" -c 'SELECT 1' 2>/dev/null; then
  fail "a login reached another app's database"
fi
if pg_client "$other" "host=postgres dbname=smoke_main user=other sslmode=require" -c 'SELECT 1' 2>/dev/null; then
  fail "a login reached another app's database"
fi
superuser=$(cat "$work/config/postgres/secrets/postgres_password")
if pg_client "$superuser" "host=postgres dbname=postgres user=postgres sslmode=require" -c 'SELECT 1' 2>/dev/null; then
  fail "the superuser logged in over the network"
fi

kept=$("$root/scripts/db.sh" create pg smoke smoke_extra)
[ -z "$kept" ] || fail "creating a database for an existing login printed a new password"
pg_client "$pw" "host=postgres dbname=smoke_extra user=smoke sslmode=require" -c 'SELECT 1' >/dev/null ||
  fail "the existing login's password changed"
if "$root/scripts/db.sh" create pg smoke smoke_main 2>/dev/null; then fail "db.sh created a database twice"; fi

echo "== MariaDB: an app's user and database"
mpw=$("$root/scripts/db.sh" create mariadb smokem smokem_main)
maria_client "$mpw" -u smokem smokem_main <<<"CREATE TABLE t (x int); INSERT INTO t VALUES (42);" ||
  fail "the app can't use its MariaDB database"
if maria_client "$mpw" -u smokem -e 'SELECT 1' mysql 2>/dev/null; then fail "a user reached the mysql schema"; fi
root_pw=$(cat "$work/config/mariadb/secrets/root_password")
if maria_client "$root_pw" -u root -e 'SELECT 1' 2>/dev/null; then fail "root logged in over the network"; fi

echo "== Exporters"
# grep without -q reads to the end, so compose isn't killed by SIGPIPE (pipefail would see it fail).
compose exec -T postgres-exporter wget -q -O - http://127.0.0.1:9187/metrics | grep -x 'pg_up 1' >/dev/null ||
  fail "postgres-exporter isn't logged in"
compose exec -T mysqld-exporter wget -q -O - http://127.0.0.1:9104/metrics | grep -x 'mysql_up 1' >/dev/null ||
  fail "mysqld-exporter isn't logged in"

echo "== Backup and restore"
"$root/scripts/backup.sh" "$work/backup"
for f in VERSION SHA256SUMS postgres/globals.sql postgres/smoke_main.dump postgres/smoke_log.dump \
  postgres/other_main.dump mariadb/users.sql mariadb/smokem_main.sql.gz; do
  [ -s "$work/backup/$f" ] || fail "the backup has no $f"
done
[ "$(stat -c %a "$work/backup")" = 700 ] || fail "the backup is readable by others"
[ "$(compose ps --status running --quiet | wc -l)" -eq "$(compose config --services | wc -l)" ] ||
  fail "a service stopped during the backup"

pg_client "$pw" "host=postgres dbname=smoke_main user=smoke sslmode=require" <<<"DROP TABLE t;"
maria_client "$mpw" -u smokem smokem_main <<<"DROP TABLE t;"
if "$root/scripts/restore.sh" "$work/backup" pg smoke_main 2>/dev/null; then
  fail "restore.sh replaced a database without --replace"
fi
"$root/scripts/restore.sh" "$work/backup" pg smoke_main --replace
"$root/scripts/restore.sh" "$work/backup" mariadb smokem_main --replace
[ "$(pg_client "$pw" "host=postgres dbname=smoke_main user=smoke sslmode=require" -c 'SELECT x FROM t;')" = 42 ] ||
  fail "the PostgreSQL database didn't come back"
if pg_client "$other" "host=postgres dbname=smoke_main user=other sslmode=require" -c 'SELECT 1' 2>/dev/null; then
  fail "the restored database lost its CONNECT restriction"
fi
[ "$(maria_client "$mpw" -u smokem -N -B smokem_main -e 'SELECT x FROM t;')" = 42 ] ||
  fail "the MariaDB database didn't come back"
"$root/scripts/restore.sh" "$work/backup" pg-roles >/dev/null
"$root/scripts/restore.sh" "$work/backup" mariadb-users >/dev/null
compose exec -T postgres-exporter wget -q -O - http://127.0.0.1:9187/metrics | grep -x 'pg_up 1' >/dev/null ||
  fail "restoring the roles changed the exporter's login"

echo "== New passwords"
new=$("$root/scripts/db.sh" password pg smoke)
pg_client "$new" "host=postgres dbname=smoke_main user=smoke sslmode=require" -c 'SELECT 1' >/dev/null ||
  fail "the new password doesn't work"
if pg_client "$pw" "host=postgres dbname=smoke_main user=smoke sslmode=require" -c 'SELECT 1' 2>/dev/null; then
  fail "the old password still works"
fi
mnew=$("$root/scripts/db.sh" password mariadb smokem)
maria_client "$mnew" -u smokem -e 'SELECT 1' smokem_main >/dev/null || fail "the new MariaDB password doesn't work"

echo "== Every service still healthy"
compose up -d --wait --wait-timeout 60 >/dev/null
echo "Smoke test passed"
