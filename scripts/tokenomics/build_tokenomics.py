#!/usr/bin/env python3
"""Build kadena.ws/tokenomics/ – KDA supply before and after the November 2025 fork.

Runs in the daily site build (before update_facts.py, which reuses its numbers):
  python3 scripts/tokenomics/build_tokenomics.py

Everything that can change is read from Kadena mainnet on each run:
  - every genesis allocation in coin.allocation-table (claimed or not), so the
    frozen platform share is re-counted daily
  - the platform-share keysets PS_C0 … PS_C9 (still the community 3-of-5?)
  - balances of the two accounts that received most platform-share releases
  - the current block height, for mining so far (protocol reward schedule)
History that cannot change (who claimed what before the fork) is fixed below,
from the same chain data, checked on October 15, 2026.

Writes site/tokenomics/index.html and site/tokenomics/tokenomics.json.
Never fails the build: if the chain cannot be read, the committed page stays.
Environment: TOKENOMICS_OFFLINE=1 skips network access (keeps the committed page).
Python 3 standard library only.
"""
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SITE = os.path.join(ROOT, "site")
OUT = os.path.join(SITE, "tokenomics")
sys.path.insert(0, os.path.join(ROOT, "scripts", "report"))
import build_report as br  # noqa: E402  (page shell, charts helpers)

G = "https://graphql.chaddex.com/graphql/v0"
URL = "https://kadena.ws/tokenomics/"
TODAY = dt.datetime.now(dt.timezone.utc).date()

# The community 3-of-5 that the fork gave the platform share to (chainweb-node 3.0,
# commit 3149131c, block 6,332,978). Names and roles as the KCE "Who We Are" post gives them.
HOLDERS = [
    ("Edmund Noble", "previously technical lead for Chainweb at Kadena LLC", "4a6a31a21c0561a05b0d608bd27e9042e2d6d66eca855c7b5a20d052398257a9"),
    ("Jose Cardona", "previously technical lead for Pact at Kadena LLC", "128ad09365148288f27c16ce4ee3aceb524e00717cb253cb9f233bdea59b227e"),
    ("Louis Page", "previously devops lead at Kadena", "b21b3614b1e36c9b15d74efb4f3acaa846e2d96e81aa1661ae5686c8cbc36e7c"),
    ("Pascal Sclafer", "long-time community member and engineer", "be6918da77866bd20fc2f6581dc9cdacd98372b9c427ac6f9e4f731f7861bca8"),
    ("Tadeas Kmenta", "co-founder and CIO at InFlux Technologies", "09f3981dc8855bc5eea026d266c9f055eae79dc9bfb8a34a6af50dad062be55a"),
]
FORK_BLOCK, FORK_DATE = 6_332_978, dt.date(2025, 11, 6)
FROZEN_AT_FORK = 87_344_000.0
# Platform share claimed before the fork, by year of the transfer out of the PS accounts.
PS_CLAIMED_BY_YEAR = [("2021", 2_400_000), ("2022", 8_399_999), ("2023", 32_984_000), ("2024", 38_400_000), ("2025", 27_872_000)]
LAST_CLAIM = dt.date(2025, 10, 9)
RECEIVERS = [
    ("w:DD-js2J0pYzsFkqpaTckDmHAH3bVLu5JqwyIbx0yJbg:keys-2", 78_272_000, "October 2023 – October 2025"),
    ("w:u-on-LXLTkp7DLszyPLphqfDzS6WTvfTtqNaLvEDrAI:keys-2", 24_867_211, "October 2022 – August 2023"),
]
RECEIVERS_OTHER = 6_916_789          # 10 smaller receivers, 2021–2022
REMEDIATED = 1_567_076               # removed by the 2020 coin remediations (chainweb-node pact/coin-contract/remediations/mainnet)
NOT_CREATED = 10_000_000             # "Coinlist Non-US" line in the allocations CSV that was never in the genesis files
GROUP_LABELS = {
    "PS": "Platform share (PS)", "Coinlist": "CoinList token sale", "ST": "ST", "CS": "CS", "SB": "SB",
    "FTS": "FTS", "SA": "SA", "EB": "EB",
}
COLORS = {"mined": "#2a78d6", "claimed": "#1baf7a", "frozen": "#eb6834", "future": "#D6E0E4"}


def log(m):
    print(f"build_tokenomics: {m}", file=sys.stderr, flush=True)


