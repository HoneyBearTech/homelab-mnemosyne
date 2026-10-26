# Helpers shared by db.sh, backup.sh, restore.sh and smoke-test.sh, which source this file; it isn't run on its own.
# Written for bash 3.2 and later (macOS ships 3.2).
# shellcheck shell=bash

# Backups and restores take turns with homelab-ops' pull agent, which takes `flock --nonblock` on
# <state root>/<pull_stack>/lock and skips its run when that's busy: deploy_lock waits for a deploy in progress, then
# holds that lock (fd 9) until the calling script exits. A no-op where the agent keeps no state for this stack (CI, a
# workstation). Kept the same as homelab-ares' (the template): another stack that copies this changes only pull_stack.
pull_stack=mnemosyne
deploy_lock_timeout=1800

deploy_lock() {
  local dir=${HOMELAB_PULL_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/homelab-pull}/$pull_stack
  if [ ! -d "$dir" ]; then return 0; fi
  if ! command -v flock >/dev/null; then
    echo "error: $dir exists (the pull agent deploys here) but flock isn't installed to lock it" >&2
    return 1
  fi
  exec 9>>"$dir/lock"
  if ! flock --nonblock 9; then
    echo "Waiting for a deploy by the pull agent to finish (up to $deploy_lock_timeout s)"
    if ! flock --timeout "$deploy_lock_timeout" 9; then
      echo "error: the pull agent's deploy of $pull_stack still holds $dir/lock after $deploy_lock_timeout s;" \
        "nothing was stopped (check: journalctl --user -u homelab-pull@$pull_stack)" >&2
      return 1
    fi
  fi
}

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

# The value of setting $1: from the environment when set there (the smoke test sets every setting), otherwise from
# the env file next to compose.yaml (.env, or the first file COMPOSE_ENV_FILES names). Read as data, never sourced.
setting() {
  local file line value
  if [ -n "${!1+set}" ]; then
    printf '%s' "${!1}"
    return 0
  fi
  file=${COMPOSE_ENV_FILES:-$root/.env}
  file=${file%%,*}
  if [ ! -f "$file" ]; then
    echo "error: $1 isn't set and there is no $file (cp .env.example .env)" >&2
    return 1
  fi
  line=$(grep -E "^$1=" "$file" | tail -n 1) || {
    echo "error: $1 isn't set in $file" >&2
    return 1
  }
  value=${line#*=}
  value=${value#\"}
  value=${value%\"}
  printf '%s' "$value"
}

# The stack's Compose command, from the checkout (compose.yaml and .env there, unless the caller's COMPOSE_* say
# otherwise, as in the smoke test).
compose() { (cd "$root" && docker compose "$@"); }

# psql as the superuser, through the socket inside the postgres container; SQL on stdin. Stops at the first error.
pg_sql() { compose exec -T postgres psql -X -q -v ON_ERROR_STOP=1 -U postgres "$@"; }

# The MariaDB client as root, through the socket inside the mariadb container; SQL on stdin. The password is read
# from the container's secret file, never passed as an argument.
maria_sql() {
  # shellcheck disable=SC2016 # expanded by the container's shell
  compose exec -T mariadb sh -c 'MYSQL_PWD=$(cat /run/secrets/mariadb_root_password) exec mariadb -uroot "$@"' \
    mariadb "$@"
}

# An IPv4 range in CIDR form (192.168.40.0/24) in MariaDB's address/netmask form (192.168.40.0/255.255.255.0),
# which a MariaDB account's host part accepts.
netmask_form() {
  local addr=${1%/*} bits=${1#*/} mask="" octet
  if ! [[ $1 =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$ ]]; then
    echo "error: '$1' isn't an IPv4 range such as 192.168.40.0/24" >&2
    return 1
  fi
  for _ in 1 2 3 4; do
    if ((bits >= 8)); then
      octet=255
      bits=$((bits - 8))
    else
      octet=$((256 - 2 ** (8 - bits)))
      bits=0
    fi
    mask+=${mask:+.}$octet
  done
  printf '%s/%s' "$addr" "$mask"
}
