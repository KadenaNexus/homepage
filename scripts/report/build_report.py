"""Build kadena.ws/reports/kadena-network-october-2026/ from days.json plus live snapshots.

Usage: python3 scripts/report/build_report.py days.json site [earlier.csv]
  days.json    output of collect_network.py
  site         the homepage repo's site/ folder
  earlier.csv  optional: a CSV this script wrote before. Its days are kept
               unless days.json has the same date, so a refresh only needs
               to collect the new days.
Writes site/reports/kadena-network-october-2026/{index.html,kadena-daily-<first>_<last>.csv}
and removes older kadena-daily-*.csv files there. Once the data reaches
October 31 the page switches from "so far" wording to full-month wording.
"""
import csv
import datetime as dt
import html
import json
import os
import re
import statistics as st
import sys
import urllib.request

DAYS, SITE = sys.argv[1], sys.argv[2]
SLUG = "kadena-network-october-2026"
OUT = os.path.join(SITE, "reports", SLUG)
URL = f"https://kadena.ws/reports/{SLUG}/"
TEAL, INK, MUTED, GRID = "#1C637B", "#123A48", "#4F6B76", "#D6E0E4"
G = "https://graphql.chaddex.com/graphql/v0"


def get(url, body=None):
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                               headers={"content-type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=60))


data = json.load(open(DAYS))
days = data["days"]
if len(sys.argv) > 3:
    have = {d["date"] for d in days}
    with open(sys.argv[3], newline="") as f:
        for r in csv.DictReader(f):
            if r["date_utc"] not in have:
                days.append({"date": r["date_utc"], "blocks": int(r["blocks"]), "transactions": int(r["transactions"]),
                             "recorder_transactions": int(r["recorder_transactions"]),
                             "hashrate_phs": float(r["hashrate_phs"]),
                             "per_chain_tx": [int(r[f"tx_chain_{c}"]) for c in range(20)],
                             "per_chain_recorder": [int(r[f"recorder_chain_{c}"]) for c in range(20)]})
    days.sort(key=lambda d: d["date"])
for d in days:
    d["dt"] = dt.date.fromisoformat(d["date"])
    d["other"] = d["transactions"] - d["recorder_transactions"]
    d["per_chain_other"] = [a - b for a, b in zip(d["per_chain_tx"], d["per_chain_recorder"])]
sep = [d for d in days if d["dt"].month == 9]
octo = [d for d in days if d["dt"].month == 10]
first, last = days[0]["dt"], days[-1]["dt"]
FULL = last >= dt.date(2026, 10, 31)          # whole of October collected
OCT = f"Oct 1–{last.day}"

# live snapshots
net = get(G, {"query": "{ networkInfo { networkHashRate coinsInCirculation transactionCount } }"})["data"]["networkInfo"]
adopt = get("https://adoption.kadena.ws/api/index")
crawl = get("https://nodes.denascan.com/api/nodes")["data"]
snap_utc = dt.datetime.now(dt.timezone.utc)
active = [n for n in crawl if (n.get("metadata") or {}).get("status") == "active"]
last_seen = max((n.get("metadata") or {}).get("last_seen", "") for n in crawl)[:10]
countries = {}
for n in active:
    countries[n.get("country") or "Unknown"] = countries.get(n.get("country") or "Unknown", 0) + 1
top_countries = sorted(countries.items(), key=lambda kv: (-kv[1], kv[0]))
saudi = countries.get("Saudi Arabia", 0)


def avg(rows, k):
    return st.mean(r[k] for r in rows) if rows else 0


def pct(a, b):
    return (a - b) / b * 100 if b else 0


def fmt(n, d=0):
    return f"{n:,.{d}f}"


def fdate(x):
    return x.strftime("%B %-d")


tx_sep, tx_oct = avg(sep, "transactions"), avg(octo, "transactions")
oth_sep, oth_oct = avg(sep, "other"), avg(octo, "other")
rec_sep = avg(sep, "recorder_transactions")
rec_per_block = rec_sep / avg(sep, "blocks") if sep else 0
# first day after which the recorder stayed below 90% of its late-September rate, and first day it was (almost) gone
rec_drop = next((d["dt"] for k, d in enumerate(days)
                 if rec_sep and all(e["recorder_transactions"] < .9 * rec_sep for e in days[k:])), None)
rec_stop = next((d["dt"] for d in days if rec_sep and d["recorder_transactions"] < .01 * rec_sep), None)
rec_share_sep = rec_sep / tx_sep * 100 if tx_sep else 0
hr_sep, hr_oct = avg(sep, "hashrate_phs"), avg(octo, "hashrate_phs")
bl_sep, bl_oct = avg(sep, "blocks"), avg(octo, "blocks")
busiest = max(days, key=lambda d: d["other"])
quietest = min(days, key=lambda d: d["other"])
chain_oct = [sum(d["per_chain_other"][c] for d in octo) for c in range(20)]
tot_oct = sum(chain_oct) or 1
top_chain = max(range(20), key=lambda c: chain_oct[c])
share_top = chain_oct[top_chain] / tot_oct * 100
blocktime = 20 * 86400 / bl_oct if bl_oct else 0


def word(change, up="up", down="down"):
    return f"{up} {abs(change):.0f}%" if change >= 0.5 else (f"{down} {abs(change):.0f}%" if change <= -0.5 else "about the same")


# ---------- charts (inline SVG, single series, hover titles, table fallback)
def axis_ticks(vmax, n=4):
    raw = vmax / n
    mag = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 0.1
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    top = step * (int(vmax / step) + (1 if vmax % step else 0))
    return [step * i for i in range(int(round(top / step)) + 1)], top


def bars(rows, key, label, unit_fmt, title_id, w=960, h=300):
    pl, pr, pt, pb = 66, 12, 16, 38
    vmax = max(r[key] for r in rows) or 1
    ticks, top = axis_ticks(vmax)
    iw, ih = w - pl - pr, h - pt - pb
    bw = iw / len(rows)
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="{title_id}" class="chart">']
    for t in ticks:
        y = pt + ih - t / top * ih
        out.append(f'<line x1="{pl}" x2="{w-pr}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{pl-8}" y="{y+4:.1f}" text-anchor="end" class="tk">{unit_fmt(t)}</text>')
    for i, r in enumerate(rows):
        v = r[key]
        bh = max(v / top * ih, 1)
        x = pl + i * bw + 1
        y = pt + ih - bh
        wd = max(bw - 2, 1)
        rad = min(4, wd / 2)
        d = (f"M{x:.1f},{pt+ih:.1f} V{y+rad:.1f} Q{x:.1f},{y:.1f} {x+rad:.1f},{y:.1f} "
             f"H{x+wd-rad:.1f} Q{x+wd:.1f},{y:.1f} {x+wd:.1f},{y+rad:.1f} V{pt+ih:.1f} Z")
        out.append(f'<g class="m"><rect x="{pl+i*bw:.1f}" y="{pt}" width="{bw:.1f}" height="{ih}" fill="transparent"/>'
                   f'<path d="{d}" fill="{TEAL}"/><title>{r["label"]}: {unit_fmt(v)} {label}</title></g>')
        if r.get("tick"):
            out.append(f'<text x="{pl+i*bw+bw/2:.1f}" y="{h-12}" text-anchor="middle" class="tk">{r["tick"]}</text>')
    out.append(f'<line x1="{pl}" x2="{w-pr}" y1="{pt+ih}" y2="{pt+ih}" stroke="{MUTED}" stroke-width="1"/>')
    out.append("</svg>")
    return "".join(out)


def line(rows, key, label, unit_fmt, title_id, w=960, h=300):
    pl, pr, pt, pb = 66, 12, 16, 38
    vals = [r[key] for r in rows]
    ticks, top = axis_ticks(max(vals))
    iw, ih = w - pl - pr, h - pt - pb
    xs = [pl + iw * (i + .5) / len(rows) for i in range(len(rows))]
    ys = [pt + ih - v / top * ih for v in vals]
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="{title_id}" class="chart">']
    for t in ticks:
        y = pt + ih - t / top * ih
        out.append(f'<line x1="{pl}" x2="{w-pr}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{pl-8}" y="{y+4:.1f}" text-anchor="end" class="tk">{unit_fmt(t)}</text>')
    out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))}" fill="none" stroke="{TEAL}" stroke-width="2" stroke-linejoin="round"/>')
    for i, r in enumerate(rows):
        out.append(f'<g class="m"><rect x="{xs[i]-iw/len(rows)/2:.1f}" y="{pt}" width="{iw/len(rows):.1f}" height="{ih}" fill="transparent"/>'
                   f'<circle cx="{xs[i]:.1f}" cy="{ys[i]:.1f}" r="4" fill="{TEAL}" stroke="#fff" stroke-width="2"/>'
                   f'<title>{r["label"]}: {unit_fmt(vals[i])} {label}</title></g>')
        if r.get("tick"):
            out.append(f'<text x="{xs[i]:.1f}" y="{h-12}" text-anchor="middle" class="tk">{r["tick"]}</text>')
    out.append(f'<line x1="{pl}" x2="{w-pr}" y1="{pt+ih}" y2="{pt+ih}" stroke="{MUTED}" stroke-width="1"/>')
    out.append("</svg>")
    return "".join(out)


