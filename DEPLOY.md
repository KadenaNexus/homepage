# kadena.ws homepage – deployment notes

Static site, no build step, no backend. Two HTML files and one image.

## Files
- `index.html`            homepage (self-contained: CSS, JS, logo, favicon all inline)
- `privacy-policy.html`   privacy policy, served at /privacy-policy
- `logo-kadena-nexus.png` full logo, for reference / other subdomains (not required by the pages)

## 1. Copy files
    sudo mkdir -p /var/www/kadena.ws
    sudo cp index.html privacy-policy.html logo-kadena-nexus.png /var/www/kadena.ws/
    sudo chown -R www-data:www-data /var/www/kadena.ws

## 2. nginx server block
Save `nginx-kadena.ws.conf` as /etc/nginx/sites-available/kadena.ws, then:
    sudo ln -s /etc/nginx/sites-available/kadena.ws /etc/nginx/sites-enabled/
    sudo nginx -t && sudo systemctl reload nginx

## 3. DNS (GoDaddy DNS panel for kadena.ws)
- A record  @    -> <server IPv4>
- A record  www  -> <server IPv4>   (or CNAME www -> kadena.ws)
- Change nothing else. adoption / nodes / marketplace / kadenadevs / escrow and MX records stay as they are.

## 4. TLS
After DNS resolves:
    sudo certbot --nginx -d kadena.ws -d www.kadena.ws
The config below already redirects www -> bare domain and http -> https once certbot has run.

## 5. CORS on the Adoption Index API (required for the live number on the homepage)
In the nginx config for adoption.kadena.ws, inside the location that proxies /api/index
(or the general /api/ location), add:
    add_header Access-Control-Allow-Origin "https://kadena.ws" always;
Then `sudo nginx -t && sudo systemctl reload nginx`.
Check: `curl -sI https://adoption.kadena.ws/api/index | grep -i access-control`
should print the header. Until it does, the homepage shows a static "50".

## 6. After go-live
- Load https://kadena.ws and https://kadena.ws/privacy-policy in a private window.
- Confirm the Adoption Index card shows today's number and date, not "Baseline = 50".
- Resubmit the root domain in Google Search Console.
- Cancel the GoDaddy Website Builder subscription (keep the domain and DNS).

## Updating content later
Edit index.html and copy it over again. No cache-busting needed; nginx serves the
file directly. The "In development" list and project rows are plain HTML near the
middle of the file.

## Saudi node card on the homepage (updated Oct 8 2026)
The hero shows a pulsing "Saudi Kadena node" card. Everything on it is read from the
visitor's browser; nothing runs on the kadena.ws server.

- From the node itself (https://node.kadena.ws): version, block height, sync status
  against the network tip, and latency from the visitor.
- From the public node crawler (nodes.denascan.com, the same source nodes.kadena.ws
  uses): uptime (share of crawler checks answered) and the "online since" date. The card
  matches the node by its IP, 193.122.85.1 (const NODE_IP in the script).

States: "Online" (default; no figures shown until a source answers), "In sync" (teal),
"Syncing" (orange), "Not responding" (crawler marks it dead, or the API stopped answering).
The card never shows a figure it has not read live.

Today node.kadena.ws has no DNS record, so only the crawler-based fields (uptime, online
since, block height) can appear. Version, latency and "Public API" appear once step 1-2
below are done.

For the node-API fields to appear, on the Oracle node (193.122.85.1):
1. Put nginx in front of the Chainweb service API (port 1848) as https://node.kadena.ws
   (DNS: A record `node` -> 193.122.85.1; certbot for the cert).
2. In that server block add:
       add_header Access-Control-Allow-Origin "https://kadena.ws" always;
3. Keep the P2P port (1789) reachable so the crawler finds the node and uptime starts.
Nothing else on the kadena.ws server changes.
