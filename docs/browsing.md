# Browsing the databases

[DbGate](https://dbgate.org) shows both engines in a browser: every database, its tables and views, their columns,
keys and indexes, sizes, and an ER diagram of a database's tables. It runs in the stack (`dbgate` in
`compose.yaml`) and sees only the databases' **structure**: its login can't read a single row. For the engines'
metrics (connections, sizes over time, activity) use Argus' Databases dashboard instead.

- [On an installation from before DbGate](#on-an-installation-from-before-dbgate)
- [Once: its login](#once-its-login)
- [Opening it](#opening-it)
- [What it can and can't do](#what-it-can-and-cant-do)
- [A new password](#a-new-password)

## On an installation from before DbGate

DbGate needs a setting and a folder an older installation doesn't have. Without the setting, `docker compose`
refuses the whole file, so the pull agent's deploy stops (`required variable DBGATE_PORT is missing a value`),
moves the checkout back and changes nothing; without the folder, Docker creates it as root and DbGate can't write
to it. Before the merge that brings DbGate (or after such a failed deploy), on the VM:

```sh
printf 'DBGATE_PORT=3000\n' >> .env
mkdir -p "<CONFIG_ROOT>/dbgate/config"   # as PUID; or `scripts/db.sh init` once the checkout has DbGate
```

After a failed deploy the agent waits before it tries the same commit again; to deploy now, start its service
(`systemctl --user start homelab-pull@mnemosyne.service`).

## Once: its login

DbGate logs in as `dbviewer`, which `scripts/db.sh` creates on each engine. On the VM, in the checkout, with the
stack running:

```sh
scripts/db.sh viewer pg
scripts/db.sh viewer mariadb
```

Each prints the new login's password once: keep both in your password manager. DbGate asks for them; the VM keeps
neither. Running `viewer` again keeps the password and gives `dbviewer` `CONNECT` on any database it hasn't got yet
(after a restore, say); `scripts/db.sh create` gives it each new database itself.

## Opening it

DbGate answers on `127.0.0.1` on the VM only, so open an SSH tunnel to it from your own computer (`DBGATE_PORT` in
`.env`, 3000 by default):

```sh
ssh -N -L 3000:127.0.0.1:3000 <the VM>
```

Then open <http://localhost:3000>. The two connections, **PostgreSQL** and **MariaDB**, are already there; opening
one asks for `dbviewer`'s password for that engine. Close the tunnel (Ctrl-C) when you're done: nothing else can
reach the page.

## What it can and can't do

| It can | It can't |
| --- | --- |
| List every database on both engines, with its tables, views, columns, types, defaults, keys and indexes | Show a table's rows, or count them (other than the planner's estimate) |
| Draw a database's tables and the foreign keys between them | Change anything: both connections are read-only, and `dbviewer` owns nothing and has no right to write |
| Show each database's and table's size | See other sessions' queries (`dbviewer` isn't in `pg_monitor`) |

Most apps' schemas (the *arr apps') have few foreign keys, so their diagrams are mostly tables side by side; an
app whose migrations declare its relations (Steerhouse) draws them.

DbGate has no login page of its own. Its page is reachable only from the VM itself, and without `dbviewer`'s
password it opens no database. It calls out only when you ask it to (its changelog, its plugin catalogue), and its
usage analytics are off. What it keeps (saved scripts, its settings and logs) is in `CONFIG_ROOT/dbgate/config`,
holds no password, and isn't in the backups: nothing in it is hard to recreate.

## A new password

```sh
scripts/db.sh password pg dbviewer
scripts/db.sh password mariadb dbviewer
```

Each prints the new password once; replace the one in your password manager.