def post(q):
    r = urllib.request.Request(G, data=json.dumps({"query": q}).encode(), headers={"content-type": "application/json"})
    d = json.load(urllib.request.urlopen(r, timeout=90))
    if "errors" in d:
        raise RuntimeError(d["errors"])
    return d["data"]


def pact(items):
    """[(code, chain)] -> [parsed result or None]"""
    q = "{ pactQuery(pactQuery:[%s]) { status result error } }" % ",".join(
        "{code:%s, chainId:\"%s\"}" % (json.dumps(c), ch) for c, ch in items)
    return [json.loads(x["result"]) if x["status"] == "success" else None for x in post(q)["pactQuery"]]


def num(v):
    if isinstance(v, dict):
        return float(v.get("decimal", v.get("int", 0)))
    return float(v)


def group(keyset):
    if keyset.startswith("PS_"):
        return "PS"
    if keyset.startswith("Coinlist"):
        return "Coinlist"
    for g in ("FTS", "ST", "CS", "SB", "SA", "EB"):
        if keyset.startswith(g):
            return g
    return "Other"


def mined_to(height):
    rows = [(int(r[0]), float(r[1])) for r in csv.reader(open(os.path.join(HERE, "miner_rewards.csv"))) if len(r) == 2]
    tot, prev = 0.0, 0
    for hb, val in rows:
        lo, hi = prev + 1, min(hb, height)
        if hi >= lo:
            tot += (hi - lo + 1) * val
        prev = hb
        if hb >= height:
            break
    now = next(v for h, v in rows if h >= height)
    nxt = next(((h, v) for h, v in rows if h >= height and v != now), None)
    return tot, sum((hb - p) * v for (hb, v), p in zip(rows, [0] + [r[0] for r in rows[:-1]])), now, nxt, rows[-1][0]


# ---------------------------------------------------------------- read the chain
def read_chain():
    data = json.load(open(os.path.join(HERE, "genesis_allocations.json")))["allocations"]
    allocs = [{"name": a[0], "date": a[1], "keyset": a[2], "amount": float(a[3]), "chain": a[4], "group": group(a[2])} for a in data]
    for i in range(0, len(allocs), 20):
        batch = allocs[i:i + 20]
        res = pact([(f'(read coin.allocation-table "{a["name"]}")', str(a["chain"])) for a in batch])
        for a, r in zip(batch, res):
            if r is None:
                raise RuntimeError(f"cannot read allocation {a['name']}")
            a["redeemed"] = bool(r["redeemed"])
    keysets = pact([(f'(describe-keyset "PS_C{c}")', str(c)) for c in range(10)])
    holder_keys = {k for _, _, k in HOLDERS}
    ks_ok = all(k and k.get("pred") == "user.pred.keys-3" and set(k.get("keys", [])) == holder_keys for k in keysets)
    receivers = []
    for acct, got, when in RECEIVERS:
        bal = pact([(f'(try 0.0 (coin.get-balance "{acct}"))', str(c)) for c in range(20)])
        receivers.append((acct, got, when, sum(num(b) for b in bal if b is not None)))
    d = post('{ blocksFromDepth(chainIds:["0"], minimumDepth:0, first:1){ edges { node { height } } } networkInfo { coinsInCirculation } }')
    height = d["blocksFromDepth"]["edges"][0]["node"]["height"]
    return allocs, ks_ok, receivers, height, float(d["networkInfo"]["coinsInCirculation"])


# ---------------------------------------------------------------- numbers
def compute(allocs, ks_ok, receivers, height, indexer_circ):
    mined, mining_total, reward_now, next_step, last_height = mined_to(height)
    groups = {}
    for a in allocs:
        g = groups.setdefault(a["group"], {"total": 0.0, "claimed": 0.0, "unclaimed": 0.0})
        g["total"] += a["amount"]
        g["claimed" if a["redeemed"] else "unclaimed"] += a["amount"]
    ps_open = [a for a in allocs if a["group"] == "PS" and not a["redeemed"]]
    frozen = sum(a["amount"] for a in ps_open)
    by_chain = {}
    for a in ps_open:
        by_chain[a["chain"]] = by_chain.get(a["chain"], 0) + a["amount"]
    genesis = sum(a["amount"] for a in allocs)
    claimed = sum(g["claimed"] for g in groups.values())
    other_unclaimed = sum(g["unclaimed"] for k, g in groups.items() if k != "PS")
    circ = mined + claimed - REMEDIATED
    years_left = (last_height - height) / (2 * 60 * 24 * 365.25)
    return {
        "date": TODAY.isoformat(), "height": height,
        "max_supply_nominal": 1_000_000_000, "protocol_total": mining_total + genesis,
        "mining_total": mining_total, "mined": mined, "mining_left": mining_total - mined,
        "reward_per_height": reward_now, "reward_per_block": reward_now / 20, "per_day": reward_now * 2880,
        "next_step": next_step, "mining_ends_year": TODAY.year + round(years_left),
        "genesis": genesis, "genesis_entries": len(allocs), "claimed": claimed, "frozen": frozen, "frozen_entries": len(ps_open),
        "frozen_by_chain": dict(sorted(by_chain.items())), "moved_since_fork": FROZEN_AT_FORK - frozen,
        "other_unclaimed": other_unclaimed, "groups": groups, "keysets_unchanged": ks_ok,
        "receivers": receivers, "circulating": circ, "indexer_circulating": indexer_circ,
        "remediated": REMEDIATED, "not_created": NOT_CREATED,
    }


