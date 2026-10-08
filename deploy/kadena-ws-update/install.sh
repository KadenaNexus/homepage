#!/usr/bin/env bash
# Run with: sudo bash /home/mustafa/kadena-ws-update/install.sh
set -Eeuo pipefail
umask 077

source_dir=$(dirname -- "$(readlink -f -- "$0")")
homepage=/var/www/kadena.ws/index.html
dashboard=/home/zero/monitor/dist/index.html
homepage_conf=/etc/nginx/sites-enabled/kadena.ws
dashboard_conf=/etc/nginx/sites-enabled/nodes.kadena.ws
snippet=/etc/nginx/snippets/kadena-crawler-proxy.conf
old_homepage_hash=f32ff13ed1cf29f2bb1ec1c19c795d270d8b523e669cb76f04c3bcac81d18014
old_dashboard_hash=af82a5d1a86bd785452f42e1fd42047c5bf606c40b22f404312fa612d964b8d0
backup_dir=''
work_dir=''
changes_started=false
snippet_existed=false
temporary_files=()

die() { printf '%s\n' "$*" >&2; return 1; }
hash() { sha256sum -- "$1" | awk '{print $1}'; }

assert_data_jobs() {
    [[ -d /home/zero/monitor/dist/data ]] || die 'Dashboard data directory is missing.'
    pgrep -u zero -f '(^|[ /])sync-data-continuously[.]sh([ ]|$)' >/dev/null || die 'The zero dashboard data synchronization job is not running.'
    pgrep -u deploy -f '(^|[ /])kdatracker[ ]+track([ ]|$)' >/dev/null || die 'The deploy kdatracker job is not running.'
}

# The temporary file lives beside its destination, so each rename is atomic.
atomic_replace() {
    local input=$1 destination=$2 temp owner=0 group=0 mode=644
    if [[ -e "$destination" ]]; then
        owner=$(stat -c '%u' -- "$destination") || return 1
        group=$(stat -c '%g' -- "$destination") || return 1
        mode=$(stat -c '%a' -- "$destination") || return 1
    fi
    temp=$(mktemp -- "${destination}.kadena-update.XXXXXX") || return 1
    temporary_files+=("$temp")
    install -o "$owner" -g "$group" -m "$mode" -- "$input" "$temp" || return 1
    mv -fT -- "$temp" "$destination" || return 1
}

cleanup() {
    local temp
    for temp in "${temporary_files[@]}"; do rm -f -- "$temp"; done
    [[ -z "$work_dir" ]] || rm -rf -- "$work_dir"
}

on_failure() {
    local code=$1 line=$2 path rollback_ok=true
    trap - ERR INT TERM
    set +e
    printf 'Installation failed at line %s (exit %s).\n' "$line" "$code" >&2
    if [[ "$changes_started" == true ]]; then
        for path in "$homepage" "$dashboard" "$homepage_conf" "$dashboard_conf"; do
            atomic_replace "$backup_dir$path" "$path" || rollback_ok=false
        done
        if [[ "$snippet_existed" == true ]]; then
            atomic_replace "$backup_dir$snippet" "$snippet" || rollback_ok=false
        else
            rm -f -- "$snippet" || rollback_ok=false
        fi
        if nginx -t && systemctl reload nginx; then
            printf 'Previous website files and nginx configuration restored.\n' >&2
        else
            rollback_ok=false
        fi
        printf 'Backup: %s\n' "$backup_dir" >&2
        [[ "$rollback_ok" == true ]] || printf 'Rollback needs attention; inspect the backup and nginx status.\n' >&2
    fi
    cleanup
    exit "$code"
}
trap 'on_failure "$?" "$LINENO"' ERR
trap 'on_failure 130 "$LINENO"' INT
trap 'on_failure 143 "$LINENO"' TERM
trap cleanup EXIT

[[ $EUID -eq 0 ]] || die 'Run this installer with sudo.'
for command in python3 nginx systemctl sha256sum flock stat install pgrep; do
    command -v "$command" >/dev/null || die "Required command is missing: $command"
done
exec 9>/run/lock/kadena-ws-update.lock
flock -n 9 || die 'Another Kadena website update is running.'

for path in "$homepage" "$dashboard" "$homepage_conf" "$dashboard_conf"; do
    [[ -f "$path" && ! -L "$path" ]] || die "Expected an existing regular file: $path"
