#!/usr/bin/env bash
# Install or update Kadena Whale Watch on the kadena.ws server (Hetzner).
# Run as root from a checkout of KadenaNexus/homepage:
#   sudo bash services/whale-watch/install.sh
# Safe to re-run: it updates the code and labels, keeps state, settings and secrets.
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }
SRC="$(cd "$(dirname "$0")" && pwd)"
NODE_BIN="$(command -v node || true)"
[ -n "$NODE_BIN" ] || { echo "Node.js 18+ is required (node not found)." >&2; exit 1; }
case "$NODE_BIN" in /root/*|/home/*) echo "node is under a home folder ($NODE_BIN); the service cannot read it. Install a system Node (e.g. /usr/bin/node)." >&2; exit 1;; esac
MAJOR="$("$NODE_BIN" -p 'process.versions.node.split(".")[0]')"
[ "$MAJOR" -ge 18 ] || { echo "Node.js 18+ is required (found $("$NODE_BIN" -v))." >&2; exit 1; }
[ -d /var/www/kadena.ws ] || { echo "/var/www/kadena.ws not found: run this on the kadena.ws server." >&2; exit 1; }

id whalewatch >/dev/null 2>&1 || useradd --system --home-dir /var/lib/whale-watch --shell /usr/sbin/nologin whalewatch

install -d -o root -g root -m 755 /opt/whale-watch /opt/whale-watch/lib
install -m 644 "$SRC"/watcher.mjs "$SRC"/seed.mjs "$SRC"/labels.json /opt/whale-watch/
install -m 644 "$SRC"/lib/*.mjs /opt/whale-watch/lib/
install -d -o whalewatch -g whalewatch -m 750 /var/lib/whale-watch
install -d -o whalewatch -g whalewatch -m 755 /var/www/kadena.ws/whales /var/www/kadena.ws/whales/data
# the page itself is deployed by GitHub Actions as the deployer user; only data/ belongs to the service
chown deployer:deployer /var/www/kadena.ws/whales 2>/dev/null || true

if [ ! -f /etc/whale-watch.env ]; then
  install -m 600 -o root -g root "$SRC/whale-watch.env.example" /etc/whale-watch.env
  echo "Created /etc/whale-watch.env (POST_MODE=dry). Add the X keys there when the bot account is ready."
fi

sed "s#NODE_BIN#$NODE_BIN#" "$SRC/whale-watch.service" > /etc/systemd/system/whale-watch.service
chmod 644 /etc/systemd/system/whale-watch.service
systemctl daemon-reload

if [ ! -f /var/lib/whale-watch/state.json ]; then
  echo "First install: seeding the last 30 days (nothing is posted)..."
  systemd-run --quiet --wait --pipe --uid=whalewatch --gid=whalewatch \
    -p EnvironmentFile=/etc/whale-watch.env -p WorkingDirectory=/opt/whale-watch \
    "$NODE_BIN" /opt/whale-watch/seed.mjs 30 || echo "Seed failed; the watcher still starts and the feed fills from now on."
fi

systemctl enable whale-watch >/dev/null
systemctl restart whale-watch
sleep 5
systemctl --no-pager --lines=5 status whale-watch || true
echo
echo "Done. Logs: journalctl -u whale-watch -f   Data: /var/www/kadena.ws/whales/data/"