# ---------------------------------------------------------------- page
def M(v, d=1):
    return f"{v / 1e6:,.{d}f}M"


def supply_bar(n):
    """One 100% bar of everything the protocol will ever create."""
    segs = [("mined", "Mined so far", n["mined"]), ("claimed", "Genesis allocations claimed", n["claimed"]),
            ("frozen", "Platform share, frozen", n["frozen"]), ("future", "Mining still to come", n["mining_left"])]
    total = n["protocol_total"]
    w, h, x = 960, 56, 0.0
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="t-bar" class="chart sbar">']
    for key, label, v in segs:
        sw = v / total * w
        gap = 2 if key != "future" else 0
        parts.append(f'<g class="m"><rect x="{x:.1f}" y="4" width="{max(sw - gap, 1):.1f}" height="{h - 8}" rx="4" fill="{COLORS[key]}"/>'
                     f'<title>{label}: {v:,.0f} KDA ({v / total * 100:.1f}%)</title></g>')
        x += sw
    parts.append("</svg>")
    legend = "".join(
        f'<li><span class="sw" style="background:{COLORS[k]}"></span><b>{l}</b> {M(v)} KDA <span class="pc">{v / total * 100:.1f}%</span></li>'
        for k, l, v in segs)
    return "".join(parts) + f'<ul class="legend">{legend}</ul>'


def year_bars(n):
    rows = [{"label": y, "tick": y, "v": v} for y, v in PS_CLAIMED_BY_YEAR]
    return br.bars(rows, "v", "KDA of platform share claimed", lambda v: f"{v / 1e6:g}M" if v else "0", "t-claims", h=260)