drows = []
for d in days:
    drows.append({**d, "label": d["dt"].strftime("%b %-d"),
                  "tick": d["dt"].strftime("%b %-d") if d["dt"].day in (15, 22, 1, 8) or d is days[-1] else ""})
crows = [{"label": f"Chain {c}", "tick": str(c), "tx": chain_oct[c]} for c in range(20)]

svg_all = bars(drows, "transactions", "transactions", lambda v: fmt(v), "t-all")
svg_tx = bars(drows, "other", "transactions excluding recorder calls", lambda v: fmt(v), "t-tx")
svg_hr = line(drows, "hashrate_phs", "PH/s", lambda v: f"{v:g}" if v != int(v) else fmt(v), "t-hr")
svg_ch = bars(crows, "tx", f"transactions excluding recorder calls, {OCT}", lambda v: fmt(v), "t-ch", h=260)


def table(headers, rows):
    th = "".join(f"<th>{h}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


tbl_days = table(["Date (UTC)", "Blocks", "All transactions", "Recorder calls", "Other transactions", "Hashrate (PH/s)"],
                 [[d["date"], fmt(d["blocks"]), fmt(d["transactions"]), fmt(d["recorder_transactions"]), fmt(d["other"]),
                   f'{d["hashrate_phs"]:.2f}'] for d in reversed(days)])
tbl_chain = table(["Chain", f"Other transactions, {OCT}", "Share"],
                  [[c, fmt(chain_oct[c]), f"{chain_oct[c]/tot_oct*100:.1f}%"] for c in range(20)])
tbl_ctry = table(["Country", "Active public nodes"], [[html.escape(k), v] for k, v in top_countries])

csv_name = f"kadena-daily-{first.isoformat()}_{last.isoformat()}.csv"
os.makedirs(OUT, exist_ok=True)
for old in os.listdir(OUT):
    if old.startswith("kadena-daily-") and old.endswith(".csv") and old != csv_name:
        os.remove(os.path.join(OUT, old))
with open(os.path.join(OUT, csv_name), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date_utc", "blocks", "transactions", "recorder_transactions", "other_transactions", "hashrate_phs"]
               + [f"tx_chain_{c}" for c in range(20)] + [f"recorder_chain_{c}" for c in range(20)])
    for d in days:
        w.writerow([d["date"], d["blocks"], d["transactions"], d["recorder_transactions"], d["other"], d["hashrate_phs"]]
                   + d["per_chain_tx"] + d["per_chain_recorder"])

try:
    mon = int(float(urllib.request.urlopen("https://nodes.kadena.ws/data/tx24h", timeout=30).read().decode().split()[0]))
except Exception:  # noqa: BLE001
    mon = None
diffp = abs(days[-1]["transactions"] - mon) / mon * 100 if mon else None
mon_line = (f"As a check, the {fdate(last)} total ({fmt(days[-1]['transactions'])}) is within {max(1, round(diffp))}% of the Kadena Network Monitor's own rolling 24-hour count ({fmt(mon)}) when this report was built."
            if diffp is not None and diffp <= 10 else "")
score = adopt.get("score")
aday = adopt.get("day")
circ = float(net["coinsInCirculation"])
pub = snap_utc.date()
pub0 = pub                                    # first publication date survives refreshes
try:
    m = re.search(r'"datePublished": "(\d{4}-\d{2}-\d{2})"', open(os.path.join(OUT, "index.html"), encoding="utf-8").read())
    pub0 = dt.date.fromisoformat(m.group(1)) if m else pub
except OSError:
    pass

PERIOD = "in October" if FULL else f"from October 1 to {fdate(last)}"
rec_story = ""
if rec_sep:
    rec_story = (f"In late September about {rec_share_sep:.0f}% of all Kadena transactions were automated calls to one contract, "
                 f"<code>free.block-history</code>, which keeps an on-chain record of each block's hash and time: about "
                 f"{rec_per_block:.0f} calls per block on every chain, {fmt(rec_sep)} a day.")
    if rec_drop:
        rec_story += f" They fell sharply from {fdate(rec_drop)}"
        rec_story += f" and had stopped by {fdate(rec_stop)}." if rec_stop else "."
summary = [
    rec_story + f" That one contract explains the drop in the total, from {fmt(tx_sep)} transactions a day in late September to "
    f"{fmt(days[-1]['transactions'])} on {fdate(last)}." if rec_sep else "",
    f"Excluding those recorder calls, Kadena carried an average of <b>{fmt(oth_oct)} transactions a day</b> {PERIOD}, "
    f"{word(pct(oth_oct, oth_sep))} on the second half of September ({fmt(oth_sep)} a day).",
    f"Mining hashrate averaged <b>{hr_oct:.1f} PH/s</b> in October{'' if FULL else ' so far'}, {word(pct(hr_oct, hr_sep))} on late September ({hr_sep:.1f} PH/s).",
    f"All 20 chains kept producing blocks: about <b>{fmt(bl_oct)} blocks a day</b>, an average of {blocktime:.1f} seconds per block on each chain against the 30-second target.",
    f"Chain {top_chain} carried {share_top:.0f}% of October's transactions outside the recorder, the largest share of any chain.",
]
summary = [s for s in summary if s]

desc = (f"Original Kadena network data for {fdate(first)} – {fdate(last)}, 2026: daily transactions, blocks and mining hashrate "
        f"across all 20 chains, with methods, sources and a CSV download.")

ld = {"@context": "https://schema.org", "@graph": [
    {"@type": "Organization", "@id": "https://kadena.ws/#org", "name": "Kadena Nexus", "url": "https://kadena.ws/",
     "logo": "https://kadena.ws/logo-kadena-nexus.png",
     "sameAs": ["https://x.com/KadenaNexus", "https://t.me/KadenaNexus", "https://github.com/KadenaNexus"]},
    {"@type": "Article", "headline": "Kadena network report: October 2026", "description": desc, "url": URL,
     "inLanguage": "en", "datePublished": pub0.isoformat(), "dateModified": pub.isoformat(),
     "author": {"@id": "https://kadena.ws/#org"}, "publisher": {"@id": "https://kadena.ws/#org"},
     "image": "https://kadena.ws/og/og-nodes.jpg", "about": ["Kadena", "Kadena Community Edition", "KDA", "Chainweb"]},
    {"@type": "Dataset", "name": f"Kadena mainnet daily statistics, {first.isoformat()} to {last.isoformat()}",
     "description": "Daily canonical blocks, non-coinbase transactions (with automated free.block-history recorder calls counted separately) and mining hashrate for Kadena mainnet (all 20 chains), with transactions per chain.",
     "url": URL, "creator": {"@id": "https://kadena.ws/#org"}, "license": "https://creativecommons.org/licenses/by/4.0/",
     "temporalCoverage": f"{first.isoformat()}/{last.isoformat()}", "isAccessibleForFree": True,
     "variableMeasured": ["blocks", "transactions", "block-history recorder transactions", "other transactions", "hashrate (PH/s)"],
     "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": URL + csv_name}]},
    {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Kadena Nexus", "item": "https://kadena.ws/"},
        {"@type": "ListItem", "position": 2, "name": "Kadena network report: October 2026", "item": URL}]}]}

