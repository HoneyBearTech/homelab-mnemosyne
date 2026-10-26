# homelab-mnemosyne

The Docker Compose stack for Mnemosyne, the homelab's shared database server (an Ubuntu 24.04 VM on Proxmox, amd64,
replicated to the second node with ZFS and restarted there by HA): one PostgreSQL and one MariaDB that the other
stacks' apps connect to, each with its own login and databases; postgres_exporter and mysqld_exporter for Argus; and
Diun, which posts new engine releases and rebuilds to Discord. Every image pinned by tag and digest so the server
can be upgraded and rebuilt from this repository. Its nightly dumps go off the host.

## Before Making Structural Changes
Read the project's notes first. They live outside this repo, in the owner's Obsidian vault **Chronos** at
`~/Chronos/Projects/homelab-mnemosyne/` (every file is prefixed `homelab-mnemosyne-`):
- `homelab-mnemosyne-roadmap.md`: phases with checkboxes (the VM, the drills, each app's move), the owner's open
  questions and manual steps
- `homelab-mnemosyne-Architecture.md`: the host facts (nodes, addresses, the backup server), the inventory of which
  app on which stack uses which database, and the migration plan
- `homelab-mnemosyne-Decisions-Log.md`: ADR-style log (entries marked **Proposed** still need the owner's call)

Keep them current as work lands. **The notes never go into this repo.** Chronos is versioned in its own private
repo; only commit or push it when the owner asks.

The sibling repos `~/GitHub/homelab-ares` (the template), `-atlas`, `-deimos`, `-helios` and `-hyperion` follow the
same pattern. Tooling that isn't specific to this stack (`check_compose.py`, `scheduled-backup.sh`, `deploy_lock`
in `lib.sh`, the workflows) is kept the same as ares'. This stack's backup, restore and smoke test are its own: it
dumps databases instead of archiving folders, and never stops a service to back it up.

## This repo is public
- No hostnames, IP addresses, internal or public domains, host paths, the backup server's name, Discord webhook
  URLs, or personal email addresses in anything committed: code, compose, docs, examples, tests, commit messages.
  Host facts live only in the Chronos notes. Examples use placeholders (`/srv/config`, `192.0.2.0/24`,
  `db.example.com`, `backup-host`).
- Commit as `31805425+HoneyBearTech@users.noreply.github.com` (set as this repo's `user.email`), with
  `git commit -s` for the DCO sign-off; commits and tags are SSH-signed.
- No secrets: passwords, the TLS key and the webhook are files under `CONFIG_ROOT/<service>/secrets` (and
  `postgres/tls`) on the host, created by `scripts/db.sh init`, never in `compose.yaml`, `.env` or the `*.example`
  files. An app's password is printed once by `db.sh` and kept only in that app's settings on its own host.
- Keep the repo on track for OpenSSF Baseline Levels 1 and 2 and the Best Practices badges (the project isn't
  registered on bestpractices.dev yet: an owner step). If a change would break a met criterion (unpinning an image
  or an Action, a workflow without `permissions:`, dropping the coverage floor), say so before making it.

## Rules for the stack
- **Every image is pinned as `name:tag@sha256:<digest>`.** Never `latest`, never tag-only.
- **The engines are upgraded by hand, never by Dependabot** (owner 2026-10-26). Dependabot ignores `postgres` and
  `mariadb`; Diun watches them (`diun/images.yml`) and alerts on Discord. An engine change is a PR that moves the tag
  and digest in `compose.yaml` and the tag in `diun/images.yml`'s `name` together (`scripts/check_watches.py` fails
  otherwise), follows `docs/upgrading.md`, and is merged by the owner at a quiet time: merging restarts every app's
  database. Claude never merges an engine change. A PostgreSQL major is a dump and restore (`docs/upgrading.md`).
  The exporters and Diun stay Dependabot's, auto-merged like the other stacks' images.
- **Access rules are load-bearing** (`docs/security.md#access-to-the-databases`): the PostgreSQL superuser is
  rejected for every network address, MariaDB's root exists for `localhost` only, app logins come only from
  `DB_CLIENT_SUBNET`, the exporters' only from `STACK_SUBNET`, and every database `db.sh` makes has `CONNECT`
  revoked from `PUBLIC`. Never loosen these; the smoke test and `tests/test_settings.py` prove them.
- **Nothing secret in a process's arguments**: SQL with passwords goes to `psql`/`mariadb` on stdin; containers
  read secret files (Docker secrets); `db.sh` validates every name against `^[a-z][a-z0-9_]{0,62}$` before it
  goes into SQL.
- **Every service is hardened** (`x-hardened`: `no-new-privileges`, `cap_drop: [ALL]`), runs as `PUID:PGID`, with a
  read-only root filesystem; none needs a capability back. No Docker socket anywhere (Diun uses the file provider).
  `scripts/check_compose.py` enforces the policy in CI and in the release workflow.
- **No autoheal on the engines**: restarting a database mid-recovery restarts the recovery; `restart:
  unless-stopped` covers crashes. Long `start_period` (10 min) and `stop_grace_period` (2 min) for the engines.
- **Every service has a health check.**
- **App data layout (as in all homelab stacks):** `CONFIG_ROOT/<service>/config` at the service's data path,
  other per-service folders beside it (`secrets`, `tls`); no named Docker volumes; `CONFIG_ROOT` never inside
  `/var/lib/docker/volumes` (a prune deleted two apps' data in this homelab, 2026-10-15).
- Every setting goes through `.env` (`${VAR:?…}` in compose) and is listed in `.env.example` and
  `docs/interfaces.md` (`tests/test_settings.py` checks both).
- **Never change the live server** without the owner asking: no `docker compose up`, no `db.sh create`, no SQL
  against the engines, no restores. Read-only inspection (`docker compose ps`, `db.sh list`) only when asked.
- **Moving an app here changes another stack** (its `<service>.env` and compose): that is a PR in that stack's
  repo, one app at a time, following `docs/migrating.md`, after the owner has created the app's login.

## Deploys
- A merge to `main` deploys once the pull agent (`homelab-pull@mnemosyne`, from the owner's private homelab-ops
  repo) is installed on the VM: it fast-forwards the checkout and runs `docker compose up -d --remove-orphans
  --wait`. Compose recreates only changed services, so an exporter or Diun bump doesn't touch the engines.
- Backups and restores hold the agent's lock (`deploy_lock` in `scripts/lib.sh`, same text as ares').
- The agent never installs systemd units: a change to `deploy/systemd/` needs a manual copy and
  `systemctl --user daemon-reload` on the host (say so in the PR).

## Commands
```sh
make test     # unit tests + coverage floor (no Docker, no network; scripts run against a stand-in docker)
make lint     # ruff check, ruff format --check, yamllint --strict, shellcheck -x (scripts and initdb)
make check    # policy check over the resolved Compose file, and the watch check (needs .env)
make watches  # scripts/check_watches.py alone
make smoke    # scripts/smoke-test.sh: throwaway project; logins, access rules, exporters, dump and restore
```
