#!/bin/sh
# Restore a backup produced by docker/backup.sh into a running Postgres.
#
# Usage: scripts/restore.sh path/to/finance-<timestamp>.sql.gz
#
# Intended for: (a) disaster recovery, and (b) the periodic restore drill
# every finance app should actually run — a backup nobody has restored
# is unverified. Restores into whatever DATABASE_URL/postgres service is
# currently configured; drop and recreate the DB first if you want a
# clean-slate restore rather than a merge.
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 path/to/finance-<timestamp>.sql.gz" >&2
  exit 1
fi

DUMP_FILE="$1"
HOST="${PGHOST:-localhost}"
PORT="${PGPORT:-5432}"
USER="${PGUSER:-finance}"
DB="${PGDATABASE:-finance}"

echo "[restore] restoring ${DUMP_FILE} into ${USER}@${HOST}:${PORT}/${DB}"
gunzip -c "${DUMP_FILE}" | psql -h "${HOST}" -p "${PORT}" -U "${USER}" -d "${DB}"
echo "[restore] done"
