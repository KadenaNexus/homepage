# Kadena Whale Watch

Reads every block on all 20 Kadena chains and reports large KDA activity:

- **Wallet moves** of 100,000 KDA or more (cross-chain moves count once; a wallet moving its own KDA between chains is skipped; a relay hop with the same amount is merged into the first alert).
- **DEX trades** (net KDA bought or sold in one transaction, Mercatus and sushi-exchange) and **pool liquidity** adds/withdrawals of 100K+ KDA.
- **Platform share**: the 87,344,000 KDA in frozen `PS_C*` allocations is re-read every hour; any release, transfer or drop is alerted at once and never capped.
- **Flags**: sender idle 365+ days, receiver crossing 1M KDA.
- **Exchange flows**: every transfer to or from a labelled exchange wallet, any size.
- **Holder counts**: wallets with 100K+, 1M+, 10M+ KDA once a day (from the public indexer).

It writes `feed.json`, `stats.json` and `status.json` into `/var/www/kadena.ws/whales/data/` for **kadena.ws/whales** (the page is `site/whales/index.html`, deployed by the normal kadena.ws workflow, which never touches `data/`), and posts to X.

## Posting

| Post | When |
|---|---|
| Move / DEX / pool alert | As it happens, 100K+ KDA, at most 6 a day (Riyadh day). Extra ones are counted in the summary. Only items less than 3 hours old are posted, so a restart never posts history. |
| Platform-share alert | Always, no cap. |
| Daily summary | 21:00 Riyadh. |
| Weekly digest | Friday 21:00 Riyadh, instead of that day's summary. |

Posts contain no links: on X's pay-per-use API a plain post costs about $0.015 and a post with a link about $0.20. Expected volume is 2–3 posts a day, about $1–2 a month.

`POST_MODE=dry` (the default) writes every post to `/var/lib/whale-watch/posts.jsonl` and sends nothing. Switch to `live` only after the bot account and keys are ready.

## Labels

`labels.json` names a wallet only when a public, checkable source supports it: on-chain contract data (DEX pool accounts returned by `get-pair`, OTC locker capability guards) or a self-describing account name. Every entry records its source; CI rejects an entry without one. Wallets are never labelled from behaviour alone. The two busiest senders (k:0d584a…2fb0 and k:7cfe37…8e10) look like exchange hot wallets but no public source names them, so they stay "unknown wallet". To add a label: edit `labels.json` with the source, open a PR, then re-run `install.sh` (the watcher reloads labels without a restart).

## Install on the kadena.ws server (once, as root)

```bash
cd /path/to/homepage && git pull
sudo bash services/whale-watch/install.sh
```

This creates the `whalewatch` system user, copies the code to `/opt/whale-watch`, creates `/etc/whale-watch.env` (mode 600, `POST_MODE=dry`), seeds the last 30 days into the feed (nothing posted), and starts the `whale-watch` systemd service. Needs Node 18+ installed system-wide. Re-running it updates the code and labels and keeps state and settings.

It reads the Saudi node first (`http://193.122.85.1:1848`, whose service API is open to this server only) and falls back to `api.chainweb-community.org`.

## Going live on X

1. Create the bot account (e.g. @KDAWhaleWatch) and set it as an automated account under its own settings, managed by @KadenaNexus.
2. On developer.x.com, create an app with **Read and Write** permission and pay-per-use credit. Generate the API key and secret and the access token and secret **for the bot account**.
3. Put the four values in `/etc/whale-watch.env`, set `POST_MODE=live`, then `systemctl restart whale-watch`.

## Operations

- Logs: `journalctl -u whale-watch -f`
- Posts (dry or live): `/var/lib/whale-watch/posts.jsonl`
- State: `/var/lib/whale-watch/state.json` (delete it only to start over; the next start reads from the current block)
- Tests: `node --test services/whale-watch/test/*.test.mjs` (real mainnet blocks as fixtures, no network)
- Replay a height range for testing: `DATA_DIR=/tmp/ww PUBLIC_DIR=/tmp/ww/p node watcher.mjs --start-height 7257500 --stop-height 7258400 --once`
