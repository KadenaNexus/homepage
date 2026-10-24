# Kadena Whale Watch

Reads every block on all 20 Kadena chains and reports large KDA activity:

- **Wallet moves** of 100,000 KDA or more (cross-chain moves count once; a wallet moving its own KDA between chains is skipped; a relay hop with the same amount is merged into the first alert).
- **DEX trades** (net KDA bought or sold in one transaction, Mercatus and sushi-exchange) and **pool liquidity** adds/withdrawals of 100K+ KDA.
- **Platform share**: the 87,344,000 KDA in frozen `PS_C*` allocations is re-read every hour; any release, transfer or drop is alerted at once and never capped.
- **Flags**: "dormant wallet woke up" when the sender had no transactions for 365+ days (with its last active date), and receiver crossing 1M KDA.
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

Each alert ends with a DenaScan link to its transaction (`https://denascan.com/transactions/<request key>`). On X's pay-per-use API a post with a link costs about $0.20, against about $0.015 for a plain one, so alerts cost about $0.20 each: roughly $6–15 a month at 1–2 alerts a day, at most about $36 if the 6-a-day cap is reached every day. Daily and weekly summaries carry no link and stay at about $0.015.

Dry mode (the default) writes every post to `posts.jsonl` (on Actions: kadena.ws/whales/data/watcher/posts.jsonl) and sends nothing. Switch to `live` only after the bot account and keys are ready.

## Labels

`labels.json` names a wallet only when a checkable source supports it, and every entry records its source (CI rejects one without). Each label has a confidence level:

- **confirmed**: the exchange itself ties the wallet to it (a deposit address it issued sweeps into the wallet, or a withdrawal it made came from it), or on-chain contract data proves it (DEX pools from `get-pair`, OTC lockers from their capability guard).
- **likely**: strong circumstantial evidence, such as the wallet pausing and resuming within hours of the exchange's published suspension and resumption times. Always shown as "(likely)" on the page and in posts.

**Public names (Naif, Oct 24, 2026): only confirmed exchanges are named.** Today that is Gate (a Gate deposit address sweeps into its hot wallet and a Gate withdrawal came from it), the only centralized exchange still trading KDA, and CoinEx (a CoinEx withdrawal on Sep 16, 2026 came from its hot wallet k:7cfe37…8e10), which is shutting down. Once one wallet of an exchange is confirmed, all its labelled wallets show its name, with "likely" on the unconfirmed ones. Every other exchange wallet is shown in posts, summaries and on the page as "Other exchange" / "Other exchanges". `labels.json` keeps the likely name (OKX, Binance.US, KuCoin, MEXC, CoinEx, Bybit, TradeOgre, Coinmetro), its evidence and its `status` (delisted, withdrawals only, closed) for our own records; a likely label becomes public only once an exchange-issued deposit address or withdrawal confirms it.

**Closing exchanges.** A label can carry `closesOn` (the day withdrawals stop). Until then the watcher reads the KDA left in that exchange's labelled wallets every hour; the daily summary adds "⏳ CoinEx closes Dec 22: 24 KDA withdrawn, 3.24M left", and the page shows it under Exchange flows.

The wallets first listed as Binance (hot k:bfcfdd…bede9, sweep k:576b78…f666, storage k:9b067c…d320 with 36.9M) were relabelled OKX on Oct 24, 2026: their customer payouts ran through Binance's withdrawal deadline (Jan 12, 2026) and stopped at OKX's (Jan 22, 2026).

Wallets are never labelled from behaviour alone, and private individuals are never named.

To add a label, edit `labels.json` with its source and open a PR. After the merge, the next Actions run uses it. On the server option, re-run `install.sh`.

## Running it: GitHub Actions (default, no server setup)

`.github/workflows/whale-watch-run.yml` runs `actions-run.sh` every 5 minutes on main:

1. It restores the watcher state from `kadena.ws/whales/data/watcher/` (state.json, feed.json, posts.jsonl).
   - On the first run ever (HTTP 404), it seeds the last 30 days.
   - On any other restore problem, it stops, so an outage can never wipe the live feed.
2. It reads every block since the last run on all 20 chains, using public nodes, and posts.
3. It copies the page data and state to `/var/www/kadena.ws/whales/data/` with the existing deploy secrets (DEPLOY_HOST, DEPLOY_USER, DEPLOY_KEY, pinned host key).

Before every post, the state is copied to the server first (`CHECKPOINT_CMD`). If that copy fails, nothing is posted, so a failed run can never post twice.

GitHub sometimes delays scheduled runs. The watcher catches up on every missed block, so nothing is skipped, but alerts can arrive 5–20 minutes after the move. Actions runs are free because the repo is public.

**Switches** (repo Settings → Secrets and variables → Actions):
- Variable `WHALE_POST_MODE` = `live` turns on posting to X. Unset or `dry` writes posts to `kadena.ws/whales/data/watcher/posts.jsonl` only.
- Secrets `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN` and `X_ACCESS_SECRET` hold the bot account's keys.

To run it once by hand: Actions → whale-watch-run → Run workflow.

## Optional: run it as a service on the kadena.ws server (once, as root)

Running on the server gives near-real-time alerts and reads from the Saudi node. If you switch to it, disable the Actions workflow so only one watcher runs.

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
