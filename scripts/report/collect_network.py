"""Collect daily Kadena mainnet statistics from the public Chainweb GraphQL indexer.

Usage: python3 scripts/report/collect_network.py 2026-10-15 2026-10-31 days.json

For each chain and each UTC day: the first block height at or after 00:00 UTC
(binary search on block creationTime), then every block of the day read in
50-block windows (the indexer returns at most about 50 blocks per query, and its
bulk transaction count ignores filters). Only canonical blocks count. Per day:
blocks, transactions (non-coinbase, per chain; calls to the free.block-history
recorder counted separately) and hashrate (sum of block
difficulty / 86,400 s). Progress is cached next to the output file
(<out>.heights.json, <out>.cache.jsonl), so an interrupted run resumes.
Takes roughly 1 minute per day of data. Python 3 standard library only.
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import sys
import time
import urllib.request

G = "https://graphql.chaddex.com/graphql/v0"
CHAINS = list(range(20))
# Automated calls to the free.block-history contract (an on-chain record of each
# block's hash and time) are counted separately: until October 12, 2026 they were
# most of Kadena's transactions, about 8 per block on every chain.
RECORDER = "block-history.attest"


def q(s, tries=5):
    for i in range(tries):
        try:
            r = urllib.request.Request(G, data=json.dumps({"query": s}).encode(),
                                       headers={"content-type": "application/json"})
            d = json.load(urllib.request.urlopen(r, timeout=90))
            if "errors" in d:
                raise RuntimeError(d["errors"])
            return d["data"]
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(2 + 3 * i)


def recorder_calls(block):
    return sum(RECORDER in (((e["node"]["cmd"]["payload"] or {}).get("code")) or "")
               for e in block["transactions"]["edges"])


def block_time(chain, h):
    d = q('{ blocksFromHeight(startHeight:%d, endHeight:%d, chainIds:["%d"], first:1){ edges { node { creationTime } } } }' % (h, h, chain))
    e = d["blocksFromHeight"]["edges"]
    return dt.datetime.fromisoformat(e[0]["node"]["creationTime"].replace("Z", "+00:00")) if e else None


def tip(chain):
    d = q('{ blocksFromDepth(chainIds:["%d"], minimumDepth:0, first:1){ edges { node { height creationTime } } } }' % chain)
    n = d["blocksFromDepth"]["edges"][0]["node"]
    return n["height"], dt.datetime.fromisoformat(n["creationTime"].replace("Z", "+00:00"))


def height_at(chain, when, tip_h, tip_t):
    """Lowest height whose creationTime >= when."""
    guess = tip_h - int((tip_t - when).total_seconds() / 30)
    lo, hi = guess - 400, guess + 400
    while block_time(chain, lo) >= when:
        lo -= 800
    while block_time(chain, hi) < when:
        hi += 800
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if block_time(chain, mid) >= when:
            hi = mid
        else:
            lo = mid
    return hi


def main(start, end, out):
    days = []
    d = dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc)
    stop = dt.datetime.fromisoformat(end).replace(tzinfo=dt.timezone.utc)
    while d <= stop:
        days.append(d)
        d += dt.timedelta(days=1)
    bounds = days + [days[-1] + dt.timedelta(days=1)]
    tips = {c: tip(c) for c in CHAINS}

    def chain_heights(c):
        return c, [height_at(c, b, *tips[c]) for b in bounds]

    hfile = out + ".heights.json"
    if os.path.exists(hfile):
        H = {int(k): v for k, v in json.load(open(hfile)).items()}
    else:
        with cf.ThreadPoolExecutor(8) as ex:
            H = dict(ex.map(chain_heights, CHAINS))
        json.dump(H, open(hfile, "w"))
    print("heights done", file=sys.stderr)

    # 50-block windows: the indexer returns at most ~50 blocks per query.
    wins = []
    for c in CHAINS:
        for i in range(len(days)):
            h0, h1 = H[c][i], H[c][i + 1]
            for s in range(h0, h1, 50):
                wins.append((c, i, s, min(s + 49, h1 - 1)))

    def work(w):
        c, i, s, e = w
        # first:100 blocks x first:12 transactions stays under the indexer's complexity limit.
        r = q('{ blocksFromHeight(startHeight:%d, endHeight:%d, chainIds:["%d"], first:100){ edges { node { canonical height difficulty transactions(first:12){ totalCount edges { node { cmd { payload { ... on ExecutionPayload { code } } } } } } } } } }' % (s, e, c))["blocksFromHeight"]["edges"]
        r = [x["node"] for x in r if x["node"]["canonical"]]
        att = 0
        for x in r:
            a = recorder_calls(x)
            if x["transactions"]["totalCount"] > 12:   # read the whole block
                b = q('{ blocksFromHeight(startHeight:%d, endHeight:%d, chainIds:["%d"], first:6){ edges { node { canonical transactions(first:100){ totalCount edges { node { cmd { payload { ... on ExecutionPayload { code } } } } } } } } } }' % (x["height"], x["height"], c))
                a = recorder_calls([e["node"] for e in b["blocksFromHeight"]["edges"] if e["node"]["canonical"]][0])
            att += a
        return c, i, len(r), sum(x["transactions"]["totalCount"] for x in r), sum(int(x["difficulty"]) for x in r), att

    acc = {(c, i): [0, 0, 0, 0] for c in CHAINS for i in range(len(days))}
    cfile = out + ".cache.jsonl"
    done = {}
    if os.path.exists(cfile):
        for ln in open(cfile):
            try:
                r = json.loads(ln); done[tuple(r[:3])] = r
            except ValueError:
                pass
    todo = [w for w in wins if (w[0], w[1], w[2]) not in done]
    print("resuming:", len(done), "cached,", len(todo), "to go", file=sys.stderr, flush=True)

    def work2(w):
        c, i, nb, tx, diff, att = work(w)
        return [c, i, w[2], nb, tx, diff, att]

    with open(cfile, "a") as cf_out, cf.ThreadPoolExecutor(8) as ex:
        for k, r in enumerate(ex.map(work2, todo)):
            cf_out.write(json.dumps(r) + "\n"); cf_out.flush()
            done[tuple(r[:3])] = r
            if k % 1000 == 0:
                print(len(done), "/", len(wins), file=sys.stderr, flush=True)
    for r in done.values():
        a = acc[(r[0], r[1])]; a[0] += r[3]; a[1] += r[4]; a[2] += r[5]; a[3] += r[6]

    rows = []
    for i, day in enumerate(days):
        rows.append({"date": day.date().isoformat(),
                     "blocks": sum(acc[(c, i)][0] for c in CHAINS),
                     "transactions": sum(acc[(c, i)][1] for c in CHAINS),
                     "hashrate_phs": round(sum(acc[(c, i)][2] for c in CHAINS) / 86400 / 1e15, 3),
                     "recorder_transactions": sum(acc[(c, i)][3] for c in CHAINS),
                     "per_chain_tx": [acc[(c, i)][1] for c in CHAINS],
                     "per_chain_recorder": [acc[(c, i)][3] for c in CHAINS]})
    json.dump({"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "source": G, "days": rows,
               "heights": {str(c): H[c] for c in CHAINS},
               "boundaries_utc": [b.isoformat() for b in bounds]}, open(out, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
