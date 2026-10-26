# Installing

From an empty Proxmox cluster to a running stack: the VM, its replication and HA, the stack, TLS, backups, and
Argus. Host names, addresses and the backup server's name are your own and stay out of this repository.

- [The VM](#the-vm)
- [Replication and HA](#replication-and-ha)
- [The stack](#the-stack)
- [Where data lives](#where-data-lives)
- [TLS](#tls)
- [Scheduled backups](#scheduled-backups)
- [Whole-VM backups](#whole-vm-backups)
- [Metrics in Argus](#metrics-in-argus)
- [Sizing](#sizing)
- [Drills before the first app moves](#drills-before-the-first-app-moves)

## The VM

One Ubuntu Server 24.04 VM, created on the node that normally runs it, with every disk on that node's ZFS
storage (replication needs every disk of the VM on ZFS).

| Setting | Value | Why |
| --- | --- | --- |
| Machine | q35, UEFI (OVMF) | |
| CPU type | a model both nodes support, such as `x86-64-v2-AES` | not `host`: after a failover the VM boots on the other node's CPU, and a live migration needs the same model on both |
| Cores, memory | 4, 8 GiB (no ballooning) | [Sizing](#sizing); a database wants its memory to stay put |
| Disk 1 (OS) | 32 GiB, VirtIO SCSI single, `discard=on`, `iothread=1`, `ssd=1` | |
| Disk 2 (data) | 64 GiB or more, same options, mounted at the parent of `CONFIG_ROOT` (for example `/srv`) | the databases; grows on its own, apart from the OS |
| Network | VirtIO, on the servers' VLAN, a fixed address (static or a DHCP reservation) | every app points at it |
| QEMU guest agent | on, and `qemu-guest-agent` installed in the VM | consistent snapshots (fs-freeze) for backups, clean shutdowns |

Format the data disk ext4 or XFS inside the VM. PostgreSQL's checksums (`--data-checksums`, set at initdb) and
ZFS's own catch corruption on either layer.

**ZFS on a hardware RAID controller.** ZFS expects to see the disks itself. On a RAID virtual disk it still works
and replicates, but it can't repair what it detects (it has one copy of each block) and it can't see a failing disk;
the controller's cache must not lie about flushes (battery-backed, or write-through). Putting the controller in HBA
mode (many PERCs can be crossflashed to IT mode) and letting ZFS mirror the disks is what Proxmox recommends.
Either way, the second node's pool must have the **same storage ID** in Proxmox and room for the VM's disks.

Then, in the VM: Docker Engine with the Compose plugin (Docker's own apt repository), the user that will own the
data in the `docker` group, and `rsync`, `openssl` and `git`.

## Replication and HA

**Replication** copies the VM's disks to the other node as ZFS snapshots on a schedule: Datacenter → Replication →
Add, target the other node, schedule `*/5` (every five minutes; `*/1` is the shortest). It is asynchronous: when the
running node dies, the copy is up to one interval old.

**HA** restarts the VM on the other node from that copy when the running node fails: Datacenter → HA → Resources →
Add (the VM, state `started`), and a node-affinity rule preferring the usual node so it moves back once that node
returns. The cluster needs quorum to do it, which the QDevice gives a two-node cluster. A node that loses quorum
fences itself (the watchdog reboots it), so the VM never runs twice.

What a failover means for the databases:

- **PostgreSQL and MariaDB start from a crash-consistent copy**, as after a power cut: each replays its log
  (WAL, redo log) and comes up with every transaction committed before the snapshot. Transactions committed in the
  last replication interval before the failure are lost. For the homelab's apps (download history, settings
  edits) that is minutes of work at most; nothing here is a ledger.
- **The apps reconnect on their own** once the address answers again (the VM keeps its address); a few log errors
  in between are expected. Diun and the exporters start with the stack.
- **The replication direction follows the VM**: the job now copies from the node it runs on.

Test it before any app depends on it ([drills](#drills-before-the-first-app-moves)).

## The stack

As the user who will own the data (`PUID`), in their home directory:

```sh
git clone https://github.com/HoneyBearTech/homelab-mnemosyne.git && cd homelab-mnemosyne
cp .env.example .env && chmod 600 .env
$EDITOR .env                       # PUID/PGID (id -u, id -g), CONFIG_ROOT, DB_CLIENT_SUBNET, sizing
scripts/db.sh init --tls-name db.example.com --tls-name db   # asks for the Discord webhook
docker compose up -d --wait
scripts/db.sh list
```

`db.sh init` creates the folders, passwords and certificate under `CONFIG_ROOT` and never overwrites one that
exists. Create the Discord webhook first: in the channel that should get the alerts, Edit Channel → Integrations →
Webhooks → New Webhook → Copy Webhook URL.

On the first start each engine initialises its data directory and runs its script in `initdb/` (the exporters'
accounts). Both exporters wait for their engine to be healthy; Diun's first check records what exists and posts
nothing.

When the stack follows `main` through the homelab's pull agent, install it for this host as on the others; the
agent then applies every merge (see the cautions in [upgrading.md](upgrading.md)).

## Where data lives

Each service's data is under `CONFIG_ROOT/<service>/`, on the VM's data disk: nothing in named Docker volumes, and
`CONFIG_ROOT` never inside `/var/lib/docker/volumes`. `docker volume prune`, `docker system prune --volumes` and
Portainer's "remove unused volumes" delete every volume no container mounts *as a volume*, including one whose
`_data` folder a service bind-mounts by path: that is how a prune deleted two apps' data in this homelab. The full
list of files is in [interfaces.md](interfaces.md#files-under-config_root).

## TLS

PostgreSQL requires a certificate to start (`ssl=on`); `db.sh init` makes a self-signed one, valid for ten years,
for the names given with `--tls-name`. With it, clients that only ask for encryption (`sslmode=require`, or the
default `prefer`) are encrypted; clients that verify the server (`verify-ca`, `verify-full`) need a certificate from
a CA they trust. To use your own CA, replace `CONFIG_ROOT/postgres/tls/server.crt` and `server.key` (key 0600, both
owned by `PUID`) and restart PostgreSQL (`docker compose restart postgres`); give the clients the CA certificate.

MariaDB makes and rotates its own certificate (11.4 and later) and offers TLS without configuration; its own
clients verify it through the password exchange. Neither engine requires TLS: an app that can't do it still
connects, with its password protected by SCRAM (PostgreSQL) or the native challenge (MariaDB), and only from
`DB_CLIENT_SUBNET`.

## Scheduled backups

`scripts/scheduled-backup.sh` runs `scripts/backup.sh` (a dump of every database and the accounts, nothing
stopped), copies it to the backup server with rsync over SSH (encrypted with age, when `BACKUP_AGE_RECIPIENT` is
set), keeps the newest few in each place, and tells an Uptime Kuma push monitor how it went.

1. On the backup server (a NAS, for example): a user used only for this, with SSH enabled for it, a shared folder
   it can write, and rsync available.
2. On the VM, as `PUID`: a key used only for this (`ssh-keygen -t ed25519 -f ~/.ssh/db-backup -N ''`), its public
   half in that user's `authorized_keys`, and an alias in `~/.ssh/config`:

   ```text
   Host backup-host
     HostName <the backup server>
     User <that user>
     IdentityFile ~/.ssh/db-backup
     IdentitiesOnly yes
   ```

   `ssh backup-host true` must work without a prompt. A firewall between the servers' VLAN and the backup server's
   must allow the VM to reach it on TCP 22.
3. **The encryption key** (optional, recommended), on another machine you trust (not this VM):
   `age-keygen -o mnemosyne-backup.key`. It prints the public key (`age1...`). Keep the key file where you keep your
   other recovery secrets, such as a password manager, and never copy it to the VM: without it no encrypted backup
   off the host can be read, and with it any of them can. On the VM: `sudo apt install -y age`.
4. `cp backup.env.example backup.env && chmod 600 backup.env`, and set `BACKUP_REMOTE` (such as
   `backup-host:/volume1/backups/mnemosyne`), `BACKUP_AGE_RECIPIENT=age1...` (the public key from step 3; leave it
   empty to copy the dumps as they are) and `BACKUP_PING_URL` (an Uptime Kuma push monitor with a 25-hour
   heartbeat). With `BACKUP_AGE_RECIPIENT`, the copy off the host is one folder per backup holding only
   `backup.tar.age` and its `SHA256SUMS`; the backups in `BACKUP_DIR` on the VM stay as they are.
5. Run it once by hand (`scripts/scheduled-backup.sh`), then install the timer:

   ```sh
   mkdir -p ~/.config/systemd/user && cp deploy/systemd/homelab-mnemosyne-backup.* ~/.config/systemd/user/
   systemctl --user daemon-reload && systemctl --user enable --now homelab-mnemosyne-backup.timer
   sudo loginctl enable-linger "$USER"   # user timers run without a login session
   ```

The dumps hold every app's data and the accounts' password hashes: the backup directory is 0700, and the copy on
the backup server should be readable only by that user, or encrypted (step 3) so that the backup server holds
nothing it can read. An encrypted copy is opened with the private key as [rebuilding.md](rebuilding.md) shows.

## Whole-VM backups

The dumps restore one database at a time; a whole-VM backup restores the server. In Proxmox, add the backup
server as storage (NFS or SMB, content "VZDump backup file") and a weekly backup job for this VM in snapshot mode
(the guest agent freezes the file systems for a consistent image). The two cover each other: a vzdump image is the
quickest way back after losing both nodes; a dump is the way to undo one app's bad migration.

## Metrics in Argus

Add the two exporters to Argus' Prometheus targets (`<VM>:9187`, `<VM>:9104`). The usual dashboards are the
community ones for postgres_exporter and mysqld_exporter; `pg_up` and `mysql_up` dropping to 0 are the alerts that
matter, together with the database's size and connections near `max_connections`.

## Sizing

The defaults fit an 8 GiB VM: `shared_buffers` 2 GB (a quarter of memory), `effective_cache_size` 5 GB, MariaDB's
buffer pool 512 MB, the rest for the OS cache. `max_connections` 300 covers the homelab's apps together (each
*arr app keeps a pool of a few per database; Seerr up to 10); watch `pg_stat_activity` (Argus) and raise it if the
total gets close. Each connection costs memory, so add RAM before raising it far.

## Drills before the first app moves

1. **A restore.** Create a test login and database, write a row, run `scripts/backup.sh`, drop the table,
   `scripts/restore.sh <dir> pg <db> --replace`, read the row.
2. **The nightly run.** `scripts/scheduled-backup.sh`: the copy arrives on the backup server and the push monitor
   goes up. With `BACKUP_AGE_RECIPIENT` set, open that copy with the private key on the machine that holds it
   ([rebuilding.md](rebuilding.md), step 2) and check its `SHA256SUMS`.
3. **A failover.** With the test database open from another host, shut down the node the VM runs on (or put it in
   maintenance). The VM must start on the other node within a couple of minutes, keep its address, and the client
   reconnect. Bring the node back and let the VM move home.
4. **An alert.** `docker compose exec diun diun notif test` posts a test message to the Discord channel.
