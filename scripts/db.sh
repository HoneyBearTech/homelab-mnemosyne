#!/usr/bin/env bash
# Set up the stack's secrets, and give each app its own login and databases on one of the two engines.
#
#   scripts/db.sh init [--tls-name NAME]...   create the folders, passwords and certificate the stack needs (once,
#                                             before the first `docker compose up`; never overwrites one that exists)
#   scripts/db.sh create pg LOGIN DB...       a PostgreSQL login role owning these databases (new ones)
#   scripts/db.sh create mariadb LOGIN DB...  a MariaDB user with every right on these databases (new ones)
#   scripts/db.sh password pg|mariadb LOGIN   give an existing login a new password
#   scripts/db.sh list                        every database on both engines, its owner and size
#
# A new login's password is printed once, on stdout, and kept nowhere here: put it straight into the app's settings
# on its own host. Creating databases for a login that already exists leaves its password alone.
#
# Names are lowercase letters, digits and underscores, starting with a letter, at most 63 characters (PostgreSQL's
# limit; MariaDB's for users is 80): `sonarr_main`, not `sonarr-main`. Each PostgreSQL database may be connected to
# only by its owner (CONNECT is revoked from PUBLIC); each MariaDB user may log in only from DB_CLIENT_SUBNET.
#
# The stack's settings come from .env (COMPOSE_ENV_FILES or the environment override it, as in the smoke test).
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=scripts/lib.sh
. "$root/scripts/lib.sh"

name_re='^[a-z][a-z0-9_]{0,62}$'
# The engines' own accounts and databases, and the stack's: never handed to an app.
reserved=" postgres template0 template1 metrics pg_monitor public mysql sys information_schema performance_schema
  root exporter healthcheck mariadb mariadb_sys "