done
[[ ! -e "$snippet" || ( -f "$snippet" && ! -L "$snippet" ) ]] || die 'The crawler snippet is not a regular file.'
[[ -s /etc/ssl/certs/ca-certificates.crt ]] || die 'System certificate trust store is missing.'
assert_data_jobs
nginx -t

# Reject unexpected manifest paths before invoking sha256sum as root.
python3 - "$source_dir/SHA256SUMS" <<'PY'
import re, sys
from pathlib import Path
expected = {'homepage-index.html', 'nodes-index.html', 'crawler-proxy.conf'}
seen = set()
for line in Path(sys.argv[1]).read_text().splitlines():
    match = re.fullmatch(r'([0-9a-f]{64}) [ *]([^\r\n]+)', line)
    if not match or match[2] not in expected or match[2] in seen:
        raise SystemExit('SHA256SUMS must contain each of the three expected input files exactly once.')
    seen.add(match[2])
if seen != expected:
    raise SystemExit('SHA256SUMS is missing an input file.')
PY
(cd -- "$source_dir" && sha256sum --strict -c SHA256SUMS)
new_homepage_hash=$(hash "$source_dir/homepage-index.html")
new_dashboard_hash=$(hash "$source_dir/nodes-index.html")
new_snippet_hash=$(hash "$source_dir/crawler-proxy.conf")
current_homepage_hash=$(hash "$homepage")
current_dashboard_hash=$(hash "$dashboard")
current_homepage_conf_hash=$(hash "$homepage_conf")
current_dashboard_conf_hash=$(hash "$dashboard_conf")
current_snippet_hash=''
if [[ -e "$snippet" ]]; then
    snippet_existed=true
    current_snippet_hash=$(hash "$snippet")
fi
[[ "$current_homepage_hash" == "$old_homepage_hash" || "$current_homepage_hash" == "$new_homepage_hash" ]] || die 'Homepage changed since preparation; installation stopped without modifying it.'
[[ "$current_dashboard_hash" == "$old_dashboard_hash" || "$current_dashboard_hash" == "$new_dashboard_hash" ]] || die 'Dashboard changed since preparation; installation stopped without modifying it.'

work_dir=$(mktemp -d /tmp/kadena-ws-update.XXXXXX)
# Use root-owned snapshots of verified inputs for the actual installation.
cp -- "$source_dir/homepage-index.html" "$source_dir/nodes-index.html" "$source_dir/crawler-proxy.conf" "$work_dir/"
[[ "$(hash "$work_dir/homepage-index.html")" == "$new_homepage_hash" && "$(hash "$work_dir/nodes-index.html")" == "$new_dashboard_hash" && "$(hash "$work_dir/crawler-proxy.conf")" == "$new_snippet_hash" ]] || die 'Staged inputs changed while being copied.'
# Parse nginx server blocks, preserving the original configuration verbatim
# apart from one include inside each requested HTTPS server.
python3 - "$homepage_conf" "$dashboard_conf" "$work_dir" "$snippet" <<'PY'
import re, sys
from pathlib import Path
token_re = re.compile(r'''\#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[{};]|[^\s{};#]+''')
include_path = sys.argv[4]

def prepare(filename, domain, expected_root, output):
    text = Path(filename).read_text()
    tokens = [(m.group(), m.start(), m.end()) for m in token_re.finditer(text) if not m.group().startswith('#')]
    servers, level, i = [], 0, 0
    while i < len(tokens):
        token, start, end = tokens[i]
        if level == 0 and token == 'server' and i + 1 < len(tokens) and tokens[i + 1][0] == '{':
            opening = tokens[i + 1][2]
            j, depth, directive, directives = i + 2, 1, [], []
            while j < len(tokens) and depth:
                word = tokens[j][0]
                if word == '{':
                    depth += 1
                    if depth == 2:
                        directive = []
                elif word == '}':
                    depth -= 1
                    directive = []
                elif depth == 1 and word == ';':
                    directives.append(directive)
                    directive = []
                elif depth == 1:
                    directive.append(word.strip("\"'"))
                j += 1
            if depth:
                raise SystemExit(f'Unbalanced server block in {filename}')
            servers.append((opening, directives))
            i = j
            continue
        if token == '{':
            level += 1
        elif token == '}':
            level -= 1
        i += 1
    candidates = []
    for opening, directives in servers:
        names = [d[1:] for d in directives if d and d[0] == 'server_name']
        listens = [d[1:] for d in directives if d and d[0] == 'listen']
        https = any('ssl' in args and any(a == '443' or a.endswith(':443') for a in args) for args in listens)
        if https and any(domain in args for args in names):
            candidates.append((opening, directives))
    if len(candidates) != 1:
        raise SystemExit(f'Expected one HTTPS server for {domain} in {filename}')
    opening, directives = candidates[0]
    if ['root', expected_root] not in directives:
        raise SystemExit(f'Unexpected website root for {domain}; refusing to alter configuration.')
    includes = sum(d == ['include', include_path] for d in directives)
    total_includes = sum(d == ['include', include_path] for _, ds in servers for d in ds)
    if includes > 1 or total_includes != includes:
        raise SystemExit(f'Unexpected crawler snippet placement in {filename}')
    if not includes:
        text = text[:opening] + '\n    include ' + include_path + ';' + text[opening:]
    Path(output).write_text(text)

