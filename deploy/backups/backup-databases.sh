#!/usr/bin/env bash
# Nightly PostgreSQL backups for the Kadena Nexus server, copied off the server.
#
#   sudo /usr/local/bin/kadena-backup-databases            (normally run by kadena-backups.timer)
#
# Settings: /etc/kadena-backups.conf (see kadena-backups.conf.example). For each database in DATABASES it:
#   1. dumps it with pg_dump (custom format) as the postgres user, so no passwords are needed;
#   2. checks the dump can be read back (pg_restore --list) and writes a SHA-256 file;
#   3. keeps KEEP_DAYS days locally in BACKUP_DIR;
#   4. copies BACKUP_DIR to the off-server target (REMOTE) with rsync over SSH, if REMOTE is set.
# Any failure stops the run with a non-zero exit, so systemd marks it failed and the optional HEALTHCHECK_URL is
# not pinged (a missed ping is the alert). Nothing here reads or prints application secrets.
set -euo pipefail
umask 077

CONF=${KADENA_BACKUPS_CONF:-/etc/kadena-backups.conf}
[ -r "$CONF" ] || { echo "Missing $CONF (copy kadena-backups.conf.example)" >&2; exit 1; }
# shellcheck source=/dev/null
. "$CONF"

: "${DATABASES:?DATABASES must list at least one database}"
BACKUP_DIR=${BACKUP_DIR:-/var/backups/kadena-db}
KEEP_DAYS=${KEEP_DAYS:-14}
PG_USER=${PG_USER:-postgres}
PGPORT=${PGPORT:-5432}
REMOTE=${REMOTE:-}
REMOTE_PORT=${REMOTE_PORT:-23}
REMOTE_KEY=${REMOTE_KEY:-/root/.ssh/kadena-backups}
HEALTHCHECK_URL=${HEALTHCHECK_URL:-}
export PGPORT

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
[ "$(id -u)" = 0 ] || { echo "Run as root (it dumps as $PG_USER and writes $BACKUP_DIR)" >&2; exit 1; }
case "$KEEP_DAYS" in ''|*[!0-9]*) echo "KEEP_DAYS must be a whole number" >&2; exit 1 ;; esac

exec 9>/run/kadena-backups.lock
flock -n 9 || { log "Another backup is running; stopping."; exit 1; }

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)

for db in $DATABASES; do
  case "$db" in *[!A-Za-z0-9_-]*) echo "Invalid database name: $db" >&2; exit 1 ;; esac
  name="$db-$stamp.dump"
  tmp="$BACKUP_DIR/.$name.partial"
  log "Dumping $db"
  # pg_dump runs as the postgres user (peer authentication); its output is written by root into BACKUP_DIR.
  runuser -u "$PG_USER" -- pg_dump --format=custom --no-owner --no-acl --dbname="$db" > "$tmp"
  pg_restore --list "$tmp" > /dev/null
  mv "$tmp" "$BACKUP_DIR/$name"
  (cd "$BACKUP_DIR" && sha256sum "$name" > "$name.sha256")
  log "OK $name ($(du -h "$BACKUP_DIR/$name" | cut -f1))"
done

find "$BACKUP_DIR" -maxdepth 1 -type f \( -name '*.dump' -o -name '*.dump.sha256' \) -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name '.*.partial' -delete

if [ -n "$REMOTE" ]; then
  [ -r "$REMOTE_KEY" ] || { echo "Missing SSH key $REMOTE_KEY for $REMOTE" >&2; exit 1; }
  log "Copying to $REMOTE"
  # The remote copy mirrors BACKUP_DIR (the last KEEP_DAYS days). Turn on the storage's own snapshots so a
  # mistake or an attacker on this server cannot remove older copies (see README).
  rsync -a --delete --partial-dir=.rsync-partial \
    -e "ssh -p $REMOTE_PORT -i $REMOTE_KEY -o BatchMode=yes -o StrictHostKeyChecking=yes" \
    "$BACKUP_DIR/" "$REMOTE/"
  log "Off-server copy done"
else
  log "REMOTE is not set: backups stay on this server only"
fi

if [ -n "$HEALTHCHECK_URL" ]; then
  curl -fsS -m 15 --retry 3 -o /dev/null "$HEALTHCHECK_URL" || log "Health-check ping failed (backups are fine)"
fi
log "All done: $DATABASES"