def build(n):
    esc = html.escape
    g = n["groups"]
    rec_rows = [[f'<code>{esc(a[:22])}…</code>', f"{got:,.0f}", when, f"{now:,.0f}"] for a, got, when, now in n["receivers"]]
    rec_rows.append(["10 other accounts", f"{RECEIVERS_OTHER:,.0f}", "2021 – 2022", "–"])
    grp_rows = []
    for k in ("PS", "ST", "Coinlist", "CS", "SB", "FTS", "SA", "EB"):
        if k in g:
            grp_rows.append([GROUP_LABELS.get(k, k), f'{g[k]["total"]:,.0f}', f'{g[k]["claimed"]:,.0f}', f'{g[k]["unclaimed"]:,.2f}'.rstrip("0").rstrip(".")])
    chain_rows = [[f"Chain {c}", f"{v:,.0f}"] for c, v in n["frozen_by_chain"].items()]
    hold_rows = [[esc(nm), esc(role), f"<code>{k[:8]}…{k[-6:]}</code>"] for nm, role, k in HOLDERS]
    moved = n["moved_since_fork"]
    moved_line = ("Nothing has been released since the fork." if moved < 1 else
                  f"{moved:,.0f} KDA has been released from it since the fork.")
    ks_line = ("All ten keysets were still the community 3-of-5 when this page was updated."
               if n["keysets_unchanged"] else "Note: at least one of the ten keysets no longer matches the 3-of-5 set out at the fork.")
    nxt = n["next_step"]
    gap = n["indexer_circulating"] - n["circulating"]
    faq = [
        ("Where are the frozen Kadena platform tokens?",
         f"They are {n['frozen']:,.0f} KDA of platform-share allocations that were never claimed. They sit in the coin contract's allocation table, not in an account balance, as {n['frozen_entries']} entries named PS_C0_… to PS_C9_… on chains 0–9."),
        ("Who controls the Kadena platform share now?",
         "Since block 6,332,978 (November 6, 2025) the platform-share keysets PS_C0 to PS_C9 need 3 of 5 signatures from Edmund Noble, Jose Cardona, Louis Page, Pascal Sclafer and Tadeas Kmenta. The community has said the share stays frozen until a foundation answerable to the community exists."),
        ("What is the maximum supply of KDA?",
         f"The protocol creates {n['protocol_total'] / 1e6:,.0f} million KDA in total: 700 million through mining over about 120 years and {n['genesis'] / 1e6:,.0f} million in genesis allocations. The commonly quoted 1 billion includes a 10 million line that was never created at genesis."),
        ("How much KDA is in circulation?",
         f"By Kadena Nexus's count, about {n['circulating'] / 1e6:,.0f} million KDA: {n['mined'] / 1e6:,.1f} million mined plus {n['claimed'] / 1e6:,.1f} million of claimed genesis allocations, less about 1.6 million removed by the 2020 remediations."),
    ]
    ld = {"@context": "https://schema.org", "@graph": [
        br.ORG,
        {"@type": "Article", "headline": "KDA tokenomics after the fork", "url": URL, "inLanguage": "en",
         "description": "Where the frozen Kadena platform share is, who controls it, how much KDA has been mined and claimed, before and after the November 2025 community fork.",
         "datePublished": "2026-10-15", "dateModified": TODAY.isoformat(),
         "author": {"@id": "https://kadena.ws/#org"}, "publisher": {"@id": "https://kadena.ws/#org"},
         "image": "https://kadena.ws/og/og-nodes.jpg", "about": ["KDA", "Kadena", "tokenomics", "Kadena Community Edition"]},
        {"@type": "Dataset", "name": "KDA supply and platform share, read from Kadena mainnet", "url": URL,
         "description": "Daily on-chain reading of every Kadena genesis allocation (claimed or not), the platform-share keysets and mining to date.",
         "creator": {"@id": "https://kadena.ws/#org"}, "license": "https://creativecommons.org/licenses/by/4.0/",
         "isAccessibleForFree": True, "dateModified": TODAY.isoformat(),
         "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": URL + "tokenomics.json"}]},
        {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Kadena Nexus", "item": "https://kadena.ws/"},
            {"@type": "ListItem", "position": 2, "name": "KDA tokenomics", "item": URL}]}]}
    upd = (f'<p class="upd"><span class="dot" aria-hidden="true"></span><span>Updated {TODAY:%b} {TODAY.day}, {TODAY.year} · '
           f'<span class="nx">read from mainnet every day</span></span></p>')
    body = f'''<main id="main">
  <article class="policy" aria-labelledby="r-title">
    <div class="wrap">
      <div class="topbar"><p class="crumb"><a href="/">Kadena Nexus</a> / Tokenomics</p>{upd}</div>
      <h1 id="r-title">KDA tokenomics after the fork</h1>
      <p class="lede">How much KDA exists, how much has been mined and claimed, and where the frozen platform share is. Every number on this page is read from Kadena mainnet and the protocol's own rules, and refreshed daily.</p>

      <h2>At a glance</h2>
      {br.table(["", "KDA"], [
        ["Created by the protocol in total", f"{n['protocol_total']:,.0f}"],
        ["Mined so far", f"{n['mined']:,.0f}"],
        ["Genesis allocations claimed", f"{n['claimed']:,.0f}"],
        ["<b>Platform share, frozen since the fork</b>", f"<b>{n['frozen']:,.0f}</b>"],
        ["Other genesis allocations never claimed", f"{n['other_unclaimed']:,.0f}"],
        ["Mining still to come", f"{n['mining_left']:,.0f}"],
        ["In circulation (Kadena Nexus count)", f"about {n['circulating'] / 1e6:,.1f} million"],
        ["New KDA mined per day", f"about {n['per_day']:,.0f}"],
      ])}

      <h2 id="t-bar">Where the {n['protocol_total'] / 1e6:,.0f} million KDA stands</h2>
      <p>Everything the protocol will ever create, split by what has happened to it so far. Other unclaimed allocations ({M(n['other_unclaimed'])}) are too small to show.</p>
      {supply_bar(n)}

      <h2>Before the fork: 2019 – October 2025</h2>
      <p>Kadena's supply has two sources. <b>Mining</b> pays 700 million KDA to miners over about 120 years on a fixed schedule built into the node software. <b>Genesis allocations</b>, {n['genesis']:,.0f} KDA in {n['genesis_entries']:,} entries on chains 0–9, were written into the chain at launch with release dates from 2019 to 2024. Each allocation becomes spendable only when its keyset holder claims it after the release date. The commonly quoted 1 billion maximum includes a 10 million "Coinlist Non-US" line from the published allocation list that was never created at genesis.</p>
      <details open><summary>Genesis allocations by label</summary>{br.table(["Genesis label", "Allocated", "Claimed", "Never claimed"], grp_rows)}</details>
      <p class="note">Labels are the keyset names in the genesis files. Only the platform share (PS) and the CoinList sale are named outright there.</p>
      <p>The <b>platform share</b> was the largest allocation: 197,400,000 KDA, released monthly from January 2021 to December 2024 and controlled by Kadena LLC's keysets PS_C0 to PS_C9. Kadena LLC claimed 110,056,000 of it, the last on {br.fdate(LAST_CLAIM)}, {LAST_CLAIM.year}, and left {FROZEN_AT_FORK:,.0f} unclaimed.</p>
      <h3 id="t-claims">Platform share claimed by Kadena LLC, by year</h3>
      {year_bars(n)}
      <p>Most of what was claimed went to two accounts. They are ordinary accounts under their own keys, so the fork did not change them.</p>
      {br.table(["Account", "Received from the platform share", "When", "Balance now"], rec_rows)}

      <h2>After the fork: November 2025 onward</h2>
      <p>Kadena LLC announced on October 21, 2025 that it was ceasing operations. The community node release, chainweb-node 3.0, included a one-time change at block {FORK_BLOCK:,} ({br.fdate(FORK_DATE)}, {FORK_DATE.year}): it handed the platform-share keysets PS_C0 to PS_C9, and six namespace admin keysets, to a new community multisig that needs <b>3 of 5</b> signatures. KDA in personal accounts was not touched.</p>
      {br.table(["Keyholder", "Background, as the community describes it", "Public key"], hold_rows)}
      <p>The KDA Community Edition team has said the platform share is <b>frozen until a foundation answerable to the community can be established</b>. {moved_line} {ks_line}</p>
      <h3>Where the frozen {n['frozen'] / 1e6:,.3f} million KDA is</h3>
      <p>It is not in an account balance, which is why it is hard to find in an explorer. It sits in the coin contract's allocation table as {n['frozen_entries']} entries named <code>PS_C0_…</code> to <code>PS_C9_…</code>, each with a release date that has already passed. Any 3 of the 5 keyholders could release it.</p>
      {br.table(["Chain", "Frozen platform share (KDA)"], chain_rows)}
      <p>Two other allocations were never claimed by their holders: SB ({g.get("SB", {}).get("unclaimed", 0):,.0f} KDA) and SA ({g.get("SA", {}).get("unclaimed", 0):,.0f} KDA). Their keysets were not changed.</p>

      <h2>Mining</h2>
      <p>Each block pays its miner {n['reward_per_block']:.6f} KDA right now, {n['reward_per_height']:.5f} KDA across the 20 chains for every block height, or about {n['per_day']:,.0f} KDA a day. {f"The reward steps down to {nxt[1] / 20:.6f} KDA a block at height {nxt[0]:,}, about {round((nxt[0] - n['height']) / 2880)} days from now. " if nxt else ""}So far {n['mined']:,.0f} KDA has been mined; {n['mining_left']:,.0f} is still to come, with the last rewards around {n['mining_ends_year']}.</p>

      <h2>Circulating supply</h2>
      <p>Kadena Nexus counts about <b>{n['circulating'] / 1e6:,.1f} million KDA</b> in circulation: everything mined, plus genesis allocations that have been claimed, less about 1.6 million removed by the 2020 coin remediations. The frozen platform share and other unclaimed allocations are not counted, because no account holds them. {f"The public Chainweb indexer reports {n['indexer_circulating'] / 1e6:,.1f} million; we have not yet found what explains the {abs(gap) / 1e6:,.1f} million difference, so treat circulating figures from any source with care." if abs(gap) > 1e6 else ""}</p>

      <h2>Check it yourself</h2>
      <ul>
        <li>A frozen entry, on chain 5: <code>(read coin.allocation-table "PS_C5_1314")</code> returns its amount and <code>"redeemed": false</code>.</li>
        <li>Who controls it: <code>(describe-keyset "PS_C5")</code> returns the 3-of-5 keys above with <code>user.pred.keys-3</code>.</li>
        <li>The fork change: commit <a href="https://github.com/kda-community/chainweb-node/commit/3149131c8ee19d230c8312756eafde0133180e2c">3149131c "Platform share migrate"</a> in kda-community/chainweb-node, released in <a href="https://github.com/kda-community/chainweb-node/releases/tag/3.0">3.0</a>.</li>
        <li>The community statement: <a href="https://medium.com/@communitykadena/who-we-are-e7f4ac192e6e">"Who We Are", KDA Community Edition</a>.</li>
        <li>Allocations and the reward schedule: <code>pact/genesis/mainnet/</code>, <code>allocations/</code> and <code>rewards/miner_rewards.csv</code> in the same repository.</li>
      </ul>
      <p><a class="dl" href="tokenomics.json" download>Download today's numbers (JSON)</a></p>

      <h2>Questions</h2>
      {"".join(f"<h3>{esc(q)}</h3><p>{esc(a)}</p>" for q, a in faq)}

      <h2>More</h2>
      <p>Network activity month by month: <a href="/reports/">Kadena network reports</a>. What changed in 2025: <a href="/community-edition/">What is Kadena Community Edition?</a> Buying KDA: <a href="/buy-kda/">How to buy KDA</a>.</p>
      <p class="updated">Kadena Nexus is an independent community project and is not affiliated with Kadena LLC. It works alongside the kda-community developers and the community DAO. Figures are Kadena Nexus readings of public chain data, not official statistics. Nothing here is financial advice.</p>
    </div>
  </article>
</main>'''
    css = f'''.sbar{{margin:.8rem 0 .2rem}}
.legend{{list-style:none;padding:0;margin:.4rem 0 1rem;display:flex;flex-wrap:wrap;gap:.4rem 1.4rem;font-size:.92rem}}
.legend li{{display:flex;align-items:center;gap:.45rem}}
.legend .sw{{width:.8rem;height:.8rem;border-radius:3px;flex:none}}
.legend b{{font-weight:600;color:var(--sand)}}
.legend .pc{{color:var(--mist)}}
.policy h3{{margin-top:1.4rem}}
'''
    page = br.shell(SITE, "KDA tokenomics after the fork: supply and the frozen platform share",
                    f"Where the frozen Kadena platform share is ({n['frozen'] / 1e6:,.1f} million KDA), who controls it, and how much KDA has been mined and claimed, before and after the November 2025 fork. Read from mainnet daily.",
                    URL, ld, css, body)
    page = page.replace("<title>KDA tokenomics after the fork: supply and the frozen platform share | Kadena Nexus</title>",
                        "<title>KDA Tokenomics: Supply and the Frozen Platform Share | Kadena Nexus</title>")
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(page)
    js = {k: v for k, v in n.items() if k not in ("receivers",)}
    js["receivers"] = [{"account": a, "received_platform_share": got, "period": w, "balance_now": round(now, 6)} for a, got, w, now in n["receivers"]]
    js["keyholders"] = [{"name": nm, "public_key": k} for nm, _, k in HOLDERS]
    js["fork"] = {"block": FORK_BLOCK, "date": FORK_DATE.isoformat(), "frozen_at_fork": FROZEN_AT_FORK}
    json.dump(js, open(os.path.join(OUT, "tokenomics.json"), "w"), indent=1)
    sm = os.path.join(SITE, "sitemap.xml")
    s = open(sm, encoding="utf-8").read()
    s = re.sub(r"(<loc>https://kadena\.ws/tokenomics/</loc><lastmod>)\d{4}-\d{2}-\d{2}", lambda m: m.group(1) + TODAY.isoformat(), s)
    open(sm, "w", encoding="utf-8").write(s)


def main():
    if os.environ.get("TOKENOMICS_OFFLINE") == "1":
        log("offline: keeping the committed page")
        return 0
    try:
        n = compute(*read_chain())
        if not (50e6 < n["frozen"] <= FROZEN_AT_FORK + 1 and 1e8 < n["mined"] < 7e8):
            raise ValueError(f"implausible numbers (frozen {n['frozen']}, mined {n['mined']})")
        build(n)
        log(f"built: frozen {n['frozen']:,.0f}, mined {n['mined']:,.0f}, circulating {n['circulating']:,.0f}")
    except Exception as e:  # noqa: BLE001
        log(f"kept the committed page ({e!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
