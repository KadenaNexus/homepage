#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" -eq 0
staged=/home/ubuntu/kadena-homepage-update
if test -e /etc/letsencrypt/live/node.kadena.ws/fullchain.pem; then
    printf 'HTTPS is already configured. Keep the existing nginx configuration.\n'
    exit 0
fi
curl -fsS http://127.0.0.1:1848/info >/dev/null
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y nginx certbot python3-certbot-nginx
install -d -m 755 /var/www/node.kadena.ws/.well-known/acme-challenge
if test -f /etc/nginx/sites-available/node.kadena.ws; then
    cp -a /etc/nginx/sites-available/node.kadena.ws "/etc/nginx/sites-available/node.kadena.ws.bak-$(date -u +%Y%m%dT%H%M%SZ)"
fi
install -m 644 "$staged/node-kadena.ws.conf" /etc/nginx/sites-available/node.kadena.ws
ln -sfn /etc/nginx/sites-available/node.kadena.ws /etc/nginx/sites-enabled/node.kadena.ws
nginx -t
for port in 80 443; do
    iptables -C INPUT -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null ||
        iptables -I INPUT 5 -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT
done
netfilter-persistent save
systemctl enable --now nginx
systemctl reload nginx
curl -fsS --retry 3 --retry-all-errors --retry-delay 1 -H 'Host: node.kadena.ws' http://127.0.0.1/info | python3 -c 'import json,sys; d=json.load(sys.stdin); print("Node gateway ready: Chainweb",d["nodePackageVersion"])'
curl -fsSI -H 'Host: node.kadena.ws' http://127.0.0.1/info
