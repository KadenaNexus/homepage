# Kadena Nexus deploy standard

A successful pull request to main is the production release. Each site repository runs a check on pull requests and deploys only after a successful push to main.

## Current sites

| Type | Site | Deployment |
|---|---|---|
| Static | kadena.ws | Copy site/index.html, site/logo-kadena-nexus.png, and site/privacy-policy.html to /var/www/kadena.ws |
| Static | kadenadevs.kadena.ws | Copy static-site/index.html and static-site/og.png to /var/www/kadenadevs.kadena.ws |
| Static | nodes.kadena.ws | Replace only /home/zero/monitor/dist/index.html. Never write dist/data. |
| Static | quantum.kadena.ws | Copy index.html and nexus-mark.png. Preserve assessment.json and status.json. |
| App | marketplace.kadena.ws | Run the fixed deploy-marketplace server script after checks. This deploys the frontend; the API process remains separate. |
| App | earn.kadena.ws | Run the fixed deploy-earn server script after backend and Pact tests. |
| App | adoption.kadena.ws | Run the fixed deploy-adoption server script after backend and site tests/build. |

Mine/Garden is a later addition and is not configured yet.

Static workflows call deploy-static.yml. Its checks job also runs SEO checks before any deploy: every HTML page needs a title, meta description and canonical link; every index.html also needs an og:image, a twitter:card, valid JSON-LD and exactly one H1; a deployed robots.txt must point to a sitemap and must not block the whole site; a deployed sitemap.xml must be valid XML with at least one URL. A failure blocks the merge-to-deploy, with the reason in the job log. A caller may also pass an optional `build` command. It runs right after checkout in both the checks job (before the file and SEO checks) and the deploy job (before the copy), with a read-only GITHUB_TOKEN and without the SSH key. Callers that do not pass it are unchanged. Besides push and manual runs on main, a scheduled run on main also deploys live.

kadena.ws uses this for the Kadena news page: `python3 scripts/build_news.py` rebuilds site/news/index.html (and the news lastmod in sitemap.xml) from public data, and deploy.yml runs every Monday at 06:17 UTC. The rebuilt page is deployed straight from the workflow and is never committed, so main still changes only through pull requests. Each source has a timeout and is left off the page if it fails; if the page cannot be built, the committed copy is deployed. Edit site/news/nexus-updates.json (newest first) to add Kadena Nexus entries.

App workflows call deploy-app.yml after their own test job. The shared app workflow only permits the marketplace, earn, and adoption-index repositories and maps each repository to one fixed server script. Main-branch deployments fail if required secrets are missing or mismatched; they do not silently skip.

The shared workflows pin the server SSH host key. They do not need a DEPLOY_KNOWN_HOSTS secret. Static copies do not delete existing server files. The network monitor workflow writes to its existing index.html file and leaves its data directory alone.

App server scripts check out origin/main, install/build, restart only the intended PM2 processes, verify local health, and restore the prior checkout/build on failure. They do not run database migrations or contract/key commands. After the server succeeds and the public URL returns HTTP 200, GitHub Actions creates and pushes a deploy tag with the deployed commit. The GitHub Actions token needs contents: write for that deploy job.

## Repository Actions secrets

| Secret | Value or use |
|---|---|
| DEPLOY_HOST | 89.167.14.58. The organization-level secret can be inherited; a repository secret may override it. |
| DEPLOY_USER | deployer |
| DEPLOY_KEY | Private half of the deployer SSH key |
| DEPLOY_PATH | Exact web root for a static site. For nodes.kadena.ws, use /home/zero/monitor/dist/index.html. |
| DEPLOY_SCRIPT | App script name, such as deploy-marketplace, deploy-earn, or deploy-adoption. The shared workflow also accepts the full /usr/local/bin path. |
| PREVIEW_PATH | Optional static branch preview root, /var/www/preview.kadena.ws |

A pull request never receives a production deploy. Other branch pushes can be copied beneath PREVIEW_PATH when it is configured. DNS, HTTPS, and the noindex header for preview.kadena.ws still need the server administrator's manual setup before preview links are usable.

## What remains manual

DNS, nginx, certificates, firewall changes, production database migrations, contract deployments, contract keys, payouts, and .env files remain manual responsibilities of the technical lead. Add new domains only after the server root or app script, secrets, workflow, and HTTPS configuration have been reviewed.
