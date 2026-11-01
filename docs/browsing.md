# Browsing the databases

[DbGate](https://dbgate.org) shows both engines in a browser: every database, its tables and views, their columns,
keys and indexes, sizes, and an ER diagram of a database's tables. It runs in the stack (`dbgate` in
`compose.yaml`) and sees only the databases' **structure**: its login can't read a single row. For the engines'
metrics (connections, sizes over time, activity) use Argus' Databases dashboard instead.

- [On an installation from before DbGate](#on-an-installation-from-before-dbgate)
- [Once: its login](#once-its-login)
- [Opening it](#opening-it)
- [Through a reverse proxy](#through-a-reverse-proxy)
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

## Through a reverse proxy

To open DbGate at a name of its own instead (`https://dbgate.example.com`), publish it on the VM's address and let
the reverse proxy alone reach it. DbGate has no login page, so the proxy's access rules are its only gate: anyone
who reaches the port reaches the page.

1. **Publish it on the VM's address.** In `.env`, set `DBGATE_BIND_ADDRESS` to the VM's address (never `0.0.0.0`:
   the rule below matches one address).

2. **Limit the port to the proxy.** Docker publishes the port with its own iptables rules, which run before UFW's:
   a `ufw allow` or `ufw deny` for it has no effect. Docker's `DOCKER-USER` chain is the place for rules that do
   apply; it sees a connection after Docker has rewritten its destination to the container's, so the rules match
   the destination the client asked for, which conntrack remembers. Add this at the end of `/etc/ufw/after.rules`
   (after the `COMMIT` that ends UFW's own `*filter` section), with your values: `192.0.2.20` is
   `DBGATE_BIND_ADDRESS`, `192.0.2.10` the reverse proxy, `3000` is `DBGATE_PORT`.

   ```text
   # homelab-mnemosyne: only the reverse proxy reaches DbGate (DBGATE_BIND_ADDRESS:DBGATE_PORT). Docker-published
   # ports bypass UFW's own rules; DOCKER-USER sees them after DNAT, so match the original destination.
   *filter
   :DOCKER-USER - [0:0]
   -A DOCKER-USER -p tcp -m conntrack --ctorigdst 192.0.2.20 --ctorigdstport 3000 --ctdir ORIGINAL -s 192.0.2.10 -j RETURN
   -A DOCKER-USER -p tcp -m conntrack --ctorigdst 192.0.2.20 --ctorigdstport 3000 --ctdir ORIGINAL -j DROP
   -A DOCKER-USER -j RETURN
   COMMIT
   ```

   Load it **before** changing the address, then look at the chain:

   ```sh
   sudo ufw reload
   sudo iptables -L DOCKER-USER -n -v      # the three rules, with packet counters
   ```

   The first rule lets the proxy through, the second drops every other connection to DbGate, and the third hands
   everything else back to Docker's own rules, so the engines' and exporters' ports are unchanged. UFW loads the
   file at every boot; Docker leaves an existing `DOCKER-USER` chain as it is. The rules are for Docker's default
   iptables backend.

3. **Deploy and test from both sides.** After the address change reaches the VM (the pull agent redeploys on the
   next merge; or `docker compose up -d dbgate` in the checkout):

   ```sh
   nc -zv -w 5 192.0.2.20 3000     # from the reverse proxy's host: "succeeded"
   nc -zv -w 5 192.0.2.20 3000     # from any other machine on the LAN: times out
   ```

4. **Add the proxy host.** Forward the name to `http://<DBGATE_BIND_ADDRESS>:<DBGATE_PORT>` with a TLS certificate,
   HTTPS forced, HSTS, and WebSocket upgrades allowed. Give it an access list that admits your LAN or VPN only
   **and** asks for a password (HTTP basic auth, or the proxy's single sign-on): that password is the page's login.
   DbGate's own `LOGIN`/`PASSWORD` settings take the password in an environment variable, which this stack doesn't
   do with secrets. Check from outside the LAN that the name is refused.

The hop from the proxy to DbGate is plain HTTP, so `dbviewer`'s password crosses the LAN in the clear when you
type it; only the proxy's host sits on that path. With the tunnel, nothing crosses unencrypted: prefer it if that
matters more to you than a name. To go back, remove `DBGATE_BIND_ADDRESS` from `.env` (or set it to `127.0.0.1`);
the `DOCKER-USER` block can stay.

## What it can and can't do

| It can | It can't |
| --- | --- |
| List every database on both engines, with its tables, views, columns, types, defaults, keys and indexes | Show a table's rows, or count them (other than the planner's estimate) |
| Draw a database's tables and the foreign keys between them | Change anything: both connections are read-only, and `dbviewer` owns nothing and has no right to write |
| Show each database's and table's size | See other sessions' queries (`dbviewer` isn't in `pg_monitor`) |

Most apps' schemas (the *arr apps') have few foreign keys, so their diagrams are mostly tables side by side; an
app whose migrations declare its relations (Steerhouse) draws them.

DbGate has no login page of its own. Its page is reachable only from the VM itself (or, behind a reverse proxy,
from the proxy's host, through its access list), and without `dbviewer`'s password it opens no database. It calls out only when you ask it to (its changelog, its plugin catalogue), and its
usage analytics are off. What it keeps (saved scripts, its settings and logs) is in `CONFIG_ROOT/dbgate/config`,
holds no password, and isn't in the backups: nothing in it is hard to recreate.

## A new password

```sh
scripts/db.sh password pg dbviewer
scripts/db.sh password mariadb dbviewer
```

Each prints the new password once; replace the one in your password manager.
