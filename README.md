# Kadena Nexus homepage

Source of https://kadena.ws, part of [Kadena Nexus](https://kadena.ws).

| Path | What it is |
|---|---|
| `site/index.html` | The homepage: a single static HTML file (inline CSS, JS and logo). Reads the Adoption Index, the Saudi node and the chain tip in the browser; no backend of its own. |
| `site/privacy-policy.html` | Privacy policy page. |
| `site/nginx-kadena.ws.conf` | nginx server block for kadena.ws. |
| `deploy/kadena-ws-update/` | Mustafa's installer and node-gateway setup for the Oct 2026 update (homepage node card, nodes page, node.kadena.ws gateway, crawler proxy). |
| `DEPLOY.md` | How to put a new version live (file swap on Hetzner). |

Built Oct 2026 to replace the GoDaddy site builder page. Design and HTML by Saudi.KDA with Claude; deployment by Mustafa Zahid.

History note: this repository was split out of `KadenaSaudi/Kadena-NEXUS` (branch `codex/kadena-homepage-node`), which is why the early history also contains the Kadena Devs site; those files were removed in the first commit here and live in `KadenaNexus/devs-site`.
