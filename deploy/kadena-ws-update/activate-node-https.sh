#!/usr/bin/env bash
# Run after GoDaddy DNS and Oracle ingress are configured.
set -euo pipefail
test "$(id -u)" -eq 0
python3 - <<'PY'
import socket
addresses = {x[4][0] for x in socket.getaddrinfo('node.kadena.ws', 80, family=socket.AF_INET)}
if addresses != {'193.122.85.1'}:
    raise SystemExit('node.kadena.ws must resolve only to 193.122.85.1 before HTTPS activation.')
PY
nginx -t
curl -fsS -H 'Host: node.kadena.ws' http://127.0.0.1/info >/dev/null
certbot --nginx -d node.kadena.ws --non-interactive --agree-tos --register-unsafely-without-email --redirect
nginx -t
systemctl is-active --quiet nginx chainweb-node
systemctl is-enabled certbot.timer
curl -fsS https://node.kadena.ws/info | python3 -c 'import json,sys; d=json.load(sys.stdin); print("HTTPS OK: Chainweb",d["nodePackageVersion"],d["nodeVersion"],d["nodeNumberOfChains"],"chains")'
curl -fsSI https://node.kadena.ws/info | sed -n '/HTTP\//p;/[Aa]ccess-[Cc]ontrol-[Aa]llow-[Oo]rigin/p'
curl -fsS https://node.kadena.ws/chainweb/0.0/mainnet01/cut | python3 -c 'import json,sys; d=json.load(sys.stdin); print("Public cut:",d["height"],"across",len(d["hashes"]),"chains")'
