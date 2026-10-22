# kadena.ws DNS inventory

The kadena.ws zone is hosted at **GoDaddy** (nameservers `ns33.domaincontrol.com`, `ns34.domaincontrol.com`).
This list was read from public DNS on **21 Oct 2026** (zone serial 2026101900). GoDaddy's DNS panel is the source of
truth; update this file whenever a record is added, changed or removed.

## Servers

| Name | Where | Runs |
|---|---|---|
| Hetzner server | `89.167.14.58` | kadena.ws, Marketplace, Marketplace preview, Earn, Network Monitor, Adoption Index, Quantum, Kadena Devs |
| Saudi node (Oracle Cloud, Saudi Arabia) | `193.122.85.1` | Kadena node gateway, Kadena Garden |
| Netlify | `fluffy-hummingbird-d7ff3d.netlify.app` | escrow-admin (v10 escrow alerts) |

## Web records

| Host | Type | Value | Site |
|---|---|---|---|
| `kadena.ws` (`@`) | A | 89.167.14.58 | Homepage, /whales |
| `www` | CNAME | kadena.ws | Redirects to kadena.ws |
| `marketplace` | A | 89.167.14.58 | P2P Marketplace (live; listed in Linx Wallet) |
| `marketplace-advanced` | A | 89.167.14.58 | Marketplace v11 preview (added 19 Oct 2026) |
| `earn` | A | 89.167.14.58 | Kadena Earn |
| `nodes` | A | 89.167.14.58 | Network Monitor |
| `adoption` | A | 89.167.14.58 | Adoption Index |
| `quantum` | A | 89.167.14.58 | Quantum-Safe Kadena |
| `kadenadevs` | A | 89.167.14.58 | Kadena Devs |
| `mine` | A | 193.122.85.1 | Kadena Garden |
| `node` | A | 193.122.85.1 | Kadena node gateway (HTTPS) |
| `escrow` | CNAME | fluffy-hummingbird-d7ff3d.netlify.app | **Not serving:** Netlify answers "Not Found" and its certificate does not cover escrow.kadena.ws (see below) |

The earlier mistake noted in commit dd8b163 is fixed: `node.kadena.ws` resolves to 193.122.85.1 and the doubled name
`node.kadena.ws.kadena.ws` no longer exists.

## Email records

| Host | Type | Value | Purpose |
|---|---|---|---|
| `kadena.ws` | MX | 0 smtp.secureserver.net, 10 mailstore1.secureserver.net | GoDaddy mailboxes |
| `kadena.ws` | TXT | `v=spf1 include:secureserver.net -all` | SPF for GoDaddy mail |
| `kadena.ws` | TXT | `google-site-verification=qiiq6zTK…` | Google Search Console |
| `_dmarc` | TXT | `v=DMARC1; p=quarantine; adkim=r; aspf=r; rua=mailto:dmarc_rua@onsecureserver.net;` | DMARC |
| `resend._domainkey` | TXT | DKIM public key (`p=MIGfMA0…`) | Resend (app emails) |
| `send` | CNAME | send.forge.rmta.net | Resend sending subdomain (MX/SPF follow the CNAME) |

## Not in DNS (do not exist)

`api`, `devs`, `garden`, `whales`, `trace`, `chainproof`, `privacy`, `agentpay`, `mail`, `status`, `blog`, `docs`, `app`.
Add a record here before linking to any of these names.

## Open item: escrow.kadena.ws

The `escrow` CNAME points at the escrow-admin Netlify site, which is up under its own name
(`fluffy-hummingbird-d7ff3d.netlify.app`) but has no custom domain attached for `escrow.kadena.ws`. Either add
`escrow.kadena.ws` as a domain in that Netlify site (Netlify then issues the certificate), or delete the `escrow` record
in GoDaddy if the dashboard is no longer used.

## How to re-check

    for h in kadena.ws www marketplace marketplace-advanced earn nodes adoption quantum kadenadevs mine node escrow; do
      n=$h; [ "$h" = kadena.ws ] || n=$h.kadena.ws; dig +short "$n"; done
    dig +short MX kadena.ws; dig +short TXT kadena.ws
