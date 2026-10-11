# Kadena Nexus deploy standard

Every Kadena Nexus site deploys from GitHub. Merging to `main` is the deployment; nobody copies files to the server by hand. This applies to every current domain and to every new one.

A new domain is not ready to launch until (1) it follows the [header standard](brand/HEADER-STANDARD.md) and (2) it deploys automatically as described here.

## Two kinds of site, two shared workflows

Both live in this repo and are called from each site's repo with a few lines.

| Kind | Sites | Workflow | What happens |
|---|---|---|---|
| Static | kadena.ws, kadenadevs.kadena.ws, nodes.kadena.ws, quantum.kadena.ws | [`deploy-static.yml`](../.github/workflows/deploy-static.yml) | `main`: files copied into the live web root. Other branches: copied to `preview.kadena.ws/<repo>/<branch>/` for review. Nothing on the server is ever deleted. |
| App | marketplace.kadena.ws, earn.kadena.ws, adoption.kadena.ws, mine.kadena.ws (Garden) | [`deploy-app.yml`](../.github/workflows/deploy-app.yml) | `main` only, after tests pass: runs the app's own deploy script on the server (pull, build, restart, tag). |

Both check the live URL afterwards and fail loudly if it doesn't answer.

## Calling the workflow from a site repo

Static site, in `.github/workflows/deploy.yml`:

```yaml
name: deploy
on:
  push:
  workflow_dispatch:
jobs:
  site:
    uses: KadenaNexus/homepage/.github/workflows/deploy-static.yml@main
    with:
      source: static-site            # folder to publish
      # files: "index.html og.png"   # optional: only these files
      url: https://kadenadevs.kadena.ws/
    secrets: inherit
```

App, after its test job:

```yaml
name: deploy
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: npm ci && npm test
  deploy:
    needs: test
    uses: KadenaNexus/homepage/.github/workflows/deploy-app.yml@main
    with:
      url: https://earn.kadena.ws/
    secrets: inherit
```

## Server side (once per site)

- One deploy user, `deployer`, with an SSH key used only by GitHub. No password login, no general sudo.
- **Static site:** `deployer` may write into that site's web root only (for nodes.kadena.ws: `index.html` and `og.png`, never `dist/data`).
- **App:** a root-owned script `/usr/local/bin/deploy-<app>` that pulls `main`, runs `npm ci` and the build, restarts its pm2 processes, keeps the previous build for rollback, tags the release, and exits non-zero on any failure. It never touches `.env`, databases or keys. `/etc/sudoers.d/deployer` allows `deployer` to run exactly these scripts and nothing else.

## Repository secrets (Settings, Secrets and variables, Actions)

| Secret | Static | App |
|---|---|---|
| `DEPLOY_HOST` | server address | server address |
| `DEPLOY_USER` | `deployer` | `deployer` |
| `DEPLOY_KEY` | private key | private key |
| `DEPLOY_PATH` | live web root | |
| `PREVIEW_PATH` | `/var/www/preview.kadena.ws` | |
| `DEPLOY_SCRIPT` | | `deploy-<app>` |
| `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan <host>` (recommended) | same |

Until the secrets exist, the workflows skip quietly, so adding them to a repo early is safe.

## Adding a new domain (checklist)

1. Repo in KadenaNexus, header standard applied.
2. DNS record at GoDaddy, nginx block and certificate on the server.
3. Web root writable by `deployer` (static) or `deploy-<app>` script plus sudoers line (app).
4. Secrets added to the repo.
5. `deploy.yml` added (copy from above), first deploy watched in the Actions tab.
6. URL added to the uptime check in `homepage/.github/scripts/uptime.js`.

## What stays manual

Contract deployments and upgrades, private keys and payouts, `.env` files, nginx, firewall and databases. Those are changed by hand on the server by the technical lead.
