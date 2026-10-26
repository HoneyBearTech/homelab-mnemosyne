#!/bin/sh
# Run by the postgres image's entrypoint on the first start only (an empty data directory), as the server's own
# user, against its temporary server (socket only, local trust). Creates the exporter's role: it can log in (from
# STACK_SUBNET only, pg_hba.conf) and read the server's statistics (pg_monitor), never a table's rows.
set -eu
psql -v ON_ERROR_STOP=1 --no-psqlrc --username postgres --dbname postgres <<SQL
\set pw \`cat "$METRICS_PASSWORD_FILE"\`
CREATE ROLE metrics LOGIN PASSWORD :'pw' CONNECTION LIMIT 5;
GRANT pg_monitor TO metrics;
-- Only roles granted CONNECT may connect (scripts/db.sh does the same for every database it creates).
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
GRANT CONNECT ON DATABASE postgres TO metrics;
SQL
