#!/bin/sh
# Daily pg_dump of the finance database into /backups (mounted volume),
# pruning dumps older than RETENTION_DAYS. Runs as a long-lived compose
# service; scripts/restore.sh documents the corresponding restore path.
set -eu

RETENTION_DAYS="${RETENTION_DAYS:-14}"

dump_now() {
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  out="/backups/finance-${ts}.sql.gz"
  echo "[backup] dumping to ${out}"
  pg_dump -h postgres -U finance -d finance | gzip > "${out}"
  find /backups -name 'finance-*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete
  echo "[backup] done, retention=${RETENTION_DAYS}d"
}

dump_now
while true; do
  sleep 86400
  dump_now
done
