#!/usr/bin/env bash
# One Whale Watch pass on GitHub Actions, no server setup needed:
#   1. restore the watcher state from the live site (kadena.ws/whales/data/watcher/)
#   2. read the new blocks, post alerts (state is copied to the server BEFORE each post)
#   3. publish page data + state to /var/www/kadena.ws/whales/data on the server
# The first run ever (state answers 404) seeds the last 30 days. Any other restore
# problem stops the run, so a temporary outage can never wipe the live feed.
#
# Needs: DEPLOY_HOST, DEPLOY_USER, DEPLOY_KEY (the existing kadena.ws deploy secrets).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LIVE="${LIVE_URL:-https://kadena.ws/whales/data}"
REMOTE="/var/www/kadena.ws/whales/data"
WORK="${RUNNER_TEMP:-/tmp}/whale-watch"
export DATA_DIR="$WORK/data" PUBLIC_DIR="$WORK/public"
mkdir -p "$DATA_DIR" "$PUBLIC_DIR"

# --- pinned SSH, same checks as the shared deploy workflow ---
test "$DEPLOY_HOST" = "89.167.14.58"
test "$DEPLOY_USER" = "deployer"
test -n "$DEPLOY_KEY"
install -m 700 -d "$HOME/.ssh"
printf '%s\n' "$DEPLOY_KEY" > "$HOME/.ssh/whale_watch_key"
chmod 600 "$HOME/.ssh/whale_watch_key"
cat > "$HOME/.ssh/whale_watch_known_hosts" <<'EOF'
89.167.14.58 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEmNdcA2rlIHynqX/PNVjT+fDPFVwmhc1WDE6QN0kLel
EOF
SSH="ssh -i $HOME/.ssh/whale_watch_key -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.ssh/whale_watch_known_hosts -o ConnectTimeout=15"
export RSYNC_RSH="$SSH"
$SSH "$DEPLOY_USER@$DEPLOY_HOST" "mkdir -p '$REMOTE/watcher'"

# --- 1. restore ---
code=$(curl -sS -o "$DATA_DIR/state.json" -w '%{http_code}' -H 'Cache-Control: no-cache' "$LIVE/watcher/state.json?t=$(date +%s)" || true)
code="${code:-000}"
if [ "$code" = "200" ]; then
  node -e 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"))' "$DATA_DIR/state.json"
  for f in feed.json posts.jsonl; do
    c=$(curl -sS -o "$DATA_DIR/$f" -w '%{http_code}' -H 'Cache-Control: no-cache' "$LIVE/watcher/$f?t=$(date +%s)" || true)
    if [ "$c" = "404" ]; then rm -f "$DATA_DIR/$f"; elif [ "$c" != "200" ]; then echo "::error::could not restore $f (HTTP $c); stopping"; exit 1; fi
  done
  test ! -f "$DATA_DIR/feed.json" || node -e 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"))' "$DATA_DIR/feed.json"
  echo "restored state"
elif [ "$code" = "404" ]; then
  rm -f "$DATA_DIR/state.json"
  echo "::notice::first run: seeding the last 30 days (nothing is posted)"
  node "$HERE/seed.mjs" 30
else
  echo "::error::could not restore state (HTTP $code); stopping so the live feed is not overwritten"
  exit 1
fi

# --- publish helper, also the checkpoint run before every post ---
cat > "$WORK/publish.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export RSYNC_RSH="$SSH"
rsync -a --chmod=F644 "$PUBLIC_DIR/" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE/"
rsync -a --chmod=F644 --include=state.json --include=feed.json --include=posts.jsonl --exclude='*' "$DATA_DIR/" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE/watcher/"
EOF
chmod 700 "$WORK/publish.sh"
export CHECKPOINT_CMD="$WORK/publish.sh"

# --- 2 + 3. one pass; the watcher runs the checkpoint before each post and at the end ---
node "$HERE/watcher.mjs" --once
echo "published to $REMOTE"
