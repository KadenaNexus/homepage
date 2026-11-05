#!/usr/bin/env bash
# Apply the November 2026 DNS/restart/scheduling fix without rebooting the server.
set -Eeuo pipefail
umask 077

[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
source_dir=$(dirname -- "$(readlink -f -- "$0")")
crawler_source="$source_dir/crawler-proxy.conf"
[[ -f "$crawler_source" ]] || crawler_source="$source_dir/../kadena-ws-update/crawler-proxy.conf"
crawler_target=/etc/nginx/snippets/kadena-crawler-proxy.conf
restart_target=/etc/systemd/system/nginx.service.d/90-kadena-recovery.conf
timer_target=/etc/systemd/system/apt-daily-upgrade.timer.d/90-kadena-schedule.conf
old_crawler_hash=99e9f6d9b382449474938140a7da0d05ce552fc7b3cb8b1916adbd6e5a0daed0
phase=none
backup_dir=''
work_dir=''

hash_file() { sha256sum -- "$1" | awk '{print $1}'; }
die() { printf '%s\n' "$*" >&2; exit 1; }
atomic_replace() {
    local input=$1 destination=$2 temp owner=0 group=0 mode=644
    if [[ -e "$destination" ]]; then
        read -r owner group mode < <(stat -c '%u %g %a' -- "$destination")
    fi
    temp=$(mktemp -- "${destination}.recovery.XXXXXX")
    install -o "$owner" -g "$group" -m "$mode" -- "$input" "$temp"
    mv -fT -- "$temp" "$destination"
}
save_target() {
    local destination=$1
    if [[ -e "$destination" ]]; then
        [[ -f "$destination" && ! -L "$destination" ]] || die "Expected regular file: $destination"
        mkdir -p -- "$backup_dir$(dirname -- "$destination")"
        cp -a -- "$destination" "$backup_dir$destination"
    fi
}
restore_target() {
    local destination=$1
    if [[ -f "$backup_dir$destination" ]]; then
        atomic_replace "$backup_dir$destination" "$destination"
    elif [[ -f "$destination" ]]; then
        unlink -- "$destination"
    fi
}
on_exit() {
    local code=$?
    trap - EXIT INT TERM
    set +e
    if [[ "$code" -ne 0 && "$phase" == crawler ]]; then
        restore_target "$crawler_target"
        nginx -t && systemctl reload nginx
        echo 'Crawler configuration restored after failure.' >&2
    elif [[ "$code" -ne 0 && "$phase" == systemd ]]; then
        restore_target "$restart_target"
        restore_target "$timer_target"
        systemctl daemon-reload
        systemctl restart apt-daily-upgrade.timer
        echo 'Systemd overrides restored; the completed nginx DNS fix remains installed.' >&2
    fi
    [[ -z "$backup_dir" ]] || printf 'Backup and audit: %s\n' "$backup_dir"
    if [[ -n "$work_dir" && "$work_dir" == /run/kadena-nginx-recovery.* ]]; then
        rm -r -- "$work_dir"
    fi
    exit "$code"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for command in nginx systemctl systemd-analyze sha256sum flock python3 curl; do
    command -v "$command" >/dev/null || die "Missing command: $command"
done
exec 9>/run/lock/kadena-nginx-recovery.lock
flock -n 9 || die 'Another nginx recovery installation is running.'
[[ -f "$crawler_target" && ! -L "$crawler_target" ]] || die 'Expected an existing regular crawler snippet.'

# Snapshot user-staged inputs into a root-owned directory before installation.
work_dir=$(mktemp -d /run/kadena-nginx-recovery.XXXXXX)
cp -- "$crawler_source" "$work_dir/crawler-proxy.conf"
cp -- "$source_dir/nginx-restart.conf" "$source_dir/apt-daily-upgrade-schedule.conf" "$work_dir/"
new_crawler_hash=$(hash_file "$work_dir/crawler-proxy.conf")
current_crawler_hash=$(hash_file "$crawler_target")
[[ "$current_crawler_hash" == "$old_crawler_hash" || "$current_crawler_hash" == "$new_crawler_hash" ]] || die 'Crawler snippet changed since inspection; refusing to overwrite it.'
systemd-analyze calendar '*-*-* 00:30:00 UTC' >/dev/null

install -d -m 750 /var/backups/kadena-nginx-recovery
backup_dir=$(mktemp -d "/var/backups/kadena-nginx-recovery/$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
for destination in "$crawler_target" "$restart_target" "$timer_target"; do
    save_target "$destination"
done
journalctl -u nginx -u systemd-resolved --since '2026-11-05 06:35:00 UTC' --until '2026-11-05 07:30:00 UTC' --no-pager > "$backup_dir/incident-journal.log"
systemctl cat nginx apt-daily-upgrade.timer > "$backup_dir/systemd-before.txt"
systemctl status pm2-tahir pm2-developer pm2-earnest --no-pager --full > "$backup_dir/legacy-pm2-before.txt" 2>&1 || true
if command -v ufw >/dev/null; then ufw status verbose > "$backup_dir/ufw-status.txt"; fi

# Urgent fix first: a reload, never a restart of nginx or systemd-resolved.
[[ "$(hash_file "$crawler_target")" == "$current_crawler_hash" ]] || die 'Crawler snippet changed while preparing the backup.'
phase=crawler
atomic_replace "$work_dir/crawler-proxy.conf" "$crawler_target"
nginx -t
systemctl reload nginx
systemctl is-active --quiet nginx
phase=none
printf '1. nginx runtime DNS lookup installed and reloaded.\n'

phase=systemd
install -d -m 755 -- "$(dirname -- "$restart_target")" "$(dirname -- "$timer_target")"
atomic_replace "$work_dir/nginx-restart.conf" "$restart_target"
atomic_replace "$work_dir/apt-daily-upgrade-schedule.conf" "$timer_target"
systemctl daemon-reload
systemctl restart apt-daily-upgrade.timer
[[ "$(systemctl show nginx -p Restart --value)" == on-failure ]] || die 'Effective nginx restart policy is unexpected.'
[[ "$(systemctl show nginx -p RestartUSec --value)" == 5s ]] || die 'Effective nginx restart delay is unexpected.'
[[ "$(systemctl show apt-daily-upgrade.timer -p RandomizedDelayUSec --value)" == 0 ]] || die 'Effective upgrade timer still has randomized delay.'
systemctl is-active --quiet apt-daily-upgrade.timer
phase=none
printf '2. nginx Restart=on-failure, RestartSec=5s installed.\n'
printf '3. Upgrade timer moved to 00:30 UTC, without randomized delay.\n'
systemctl show apt-daily-upgrade.timer -p TimersCalendar -p RandomizedDelayUSec -p AccuracyUSec -p NextElapseUSecRealtime

# Stop only the three explicitly retired PM2 units, never pm2-root/mustafa.
for unit in pm2-tahir.service pm2-developer.service pm2-earnest.service; do
    if [[ "$(systemctl show "$unit" -p LoadState --value)" == not-found ]]; then
        printf '4. %s: absent; nothing to stop or disable.\n' "$unit"
        continue
    fi
    systemctl disable --now "$unit"
    if systemctl is-enabled --quiet "$unit" || systemctl is-active --quiet "$unit"; then
        die "Legacy unit is still enabled or active: $unit"
    fi
    printf '4. %s: stopped and disabled.\n' "$unit"
done
systemctl is-active nginx pm2-root pm2-mustafa

# Failed upstream checks are reported without undoing the DNS resilience fix.
failed=false
for endpoint in nodes 'history?horas=1'; do
    file="$backup_dir/${endpoint%%\?*}-after.json"
    if curl --noproxy '*' --fail --silent --show-error --max-time 45 --resolve nodes.kadena.ws:443:127.0.0.1 "https://nodes.kadena.ws/api/kdascan/$endpoint" -o "$file"; then
        if [[ "$endpoint" == nodes ]]; then
            python3 -c 'import json,sys; assert isinstance(json.load(open(sys.argv[1])), list); print("Crawler nodes: HTTP 200, JSON array.")' "$file" || failed=true
        else
            python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert float(d["horas"]) == 1; print("Crawler history: HTTP 200, horas=1 preserved.")' "$file" || failed=true
        fi
    else
        failed=true
    fi
done
[[ "$failed" == false ]] || die 'Changes installed, but crawler validation needs attention; inspect the saved audit.'
printf 'All four recovery items applied. No server reboot was performed.\n'
