#!/usr/bin/env bash
# Proves a backup can be restored: loads the newest dump of one database into a throwaway database, prints how
# many tables and rows came back, then drops the throwaway database. The live database is never touched.
#
#   sudo /usr/local/bin/kadena-restore-test kadena_nexus
#   sudo /usr/local/bin/kadena-restore-test kadena_nexus /path/to/a/specific.dump
set -euo pipefail

CONF=${KADENA_BACKUPS_CONF:-/etc/kadena-backups.conf}
# shellcheck source=/dev/null
[ -r "$CONF" ] && . "$CONF"
BACKUP_DIR=${BACKUP_DIR:-/var/backups/kadena-db}
PG_USER=${PG_USER:-postgres}
export PGPORT=${PGPORT:-5432}

db=${1:?Usage: kadena-restore-test <database> [dump file]}
case "$db" in *[!A-Za-z0-9_-]*) echo "Invalid database name: $db" >&2; exit 1 ;; esac
[ "$(id -u)" = 0 ] || { echo "Run as root" >&2; exit 1; }

dump=${2:-$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "$db-*.dump" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)}
[ -n "$dump" ] && [ -r "$dump" ] || { echo "No dump found for $db in $BACKUP_DIR" >&2; exit 1; }
if [ -r "$dump.sha256" ]; then (cd "$(dirname "$dump")" && sha256sum -c --quiet "$(basename "$dump").sha256"); fi

scratch="restore_test_${db//-/_}_$$"
psqlp() { runuser -u "$PG_USER" -- psql -X -q -v ON_ERROR_STOP=1 "$@"; }
cleanup() { psqlp -d postgres -c "DROP DATABASE IF EXISTS \"$scratch\"" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "Restoring $(basename "$dump") into $scratch"
psqlp -d postgres -c "CREATE DATABASE \"$scratch\""
runuser -u "$PG_USER" -- pg_restore --no-owner --no-acl --exit-on-error --dbname="$scratch" < "$dump"
tables=$(psqlp -d "$scratch" -Atc "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')")
psqlp -d "$scratch" -c "ANALYZE" >/dev/null
rows=$(psqlp -d "$scratch" -Atc "SELECT coalesce(sum(greatest(c.reltuples,0)),0)::bigint FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='r' AND n.nspname NOT IN ('pg_catalog','information_schema')")
echo "Restore OK: $tables tables, $rows rows"
