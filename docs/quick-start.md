# Quick start

On an Ubuntu VM with Docker Engine and the Compose plugin, as the user that will own the data
([installing.md](installing.md) has the VM, replication, HA and backups):

```sh
git clone https://github.com/HoneyBearTech/homelab-mnemosyne.git && cd homelab-mnemosyne
cp .env.example .env && chmod 600 .env && $EDITOR .env   # PUID, PGID, CONFIG_ROOT, DB_CLIENT_SUBNET
scripts/db.sh init --tls-name db.example.com             # passwords, certificate; asks for the Discord webhook
docker compose up -d --wait
scripts/db.sh create pg myapp myapp_main                 # prints myapp's password once
```

The app then connects to the VM's address on port 5432 as `myapp`, database `myapp_main`. Per-app settings for the
homelab's apps are in [migrating.md](migrating.md).