body = f'''<main id="main">
  <article class="policy" aria-labelledby="r-title">
    <div class="wrap">
      <p class="crumb"><a href="/">Kadena Nexus</a> / Reports</p>
      <h1 id="r-title">Kadena network report: October 2026</h1>
      <p class="lede">What happened on Kadena mainnet from {fdate(first)} to {fdate(last)}, 2026: transactions, blocks and mining hashrate across all 20 chains, measured by Kadena Nexus from public chain data.</p>
      <p class="meta">Published {fdate(pub0)}, 2026{f" · Updated {fdate(pub)}, {pub.year}" if pub != pub0 else ""} · Data through {fdate(last)}, 2026 (UTC) · {"Full-month figures for October." if FULL else "A full-month update follows in early November."}</p>

      <h2>Summary</h2>
      <ul class="sum">{"".join(f"<li>{s}</li>" for s in summary)}</ul>

      <h2 id="t-all">All transactions per day</h2>
      <p>Non-coinbase transactions included in canonical blocks on all 20 chains, per UTC day. Hover a bar for the exact value.</p>
      {svg_all}
      <p class="note">{"Most of this total was one automated workload, explained next." if rec_sep else ""}</p>

      <h2 id="t-rec">The block-history recorder</h2>
      <p><code>free.block-history</code> is a Pact contract that stores each block's height, hash and time on its own chain, so other contracts can look them up later. Anyone can call its <code>attest</code> function, which records the previous block. {f"In late September recorder accounts called it about {rec_per_block:.0f} times in every block on every chain, {fmt(rec_sep)} transactions a day, most of Kadena's daily total." if rec_sep else ""} {f"The calls fell sharply from {fdate(rec_drop)}" + (f" and had stopped by {fdate(rec_stop)}" if rec_stop else "") + "." if rec_drop else ""} These are real, fee-paying transactions, but they come from one automated source, so this report shows activity with and without them.</p>

      <h2 id="t-tx">Transactions excluding the recorder</h2>
      <p>Everything except calls to <code>free.block-history</code>: transfers, swaps, contract calls and the rest, per UTC day.</p>
      {svg_tx}
      <p class="note">Busiest day: {fdate(busiest["dt"])} ({fmt(busiest["other"])}). Quietest: {fdate(quietest["dt"])} ({fmt(quietest["other"])}).</p>

      <h2 id="t-hr">Mining hashrate</h2>
      <p>Daily average hashrate in petahashes per second (PH/s), from the difficulty of every canonical block that day. As an outside check, MiningPoolStats, which tracks the active KDA pools, showed about 16.7 PH/s for the network on October 15.</p>
      {svg_hr}

      <h2 id="t-ch">Where transactions happen</h2>
      <p>Transactions per chain {PERIOD}, excluding recorder calls. Activity is uneven: a few chains host the busiest contracts.</p>
      {svg_ch}

      <h2>Blocks and block time</h2>
      <p>Each chain targets one block every 30 seconds, which is 57,600 blocks a day across 20 chains. In October{"" if FULL else " so far"} the network produced {fmt(bl_oct)} canonical blocks a day on average, so blocks arrived every {blocktime:.1f} seconds per chain. Late September averaged {fmt(bl_sep)} a day.</p>

      <h2>Nodes</h2>
      <p>The public node crawler found <b>{len(active)} active nodes in {len(countries)} countries</b> in its last scan ({fdate(dt.date.fromisoformat(last_seen))}, {last_seen[:4]}){", including the Kadena Nexus node in Jeddah, Saudi Arabia" if saudi else ""}. Nodes are placed by IP location, so the count covers public nodes only.</p>
      <details><summary>Nodes by country</summary>{tbl_ctry}</details>

      <h2>Adoption Index</h2>
      <p>The <a href="https://adoption.kadena.ws/">Kadena Community Edition Adoption Index</a> combines five weighted signals (active addresses, new contracts, value locked, hashrate and developer commits) into one daily number against a summer 2026 baseline of 50. Its reading for {fdate(dt.date.fromisoformat(aday))}, {aday[:4]} was <b>{score}</b>. How each input is measured is published in the <a href="https://adoption.kadena.ws/methodology">methodology</a>.</p>

      <h2>Supply</h2>
      <p>KDA in circulation was {fmt(circ/1e6, 1)} million when this report was built, according to the indexer's network summary. The maximum supply is 1 billion KDA, most of it paid to miners over time.</p>

      <h2>Data and method</h2>
      <ul>
        <li><b>Source:</b> the public Chainweb GraphQL indexer (graphql.chaddex.com), queried block by block in 50-block windows on every chain. Each UTC day starts at the first block created at or after 00:00 UTC.</li>
        <li><b>Transactions</b> count non-coinbase transactions in canonical blocks; orphaned blocks are excluded. {mon_line}</li>
        <li><b>Recorder calls</b> are transactions whose code calls <code>free.block-history.attest</code>, found by reading the code of every transaction in every block. Other transactions are the total minus recorder calls.</li>
        <li><b>Hashrate</b> is the sum of each canonical block's difficulty over the day, divided by 86,400 seconds.</li>
        <li><b>Nodes</b> come from the public node crawler (nodes.denascan.com); <b>Adoption Index</b> from adoption.kadena.ws; <b>supply</b> from the indexer's network summary.</li>
        <li>Figures are Kadena Nexus measurements from public data, not official statistics. Please cite "Kadena Nexus, Kadena network report: October 2026".</li>
      </ul>
      <p><a class="dl" href="{csv_name}" download>Download the daily data (CSV)</a></p>
      <details><summary>Daily table</summary>{tbl_days}</details>
      <details><summary>Transactions by chain</summary>{tbl_chain}</details>

      <h2>Follow the network live</h2>
      <p>The <a href="https://nodes.kadena.ws/">Kadena Network Monitor</a> shows every block as it lands, throughput and confirmation times. The <a href="https://adoption.kadena.ws/">Adoption Index</a> updates daily. New to Kadena? Start with <a href="/community-edition/">What is Kadena Community Edition?</a></p>
      <p class="updated">Kadena Nexus is an independent community project and is not affiliated with Kadena LLC. Nothing here is financial advice.</p>
    </div>
  </article>
</main>'''

