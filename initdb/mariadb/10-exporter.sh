# shellcheck shell=bash
# Sourced (not executable on purpose) by the mariadb image's entrypoint on the first start only (an empty data
# directory), against its temporary server, which listens on the socket only; docker_process_sql is the
# entrypoint's own, already logged in as root. Creates the exporter's user for this stack's network (STACK_SUBNET,
# in MariaDB's address/netmask form) with the rights mysqld_exporter documents, and nothing else.

# 172.30.0.0/24 -> 172.30.0.0/255.255.255.0
mnemosyne_netmask_form() {
  local addr=${1%/*} bits=${1#*/} mask="" octet
  for _ in 1 2 3 4; do
    if ((bits >= 8)); then octet=255; bits=$((bits - 8)); else octet=$((256 - 2 ** (8 - bits))); bits=0; fi
    mask+=${mask:+.}$octet
  done
  printf '%s/%s' "$addr" "$mask"
}

if ! [[ $STACK_SUBNET =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$ ]]; then
  echo "error: STACK_SUBNET must be an IPv4 range such as 172.30.0.0/24, not '$STACK_SUBNET'" >&2
  return 1
fi
mnemosyne_password=$(cat "$EXPORTER_PASSWORD_FILE")
# scripts/db.sh writes hex; anything else could break out of the quotes below.
if ! [[ $mnemosyne_password =~ ^[A-Za-z0-9]{16,}$ ]]; then
  echo "error: $EXPORTER_PASSWORD_FILE must hold letters and digits only (scripts/db.sh init writes one)" >&2
  return 1
fi
mnemosyne_host=$(mnemosyne_netmask_form "$STACK_SUBNET")
docker_process_sql --database=mysql <<SQL
CREATE USER 'exporter'@'$mnemosyne_host' IDENTIFIED BY '$mnemosyne_password' WITH MAX_USER_CONNECTIONS 3;
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'exporter'@'$mnemosyne_host';
SQL
unset mnemosyne_password mnemosyne_host
