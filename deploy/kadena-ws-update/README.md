# Kadena homepage and Saudi node update — 8 October 2026

This directory records Naif's supplied homepage update and the changes needed
to show actual node observations in the homepage and network monitor.
`homepage-index.html` is the static production homepage; the older Vite app in
`apps/web` is not the current nginx deployment.

The homepage moves Kadena Earn into the live project list and adds the Saudi
node card. Its card checks the node API and independent crawler observations.
Unavailable references do not imply synchronization. Crawler timestamps expire;
uptime uses observed checks, and the first crawler observation is labelled
"First seen" rather than continuous uptime.

The primary Denascan crawler returned HTTP 502 during verification. The supplied
network monitor includes a kdascan fallback that displays Jeddah / Saudi Arabia,
Oracle Cloud and the actual node's synchronization status. The fallback has no
browser CORS support, so both website server blocks include the fixed read-only
nginx routes in `crawler-proxy.conf`.

## Website deployment

Server: `mustafa@89.167.14.58`. The user must enter the sudo password in their
terminal; this repository contains no credentials. Stage this directory at
`/home/mustafa/kadena-ws-update`, then run:

```sh
ssh -t mustafa@89.167.14.58 'sudo bash /home/mustafa/kadena-ws-update/install.sh'
```

The installer verifies the staged SHA256 manifest and known current homepage /
dashboard hashes, refuses unexpected concurrent changes, backs up the two HTML
files and actual enabled nginx configurations, installs the crawler snippet,
tests nginx before reloading, and preserves file ownership. A failure restores
the previous files and configuration. It checks the existing data processes and
never replaces the dashboard data directory. The backup path is printed on
success and failure.

Verify after installation:

```sh
curl -fsS https://kadena.ws/api/kdascan/nodes
curl -fsS 'https://kadena.ws/api/kdascan/history?horas=48'
curl -fsS https://nodes.kadena.ws/api/kdascan/nodes
```

Open both sites to verify Earn's live project card and the Jeddah / Oracle Cloud
node in the network monitor. While the public node API is awaiting DNS/ingress,
the homepage can display recent independent crawler observations. Version and
visitor latency require the node API to be reachable.

## Saudi node gateway

Server: `ubuntu@193.122.85.1`, Oracle `me-jeddah-1` (Jeddah). The Chainweb service
API continues to listen on `127.0.0.1:1848`. nginx exposes only GET/HEAD requests
to `/info`, `/health-check` and `/chainweb/0.0/mainnet01/cut`, with CORS and rate
limiting; transaction submission is not exposed. HTTP and HTTPS are accepted
before Oracle Ubuntu's host firewall REJECT rule, and persisted.

The gateway is installed and locally verified. External HTTP is still blocked,
and `node.kadena.ws` has no A record as of the recorded verification. Naif needs
to add GoDaddy DNS `node A 193.122.85.1` and allow inbound TCP 80 and 443 from
`0.0.0.0/0` in the instance's Oracle security list / NSG. TCP 1789 already works.

After those changes, run the staged activation script on the node:

```sh
ssh ubuntu@193.122.85.1 'sudo bash /home/ubuntu/kadena-homepage-update/activate-node-https.sh'
```

The script checks DNS, activates Certbot HTTPS with HTTP redirects and automatic
renewal, then checks `/info`, CORS and the public cut. Verify from another machine:

```sh
curl -fsS https://node.kadena.ws/info
curl -fsSI https://node.kadena.ws/info
curl -fsS https://node.kadena.ws/chainweb/0.0/mainnet01/cut
```

The node passed health, 20-chain public P2P and synchronization checks at
2026-10-08 10:30:57 UTC; its cut matched the community reference at 145943296.
The network monitor's source and operational node configuration are also
maintained on branch `codex/oracle-saudi-node`.