prepare(sys.argv[1], 'kadena.ws', '/var/www/kadena.ws', Path(sys.argv[3]) / 'homepage.conf')
prepare(sys.argv[2], 'nodes.kadena.ws', '/home/zero/monitor/dist', Path(sys.argv[3]) / 'dashboard.conf')
PY

if [[ "$current_homepage_hash" == "$new_homepage_hash" && "$current_dashboard_hash" == "$new_dashboard_hash" && -f "$snippet" ]] \
    && [[ "$(hash "$snippet")" == "$new_snippet_hash" ]] \
    && cmp -s "$homepage_conf" "$work_dir/homepage.conf" \
    && cmp -s "$dashboard_conf" "$work_dir/dashboard.conf"; then
    printf 'Kadena website update is already installed; data jobs are active.\n'
    exit 0
fi

backup_dir=$(mktemp -d "/var/backups/kadena-ws-update-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
for path in "$homepage" "$dashboard" "$homepage_conf" "$dashboard_conf"; do
    mkdir -p -- "$backup_dir$(dirname -- "$path")"
    cp -a -- "$path" "$backup_dir$path"
done
if [[ "$snippet_existed" == true ]]; then
    mkdir -p -- "$backup_dir$(dirname -- "$snippet")"
    cp -a -- "$snippet" "$backup_dir$snippet"
fi
cp -a -- "$source_dir/SHA256SUMS" "$backup_dir/SHA256SUMS"

# Recheck before the first mutation to avoid overwriting concurrent changes.
[[ "$(hash "$homepage")" == "$current_homepage_hash" && "$(hash "$dashboard")" == "$current_dashboard_hash" ]] || die 'Website files changed during preparation; no files were installed.'
[[ "$(hash "$homepage_conf")" == "$current_homepage_conf_hash" && "$(hash "$backup_dir$homepage_conf")" == "$current_homepage_conf_hash" ]] || die 'Homepage nginx configuration changed during preparation.'
[[ "$(hash "$dashboard_conf")" == "$current_dashboard_conf_hash" && "$(hash "$backup_dir$dashboard_conf")" == "$current_dashboard_conf_hash" ]] || die 'Dashboard nginx configuration changed during preparation.'
if [[ "$snippet_existed" == true ]]; then
    [[ -f "$snippet" && "$(hash "$snippet")" == "$current_snippet_hash" && "$(hash "$backup_dir$snippet")" == "$current_snippet_hash" ]] || die 'Crawler snippet changed during preparation.'
else
    [[ ! -e "$snippet" ]] || die 'A crawler snippet appeared during preparation.'
fi
assert_data_jobs
changes_started=true
atomic_replace "$work_dir/crawler-proxy.conf" "$snippet"
atomic_replace "$work_dir/homepage.conf" "$homepage_conf"
atomic_replace "$work_dir/dashboard.conf" "$dashboard_conf"
nginx -t
atomic_replace "$work_dir/homepage-index.html" "$homepage"
atomic_replace "$work_dir/nodes-index.html" "$dashboard"
systemctl reload nginx
systemctl is-active --quiet nginx
[[ "$(hash "$homepage")" == "$new_homepage_hash" && "$(hash "$dashboard")" == "$new_dashboard_hash" && "$(hash "$snippet")" == "$new_snippet_hash" ]]
assert_data_jobs
printf 'Homepage, Saudi node card, crawler routes, and dashboard update installed.\nBackup: %s\n' "$backup_dir"