usage() {
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

check_name() {
  if ! [[ $1 =~ $name_re ]]; then
    echo "error: '$1' isn't a valid name: lowercase letters, digits and _, starting with a letter, at most 63" >&2
    exit 2
  fi
  if [[ $reserved == *" $1 "* ]]; then
    echo "error: '$1' is reserved for the engines or the stack" >&2
    exit 2
  fi
}

new_password() { openssl rand -hex 24; }

# --- init -------------------------------------------------------------------------------------------------------

# Writes $2 to file $1 (mode 0600) unless it already exists.
keep_or_write() {
  if [ -s "$1" ]; then
    echo "  kept    $1"
  else
    (umask 077 && printf '%s' "$2" >"$1")
    echo "  created $1"
  fi
}

init() {
  local config_root puid pgid tls_names=() dir pw webhook san
  while [ $# -gt 0 ]; do
    case $1 in
      --tls-name)
        tls_names+=("${2:?--tls-name needs a name}")
        shift 2
        ;;
      *) usage ;;
    esac
  done
  config_root=$(setting CONFIG_ROOT)
  puid=$(setting PUID)
  pgid=$(setting PGID)
  case $config_root in /var/lib/docker/*)
    echo "error: CONFIG_ROOT must not be inside /var/lib/docker: a volume prune would delete it" >&2
    exit 1
    ;;
  esac
  if [ "$(id -u)" != 0 ] && [ "$(id -u)" != "$puid" ]; then
    echo "error: run this as the user PUID names ($puid), who owns the data, or as root" >&2
    exit 1
  fi
  command -v openssl >/dev/null || {
    echo "error: openssl is needed for the passwords and the certificate" >&2
    exit 1
  }

  echo "Folders under $config_root"
  for dir in postgres/config postgres/tls postgres/secrets mariadb/config mariadb/secrets \
    mysqld-exporter/secrets diun/config diun/secrets; do
    mkdir -p "$config_root/$dir"
    case $dir in */secrets | */tls) chmod 700 "$config_root/$dir" ;; esac
  done

  echo "Passwords (random, 48 hex digits)"
  keep_or_write "$config_root/postgres/secrets/postgres_password" "$(new_password)"
  keep_or_write "$config_root/postgres/secrets/metrics_password" "$(new_password)"
  keep_or_write "$config_root/mariadb/secrets/root_password" "$(new_password)"
  keep_or_write "$config_root/mariadb/secrets/exporter_password" "$(new_password)"
  pw=$(cat "$config_root/mariadb/secrets/exporter_password")
  keep_or_write "$config_root/mysqld-exporter/secrets/my.cnf" "$(printf '[client]\nuser=exporter\npassword=%s\n' "$pw")"

  echo "Discord webhook for Diun"
  webhook=${MNEMOSYNE_DISCORD_WEBHOOK:-}
  if [ ! -s "$config_root/diun/secrets/discord_webhook" ] && [ -z "$webhook" ] && [ -t 0 ]; then
    read -r -s -p "  Paste the channel's webhook URL (Server Settings > Integrations > Webhooks): " webhook
    echo
  fi
  if [ ! -s "$config_root/diun/secrets/discord_webhook" ]; then
    if ! [[ $webhook =~ ^https://(discord|discordapp)\.com/api/webhooks/ ]]; then
      echo "error: no Discord webhook URL (https://discord.com/api/webhooks/...); set MNEMOSYNE_DISCORD_WEBHOOK or" \
        "run this in a terminal" >&2
      exit 1
    fi
  fi
  keep_or_write "$config_root/diun/secrets/discord_webhook" "$webhook"

  echo "PostgreSQL's TLS certificate"
  if [ -s "$config_root/postgres/tls/server.crt" ] && [ -s "$config_root/postgres/tls/server.key" ]; then
    echo "  kept    $config_root/postgres/tls/server.crt"
  else
    if [ ${#tls_names[@]} -eq 0 ]; then tls_names=("$(hostname -f 2>/dev/null || hostname)"); fi
    san=$(printf 'DNS:%s,' "${tls_names[@]}")
    # Self-signed, for ten years: clients that only encrypt (sslmode=require, the default `prefer`) accept it. Replace
    # both files with a pair from your own CA for clients that verify (docs/installing.md#tls).
    (umask 077 && openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3650 \
      -subj "/CN=${tls_names[0]}" -addext "subjectAltName=${san%,}" \
      -keyout "$config_root/postgres/tls/server.key" -out "$config_root/postgres/tls/server.crt" 2>/dev/null)
    chmod 644 "$config_root/postgres/tls/server.crt"
    echo "  created $config_root/postgres/tls/server.crt (self-signed for ${tls_names[*]})"
  fi

  if [ "$(id -u)" = 0 ]; then
    for dir in postgres mariadb mysqld-exporter diun; do chown -R "$puid:$pgid" "$config_root/$dir"; done
  fi
  echo "Done. Next: docker compose up -d --wait"
}

# --- create / password ------------------------------------------------------------------------------------------

# A role or database name is checked against name_re before it gets here, so it can be written into SQL as is; the
# password (hex) too. Everything goes in on stdin: nothing secret appears in a process's arguments on the host.
pg_count() { pg_sql -tA -d postgres <<<"$1"; }

pg_create() {
  local login=$1 db pw="" sql
  shift
  local n
  for db in "$@"; do
    n=$(pg_count "SELECT count(*) FROM pg_database WHERE datname = '$db';")
    if [ "$n" != 0 ]; then
      echo "error: database $db already exists on PostgreSQL; nothing was changed" >&2
      exit 1
    fi
  done
  sql=""
  n=$(pg_count "SELECT count(*) FROM pg_roles WHERE rolname = '$login';")
  if [ "$n" = 0 ]; then
    pw=$(new_password)
    sql+="CREATE ROLE \"$login\" LOGIN PASSWORD '$pw';"$'\n'
  fi
  for db in "$@"; do
    # psql sends each statement on its own (CREATE DATABASE can't run inside a transaction block).
    sql+="CREATE DATABASE \"$db\" OWNER \"$login\";"$'\n'
    sql+="REVOKE CONNECT, TEMPORARY ON DATABASE \"$db\" FROM PUBLIC;"$'\n'
    sql+="GRANT CONNECT, TEMPORARY ON DATABASE \"$db\" TO \"$login\";"$'\n'
  done
  pg_sql -d postgres <<<"$sql"
  report pg "$login" "$pw" "$@"
}

maria_create() {
  local login=$1 db pw="" exists host sql
  shift
  host=$(netmask_form "$(setting DB_CLIENT_SUBNET)")
  exists=$(maria_sql -N -B <<<"SELECT COUNT(*) FROM mysql.global_priv WHERE User = '$login';")
  local n
  for db in "$@"; do
    n=$(maria_sql -N -B <<<"SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '$db';")
    if [ "$n" != 0 ]; then
      echo "error: database $db already exists on MariaDB; nothing was changed" >&2
      exit 1
    fi
  done
  sql=""
  if [ "$exists" = 0 ]; then
    pw=$(new_password)
    sql+="CREATE USER '$login'@'$host' IDENTIFIED BY '$pw';"$'\n'
  fi
  for db in "$@"; do
    sql+="CREATE DATABASE \`$db\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"$'\n'
    sql+="GRANT ALL PRIVILEGES ON \`$db\`.* TO '$login'@'$host';"$'\n'
  done
  maria_sql <<<"$sql"
  report mariadb "$login" "$pw" "$@"
}

report() {
  local engine=$1 login=$2 pw=$3
  shift 3
  echo "Created on $engine: $* (owned by $login)" >&2
  if [ -n "$pw" ]; then
    echo "New login $login. Its password, shown this once; put it in the app's settings now:" >&2
    printf '%s\n' "$pw"
  else
    echo "$login already existed; its password is unchanged." >&2
  fi
}

password() {
  local engine=$1 login=$2 pw host n
  pw=$(new_password)
  case $engine in
    pg)
      n=$(pg_count "SELECT count(*) FROM pg_roles WHERE rolname = '$login';")
      if [ "$n" = 0 ]; then
        echo "error: there is no PostgreSQL login $login" >&2
        exit 1
      fi
      pg_sql -d postgres <<<"ALTER ROLE \"$login\" PASSWORD '$pw';"
      ;;
    mariadb)
      host=$(netmask_form "$(setting DB_CLIENT_SUBNET)")
      n=$(maria_sql -N -B <<<"SELECT COUNT(*) FROM mysql.global_priv WHERE User = '$login';")
      if [ "$n" = 0 ]; then
        echo "error: there is no MariaDB user $login" >&2
        exit 1
      fi
      maria_sql <<<"ALTER USER '$login'@'$host' IDENTIFIED BY '$pw';"
      ;;
  esac
  echo "New password for $login on $engine, shown this once; the app needs it before its next connection:" >&2
  printf '%s\n' "$pw"
}

list() {
  echo "PostgreSQL"
  pg_sql -d postgres -P footer=off <<'SQL'
SELECT d.datname AS database, pg_get_userbyid(d.datdba) AS owner,
       pg_size_pretty(pg_database_size(d.datname)) AS size
FROM pg_database d WHERE NOT d.datistemplate ORDER BY 1;
SQL
  echo
  echo "MariaDB"
  maria_sql -t <<'SQL'
SELECT s.SCHEMA_NAME AS `database`,
       CONCAT(ROUND(COALESCE(SUM(t.DATA_LENGTH + t.INDEX_LENGTH), 0) / 1048576, 1), ' MB') AS size
FROM information_schema.SCHEMATA s LEFT JOIN information_schema.TABLES t ON t.TABLE_SCHEMA = s.SCHEMA_NAME
WHERE s.SCHEMA_NAME NOT IN ('mysql', 'sys', 'information_schema', 'performance_schema')
GROUP BY s.SCHEMA_NAME ORDER BY 1;
SQL
}

engine_arg() {
  case ${1:-} in
    pg | postgres) echo pg ;;
    mariadb | mysql) echo mariadb ;;
    *)
      echo "error: the engine is pg or mariadb, not '${1:-}'" >&2
      exit 2
      ;;
  esac
}

main() {
  local engine name
  case ${1:-} in
    init)
      shift
      init "$@"
      ;;
    create)
      [ $# -ge 4 ] || usage
      engine=$(engine_arg "$2")
      shift 2
      for name in "$@"; do check_name "$name"; done
      if [ "$engine" = pg ]; then pg_create "$@"; else maria_create "$@"; fi
      ;;
    password)
      [ $# -eq 3 ] || usage
      engine=$(engine_arg "$2")
      check_name "$3"
      password "$engine" "$3"
      ;;
    list)
      [ $# -eq 1 ] || usage
      list
      ;;
    *) usage ;;
  esac
}

main "$@"
