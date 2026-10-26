# Rebuilding the server

When the VM is gone and neither its replica nor a vzdump image will do (both nodes lost, or a corrupted pool), the
server is rebuilt from this repository and the nightly dumps.

1. A new VM and stack as in [installing.md](installing.md), up to `docker compose up -d --wait`. New secrets are
   fine: the stack's own accounts are never taken from a dump.
2. Copy the newest dump back from the backup server (`rsync -a backup-host:<path>/<date-time>/ ~/restore/`).

   **An encrypted copy** (the folder holds only `backup.tar.age` and `SHA256SUMS`, from `BACKUP_AGE_RECIPIENT`) is
   opened on the machine that holds the age private key, never on the backup server or the new VM. Check it there,
   decrypt it, which gives the backup directory as the old VM wrote it, and copy that to the new VM:

   ```sh
   rsync -rlpt backup-host:<path>/<date-time>/ ~/sealed/
   cd ~/sealed && sha256sum -c --quiet SHA256SUMS && cd -
   (umask 077 && age -d -i mnemosyne-backup.key ~/sealed/backup.tar.age | tar -x -C ~)   # ~/<date-time>/
   rsync -rlpt ~/<date-time>/ <you>@<the new VM>:restore/
   rm -rf ~/sealed ~/<date-time>
   ```

3. Restore the apps' accounts, then every database:

   ```sh
   scripts/restore.sh ~/restore pg-roles
   scripts/restore.sh ~/restore mariadb-users
   for f in ~/restore/postgres/*.dump; do scripts/restore.sh ~/restore pg "$(basename "$f" .dump)"; done
   for f in ~/restore/mariadb/*.sql.gz; do scripts/restore.sh ~/restore mariadb "$(basename "$f" .sql.gz)"; done
   ```

4. The apps' passwords are the ones they had (the dumps hold the hashes), so the apps reconnect once the VM answers
   on its old address. Check each one, then the nightly backup and the exporters.

A MariaDB user is restored for the range it was created for; if `DB_CLIENT_SUBNET` changed, give each user a new
password with `scripts/db.sh password mariadb <login>` after recreating it for the new range.