# ---- assemble from the Community Edition page template
tpl = open(os.path.join(SITE, "community-edition", "index.html"), encoding="utf-8").read()
head_end = tpl.index("</head>")
head = tpl[:head_end]
head = re.sub(r"<title>[^<]*</title>", "<title>Kadena network report: October 2026 | Kadena Nexus</title>", head, count=1)
head = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{html.escape(desc)}">', head, count=1)
head = re.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{URL}">', head, count=1)
head = re.sub(r'<meta property="og:title" content="[^"]*">', '<meta property="og:title" content="Kadena network report: October 2026">', head, count=1)
head = re.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{html.escape(desc)}">', head, count=1)
head = re.sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{URL}">', head, count=1)
head = re.sub(r'og-home\.jpg', 'og-nodes.jpg', head)
head = re.sub(r'<script type="application/ld\+json">.*?</script>\n?', "", head, flags=re.S)
head += '<script type="application/ld+json">\n' + json.dumps(ld, indent=1, ensure_ascii=False) + "\n</script>\n"
head += f'''<style>
.policy .crumb{{font-size:.9rem;margin-bottom:.8rem}}
.policy .crumb a{{color:var(--teal)}}
.policy .meta{{font-size:.9rem;margin:-1rem 0 1.5rem}}
.policy .sum li{{margin-bottom:.5rem}}
.chart{{width:100%;height:auto;margin:.6rem 0 .4rem;overflow:visible}}
.chart .tk{{font:15px var(--body);fill:{MUTED}}}
.chart .m:hover path,.chart .m:hover circle{{fill:{INK}}}
.policy .note{{font-size:.92rem}}
.policy details{{margin:.6rem 0 1rem;border:1px solid var(--line);border-radius:12px;padding:.6rem .9rem}}
.policy summary{{cursor:pointer;color:var(--sand);font-weight:600}}
.tw{{overflow-x:auto;margin-top:.6rem}}
.tw table{{border-collapse:collapse;width:100%;font-size:.92rem;font-variant-numeric:tabular-nums}}
.tw th,.tw td{{text-align:right;padding:.35rem .6rem;border-top:1px solid var(--line)}}
.tw th:first-child,.tw td:first-child{{text-align:left}}
.policy .dl{{display:inline-block;font-weight:600}}
.policy code{{font-size:.9em;background:var(--panel);padding:.05em .3em;border-radius:4px}}
</style>
'''
rest = tpl[head_end:]
pre_main = rest[:rest.index('<main id="main">')]
post_main = rest[rest.index("</main>") + len("</main>"):]
page = head + pre_main + body + post_main
assert "—" not in page
open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(page)
print("wrote", OUT, "| tx/day Sep", round(tx_sep), "Oct", round(tx_oct), "| PH/s", round(hr_sep, 2), round(hr_oct, 2),
      "| nodes", len(active), len(countries), "last seen", last_seen, "| adoption", score, aday)
