"""Build the monthly Kadena network report pages and the /reports/ index.

Used by scripts/report/update_reports.py, which runs in the daily site build.
It can also be run by hand:

  python3 scripts/report/build_report.py site/reports/data/kadena-daily.csv site 2026-10

Pages: site/reports/kadena-network-<month>-<year>/index.html plus that month's
CSV, and site/reports/index.html listing every month. Each month is compared
with the month before it (whatever days of it the data holds). Calls to the
automated free.block-history recorder are shown separately because, until
October 12, 2026, they were most of Kadena's transactions.

Every page carries <meta name="generator" content="... GENERATOR">. Bump
GENERATOR when the page template changes so already-published months are
rebuilt with the new template on the next run.
Python 3 standard library only.
"""
import calendar
import csv
import datetime as dt
import html
import json
import os
import re
import statistics as st
import sys
import urllib.request

GENERATOR = "kadena-nexus-network-report 5"
BASE = "https://kadena.ws/reports/"
TEAL, INK, MUTED, GRID = "#1C637B", "#123A48", "#4F6B76", "#D6E0E4"
G = "https://graphql.chaddex.com/graphql/v0"
FIELDS = (["date_utc", "blocks", "transactions", "recorder_transactions", "other_transactions", "hashrate_phs"]
          + [f"tx_chain_{c}" for c in range(20)] + [f"recorder_chain_{c}" for c in range(20)])
# Outside facts that belong to one month's page only.
MONTH_NOTES = {
    (2026, 10): {"hashrate": "As an outside check, MiningPoolStats, which tracks the active KDA pools, "
                             "showed about 16.7 PH/s for the network on October 15."},
}


# ---------------------------------------------------------------- data
def read_csv(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"date": r["date_utc"], "blocks": int(r["blocks"]), "transactions": int(r["transactions"]),
                         "recorder_transactions": int(r["recorder_transactions"]),
                         "hashrate_phs": float(r["hashrate_phs"]),
                         "per_chain_tx": [int(r[f"tx_chain_{c}"]) for c in range(20)],
                         "per_chain_recorder": [int(r[f"recorder_chain_{c}"]) for c in range(20)]})
    return rows


def write_csv(path, days):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for d in sorted(days, key=lambda d: d["date"]):
            w.writerow([d["date"], d["blocks"], d["transactions"], d["recorder_transactions"],
                        d["transactions"] - d["recorder_transactions"], d["hashrate_phs"]]
                       + d["per_chain_tx"] + d["per_chain_recorder"])


def prepare(days):
    out = []
    for d in sorted(days, key=lambda d: d["date"]):
        d = dict(d)
        d["dt"] = dt.date.fromisoformat(d["date"])
        d["other"] = d["transactions"] - d["recorder_transactions"]
        d["per_chain_other"] = [a - b for a, b in zip(d["per_chain_tx"], d["per_chain_recorder"])]
        out.append(d)
    return out


def months_in(days):
    return sorted({(d["dt"].year, d["dt"].month) for d in days})


def slug(year, month):
    return f"kadena-network-{calendar.month_name[month].lower()}-{year}"


def title(year, month):
    return f"Kadena network report: {calendar.month_name[month]} {year}"


def month_csv_name(year, month):
    return f"kadena-daily-{year}-{month:02d}.csv"


# ---------------------------------------------------------------- formatting
def avg(rows, k):
    return st.mean(r[k] for r in rows) if rows else 0


def pct(a, b):
    return (a - b) / b * 100 if b else 0


def fmt(n, d=0):
    return f"{n:,.{d}f}"


def fdate(x):
    return x.strftime("%B %-d")


def word(change, up="up", down="down"):
    return f"{up} {abs(change):.0f}%" if change >= 0.5 else (f"{down} {abs(change):.0f}%" if change <= -0.5 else "about the same")


def span_label(rows):
    """'September' for a whole month, 'September 15–30' for part of one."""
    a, b = rows[0]["dt"], rows[-1]["dt"]
    whole = a.day == 1 and b.day == calendar.monthrange(b.year, b.month)[1]
    return a.strftime("%B") if whole else f"{a:%B} {a.day}–{b.day}"


# ---------------------------------------------------------------- charts
def axis_ticks(vmax, n=4):
    vmax = vmax or 1
    raw = vmax / n
    mag = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 0.1
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    top = step * (int(vmax / step) + (1 if vmax % step else 0))
    return [step * i for i in range(int(round(top / step)) + 1)], top


def bars(rows, key, label, unit_fmt, title_id, w=960, h=300):
    pl, pr, pt, pb = 66, 12, 16, 38
    ticks, top = axis_ticks(max(r[key] for r in rows))
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


def table(headers, rows):
    th = "".join(f"<th>{h}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


# ---------------------------------------------------------------- live snapshot
def get(url, body=None):
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                               headers={"content-type": "application/json",
                                        "User-Agent": "KadenaNexus-report (+https://kadena.ws/reports/)"})
    return urllib.request.urlopen(r, timeout=60).read().decode()


def snapshot():
    """Nodes, Adoption Index, supply and the Network Monitor's 24h count. Each part is optional."""
    s = {"when": dt.datetime.now(dt.timezone.utc).date()}
    try:
        crawl = json.loads(get("https://nodes.denascan.com/api/nodes"))["data"]
        active = [n for n in crawl if (n.get("metadata") or {}).get("status") == "active"]
        countries = {}
        for n in active:
            k = n.get("country") or "Unknown"
            countries[k] = countries.get(k, 0) + 1
        s["nodes"] = {"active": len(active), "countries": sorted(countries.items(), key=lambda kv: (-kv[1], kv[0])),
                      "last_seen": max((n.get("metadata") or {}).get("last_seen", "") for n in crawl)[:10]}
    except Exception as e:  # noqa: BLE001
        print(f"report: nodes snapshot skipped ({e})", file=sys.stderr)
    try:
        a = json.loads(get("https://adoption.kadena.ws/api/index"))
        if a.get("state") == "ready":
            s["adoption"] = (a["score"], a["day"])
    except Exception as e:  # noqa: BLE001
        print(f"report: adoption snapshot skipped ({e})", file=sys.stderr)
    try:
        net = json.loads(get(G, {"query": "{ networkInfo { coinsInCirculation } }"}))["data"]["networkInfo"]
        s["supply"] = float(net["coinsInCirculation"])
    except Exception as e:  # noqa: BLE001
        print(f"report: supply snapshot skipped ({e})", file=sys.stderr)
    try:
        s["tx24h"] = int(float(get("https://nodes.kadena.ws/data/tx24h").split()[0]))
    except Exception as e:  # noqa: BLE001
        print(f"report: monitor snapshot skipped ({e})", file=sys.stderr)
    return s



# ---------------------------------------------------------------- update badge
def next_update(last):
    """The morning the weekly job will add new days: 8 days after the newest day,
    or the day after the month ends if that comes first."""
    month_end = dt.date(last.year, last.month, calendar.monthrange(last.year, last.month)[1])
    nxt = last + dt.timedelta(days=8)
    if last < month_end:
        nxt = min(nxt, month_end + dt.timedelta(days=1))
    return nxt


def badge(updated, last):
    """Top-right note: last update and when the next one is due. The day count is
    worked out in the reader's browser, so it stays right between weekly rebuilds."""
    nxt = next_update(last)
    return (f'<p class="upd" data-next="{nxt.isoformat()}"><span class="dot" aria-hidden="true"></span>'
            f'<span>Updated {updated:%b} {updated.day}, {updated.year} · '
            f'<span class="nx">Next update around {nxt:%b} {nxt.day}</span></span></p>')


BADGE_JS = """<script>
(function(){var p=document.querySelector('.upd[data-next]');if(!p)return;
var n=new Date(p.getAttribute('data-next')+'T03:30:00Z'),d=Math.ceil((n-new Date())/864e5),s=p.querySelector('.nx');
if(!s)return;s.textContent=d>1?'Next update in '+d+' days':d===1?'Next update tomorrow':'Next update due today';})();
</script>"""

# ---------------------------------------------------------------- page shell
def shell(site, page_title, desc, url, ld, extra_css, body):
    tpl = open(os.path.join(site, "community-edition", "index.html"), encoding="utf-8").read()
    head_end = tpl.index("</head>")
    head = tpl[:head_end]
    esc = html.escape
    head = re.sub(r"<title>[^<]*</title>", f"<title>{esc(page_title)} | Kadena Nexus</title>", head, count=1)
    head = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{esc(desc)}">', head, count=1)
    head = re.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{url}">', head, count=1)
    for prop, val in (("og:title", page_title), ("og:description", desc), ("og:url", url)):
        head = re.sub(rf'<meta property="{prop}" content="[^"]*">', f'<meta property="{prop}" content="{esc(val)}">', head, count=1)
    for name, val in (("twitter:title", page_title), ("twitter:description", desc)):
        head = re.sub(rf'<meta name="{name}" content="[^"]*">', f'<meta name="{name}" content="{esc(val)}">', head, count=1)
    head = re.sub(r"og-home\.jpg", "og-nodes.jpg", head)
    head = re.sub(r'<script type="application/ld\+json">.*?</script>\n?', "", head, flags=re.S)
    head += f'<meta name="generator" content="{GENERATOR}">\n'
    head += '<script type="application/ld+json">\n' + json.dumps(ld, indent=1, ensure_ascii=False) + "\n</script>\n"
    head += f'''<style>
.policy .wrap{{max-width:1040px}}
.policy .lede{{font-size:1.25rem}}
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
.policy .dl{{display:inline-block;font-weight:600;margin-right:1.2rem}}
.policy code{{font-size:.9em;background:var(--panel);padding:.05em .3em;border-radius:4px}}
.policy .topbar{{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.6rem 1rem;margin-bottom:.8rem}}
.policy .topbar .crumb{{margin:0}}
.policy .upd{{margin:0 0 0 auto;font-size:.82rem;line-height:1.3;color:var(--sand);font-weight:500;background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:.35rem .8rem;display:inline-flex;align-items:center;gap:.45rem}}
.policy .upd .nx{{white-space:nowrap}}
.policy .upd .dot{{width:.5rem;height:.5rem;border-radius:50%;background:var(--teal);flex:none}}
@media (max-width:620px){{.policy .upd{{margin-left:0}}}}
{extra_css}</style>
'''
    rest = tpl[head_end:]
    pre_main = rest[:rest.index('<main id="main">')]
    post_main = rest[rest.index("</main>") + len("</main>"):]
    page = head + pre_main + body + post_main
    if 'class="upd"' in body:
        page = page.replace("</body>", BADGE_JS + "\n</body>", 1)
    assert "—" not in page, "em-dash in report page"
    return page


ORG = {"@type": "Organization", "@id": "https://kadena.ws/#org", "name": "Kadena Nexus", "url": "https://kadena.ws/",
       "logo": "https://kadena.ws/logo-kadena-nexus.png",
       "sameAs": ["https://x.com/KadenaNexus", "https://t.me/KadenaNexus", "https://github.com/KadenaNexus"]}


# ---------------------------------------------------------------- one month
def build_month(all_days, year, month, site, snap, published=None):
    """Write one month's page and CSV. Returns a short summary dict for the index."""
    days = prepare(all_days)
    cur = [d for d in days if (d["dt"].year, d["dt"].month) == (year, month)]
    py, pm = (year, month - 1) if month > 1 else (year - 1, 12)
    prv = [d for d in days if (d["dt"].year, d["dt"].month) == (py, pm)]
    if not cur:
        raise ValueError(f"no data for {year}-{month:02d}")
    mname = calendar.month_name[month]
    first, last = cur[0]["dt"], cur[-1]["dt"]
    full = last.day == calendar.monthrange(year, month)[1]
    period = f"in {mname}" if full else f"from {mname} 1 to {fdate(last)}"
    so_far = "" if full else " so far"
    prev_lbl = span_label(prv) if prv else ""
    slg, ttl = slug(year, month), title(year, month)
    url = BASE + slg + "/"
    out = os.path.join(site, "reports", slg)
    note = MONTH_NOTES.get((year, month), {})
    pub = snap["when"]
    pub0 = published or pub

    oth_c, oth_p = avg(cur, "other"), avg(prv, "other")
    hr_c, hr_p = avg(cur, "hashrate_phs"), avg(prv, "hashrate_phs")
    bl_c, bl_p = avg(cur, "blocks"), avg(prv, "blocks")
    tot_p = avg(prv, "transactions")
    blocktime = 20 * 86400 / bl_c if bl_c else 0
    busiest = max(cur, key=lambda d: d["other"])
    quietest = min(cur, key=lambda d: d["other"])
    chain_c = [sum(d["per_chain_other"][c] for d in cur) for c in range(20)]
    tot_c = sum(chain_c) or 1
    top_chain = max(range(20), key=lambda c: chain_c[c])

    # The block-history recorder: shown only for months in which it ran.
    rec_in_month = sum(d["recorder_transactions"] for d in cur) > 0
    rec_story = rec_section = ""
    if rec_in_month:
        base = prv if any(d["recorder_transactions"] for d in prv) else [d for d in cur if d["recorder_transactions"]]
        rec_base = avg(base, "recorder_transactions")
        base_lbl = span_label(base)
        share = rec_base / avg(base, "transactions") * 100 if base else 0
        per_block = rec_base / avg(base, "blocks") if base else 0
        k0 = days.index(base[0])
        rec_drop = next((d["dt"] for k, d in enumerate(days) if k >= k0
                         and all(e["recorder_transactions"] < .9 * rec_base for e in days[k:])), None)
        rec_last = max(d["dt"] for d in days if d["recorder_transactions"] > 0)
        ended = rec_last < days[-1]["dt"]
        how_ended = ""
        if ended:
            how_ended = (f"Its developer then wound the service down: calls dropped from {fdate(rec_drop)} and the last ones were on {fdate(rec_last)}."
                         if rec_drop and rec_drop < rec_last else f"Its developer then ended the service; the last calls were on {fdate(rec_last)}.")
        rec_story = (f"Over {base_lbl} about {share:.0f}% of all Kadena transactions were automated calls to one contract, "
                     f"<code>free.block-history</code>, a service that recorded each block's hash and time on-chain: about "
                     f"{per_block:.0f} calls per block on every chain, {fmt(rec_base)} a day. {how_ended} "
                     f"That one contract explains the drop in the total, from {fmt(avg(base, 'transactions'))} transactions a day to "
                     f"{fmt(cur[-1]['transactions'])} on {fdate(last)}.")
        rec_section = f'''
      <h2 id="t-rec">The block-history recorder</h2>
      <p><code>free.block-history</code> is a Pact contract that stores each block's height, hash and time on its own chain, so other contracts can look them up later. A recorder service called its <code>attest</code> function to record the previous block. Over {base_lbl} the recorder accounts called it about {per_block:.0f} times in every block on every chain, {fmt(rec_base)} transactions a day, most of Kadena's daily total. {how_ended + " The contract stays on chain with the blocks it recorded, but no new calls are being made." if ended else ""} These were real, fee-paying transactions, but they came from one automated service, so this report shows activity with and without them.</p>
'''

    def vs(a, b, unit="a day", f=fmt):
        if not prv:
            return ""
        w = word(pct(a, b))
        return f", {w} {'as' if w == 'about the same' else 'from'} {prev_lbl} ({f(b)} {unit})"
    summary = [s for s in [
        rec_story,
        f"{'Excluding those recorder calls, Kadena' if rec_in_month else 'Kadena'} carried an average of <b>{fmt(oth_c)} transactions a day</b> {period}{vs(oth_c, oth_p)}.",
        f"Mining hashrate averaged <b>{hr_c:.1f} PH/s</b> {period}{vs(hr_c, hr_p, 'PH/s', lambda v: f'{v:.1f}')}.",
        f"All 20 chains kept producing blocks: about <b>{fmt(bl_c)} blocks a day</b>, an average of {blocktime:.1f} seconds per block on each chain against the 30-second target.",
        f"Chain {top_chain} carried {chain_c[top_chain]/tot_c*100:.0f}% of {mname}'s transactions{' outside the recorder' if rec_in_month else ''}, the largest share of any chain.",
    ] if s]

    # charts: the previous month's days (for context) and this month's
    ctx = prv + cur
    drows = [{**d, "label": d["dt"].strftime("%b %-d"),
              "tick": d["dt"].strftime("%b %-d") if d["dt"].day in (1, 8, 15, 22) or d is ctx[-1] else ""} for d in ctx]
    crows = [{"label": f"Chain {c}", "tick": str(c), "tx": chain_c[c]} for c in range(20)]
    rng = f"{mname[:3]} 1–{last.day}"
    tx_name = "transactions excluding recorder calls" if rec_in_month else "transactions"
    if rec_in_month:
        tx_block = f'''
      <h2 id="t-all">All transactions per day</h2>
      <p>Non-coinbase transactions included in canonical blocks on all 20 chains, per UTC day. Hover a bar for the exact value.</p>
      {bars(drows, "transactions", "transactions", fmt, "t-all")}
      <p class="note">Most of this total was one automated service, explained next.</p>
{rec_section}
      <h2 id="t-tx">Transactions excluding the recorder</h2>
      <p>Everything except calls to <code>free.block-history</code>: transfers, swaps, contract calls and the rest, per UTC day.</p>'''
    else:
        tx_block = '''
      <h2 id="t-tx">Transactions per day</h2>
      <p>Non-coinbase transactions included in canonical blocks on all 20 chains, per UTC day. Hover a bar for the exact value.</p>'''
    tx_block += f'''
      {bars(drows, "other", tx_name, fmt, "t-tx")}
      <p class="note">Busiest day in {mname}: {fdate(busiest["dt"])} ({fmt(busiest["other"])}). Quietest: {fdate(quietest["dt"])} ({fmt(quietest["other"])}).</p>
'''

    # snapshot sections
    nodes_html = adopt_html = supply_html = ""
    if "nodes" in snap:
        n = snap["nodes"]
        saudi = dict(n["countries"]).get("Saudi Arabia", 0)
        seen = dt.date.fromisoformat(n["last_seen"]) if n["last_seen"] else None
        nodes_html = f'''
      <h2>Nodes</h2>
      <p>The public node crawler found <b>{n["active"]} active nodes in {len(n["countries"])} countries</b> in its last scan{f" ({fdate(seen)}, {seen.year})" if seen else ""}{", including the Kadena Nexus node in Jeddah, Saudi Arabia" if saudi else ""}. Nodes are placed by IP location, so the count covers public nodes only.</p>
      <details><summary>Nodes by country</summary>{table(["Country", "Active public nodes"], [[html.escape(k), v] for k, v in n["countries"]])}</details>
'''
    if "adoption" in snap:
        score, aday = snap["adoption"]
        ad = dt.date.fromisoformat(aday)
        adopt_html = f'''
      <h2>Adoption Index</h2>
      <p>The <a href="https://adoption.kadena.ws/">Kadena Community Edition Adoption Index</a> combines five weighted signals (active addresses, new contracts, value locked, hashrate and developer commits) into one daily number against a summer 2026 baseline of 50. Its reading for {fdate(ad)}, {ad.year} was <b>{score}</b>. How each input is measured is published in the <a href="https://adoption.kadena.ws/methodology">methodology</a>.</p>
'''
    if "supply" in snap:
        supply_html = f'''
      <h2>Supply</h2>
      <p>KDA in circulation was {fmt(snap["supply"]/1e6, 1)} million when this report was last updated, according to the indexer's network summary. The maximum supply is 1 billion KDA, most of it paid to miners over time.</p>
'''
    mon_line = ""
    if snap.get("tx24h") and (pub - last).days <= 2:
        diffp = abs(cur[-1]["transactions"] - snap["tx24h"]) / snap["tx24h"] * 100
        if diffp <= 10:
            mon_line = (f"As a check, the {fdate(last)} total ({fmt(cur[-1]['transactions'])}) is within {max(1, round(diffp))}% "
                        f"of the Kadena Network Monitor's own rolling 24-hour count ({fmt(snap['tx24h'])}) at the last update.")

    csv_name = month_csv_name(year, month)
    os.makedirs(out, exist_ok=True)
    for old in os.listdir(out):
        if old.startswith("kadena-daily-") and old.endswith(".csv") and old != csv_name:
            os.remove(os.path.join(out, old))
    write_csv(os.path.join(out, csv_name), cur)

    desc = (f"Original Kadena network data for {mname} {year}{'' if full else f' (through {fdate(last)})'}: daily transactions, "
            f"blocks and mining hashrate across all 20 chains, with methods, sources and a CSV download. Updated weekly.")
    ld = {"@context": "https://schema.org", "@graph": [
        ORG,
        {"@type": "Article", "headline": ttl, "description": desc, "url": url, "inLanguage": "en",
         "datePublished": pub0.isoformat(), "dateModified": pub.isoformat(),
         "author": {"@id": "https://kadena.ws/#org"}, "publisher": {"@id": "https://kadena.ws/#org"},
         "image": "https://kadena.ws/og/og-nodes.jpg", "about": ["Kadena", "Kadena Community Edition", "KDA", "Chainweb"]},
        {"@type": "Dataset", "name": f"Kadena mainnet daily statistics, {mname} {year}",
         "description": "Daily canonical blocks, non-coinbase transactions (with automated free.block-history recorder calls counted separately) and mining hashrate for Kadena mainnet (all 20 chains), with transactions per chain.",
         "url": url, "creator": {"@id": "https://kadena.ws/#org"}, "license": "https://creativecommons.org/licenses/by/4.0/",
         "temporalCoverage": f"{first.isoformat()}/{last.isoformat()}", "isAccessibleForFree": True,
         "variableMeasured": ["blocks", "transactions", "block-history recorder transactions", "other transactions", "hashrate (PH/s)"],
         "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": url + csv_name},
                          {"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": BASE + "data/kadena-daily.csv"}]},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Kadena Nexus", "item": "https://kadena.ws/"},
            {"@type": "ListItem", "position": 2, "name": "Kadena network reports", "item": BASE},
            {"@type": "ListItem", "position": 3, "name": ttl, "item": url}]}]}

    status = "Full-month figures." if full else "Updated every week until the month is complete."
    updated = f" · Updated {fdate(pub)}, {pub.year}" if pub != pub0 else ""
    body = f'''<main id="main">
  <article class="policy" aria-labelledby="r-title">
    <div class="wrap">
      <div class="topbar"><p class="crumb"><a href="/">Kadena Nexus</a> / <a href="/reports/">Reports</a></p>{badge(pub, cur[-1]["dt"]) if not full else ""}</div>
      <h1 id="r-title">{ttl}</h1>
      <p class="lede">What happened on Kadena mainnet in {mname} {year}: transactions, blocks and mining hashrate across all 20 chains, measured by Kadena Nexus from public chain data{f", compared with {prev_lbl}" if prv else ""}.</p>
      <p class="meta">Published {fdate(pub0)}, {pub0.year}{updated} · Data through {fdate(last)}, {last.year} (UTC) · {status}</p>

      <h2>Summary</h2>
      <ul class="sum">{"".join(f"<li>{s}</li>" for s in summary)}</ul>
{tx_block}
      <h2 id="t-hr">Mining hashrate</h2>
      <p>Daily average hashrate in petahashes per second (PH/s), from the difficulty of every canonical block that day. {note.get("hashrate", "")}</p>
      {line(drows, "hashrate_phs", "PH/s", lambda v: f"{v:g}" if v != int(v) else fmt(v), "t-hr")}

      <h2 id="t-ch">Where transactions happen</h2>
      <p>Transactions per chain {period}{", excluding recorder calls" if rec_in_month else ""}. Activity is uneven: a few chains host the busiest contracts.</p>
      {bars(crows, "tx", f"{tx_name}, {rng}", fmt, "t-ch", h=260)}

      <h2>Blocks and block time</h2>
      <p>Each chain targets one block every 30 seconds, which is 57,600 blocks a day across 20 chains. In {mname}{so_far} the network produced {fmt(bl_c)} canonical blocks a day on average, so blocks arrived every {blocktime:.1f} seconds per chain.{f" {prev_lbl} averaged {fmt(bl_p)} a day." if prv else ""}</p>
{nodes_html}{adopt_html}{supply_html}
      <h2>Data and method</h2>
      <ul>
        <li><b>Source:</b> the public Chainweb GraphQL indexer (graphql.chaddex.com), queried block by block in 50-block windows on every chain. Each UTC day starts at the first block created at or after 00:00 UTC. New days are added every week.</li>
        <li><b>Transactions</b> count non-coinbase transactions in canonical blocks; orphaned blocks are excluded. {mon_line}</li>
        <li><b>Recorder calls</b> are transactions whose code calls <code>free.block-history.attest</code>, found by reading the code of every transaction in every block. Other transactions are the total minus recorder calls.</li>
        <li><b>Hashrate</b> is the sum of each canonical block's difficulty over the day, divided by 86,400 seconds.</li>
        <li><b>Nodes</b> come from the public node crawler (nodes.denascan.com); <b>Adoption Index</b> from adoption.kadena.ws; <b>supply</b> from the indexer's network summary. These are read when the page is updated.</li>
        <li>Figures are Kadena Nexus measurements from public data, not official statistics. Please cite "Kadena Nexus, {ttl}".</li>
      </ul>
      <p><a class="dl" href="{csv_name}" download>Download {mname}'s daily data (CSV)</a><a class="dl" href="/reports/data/kadena-daily.csv" download>All days since September 15, 2026 (CSV)</a></p>
      <details><summary>Daily table</summary>{table(["Date (UTC)", "Blocks", "All transactions", "Recorder calls", "Other transactions", "Hashrate (PH/s)"], [[d["date"], fmt(d["blocks"]), fmt(d["transactions"]), fmt(d["recorder_transactions"]), fmt(d["other"]), f'{d["hashrate_phs"]:.2f}'] for d in reversed(ctx)])}</details>
      <details><summary>Transactions by chain</summary>{table(["Chain", f"{'Other t' if rec_in_month else 'T'}ransactions, {rng}", "Share"], [[c, fmt(chain_c[c]), f"{chain_c[c]/tot_c*100:.1f}%"] for c in range(20)])}</details>

      <h2>Follow the network live</h2>
      <p>The <a href="https://nodes.kadena.ws/">Kadena Network Monitor</a> shows every block as it lands, throughput and confirmation times. The <a href="https://adoption.kadena.ws/">Adoption Index</a> updates daily. Other months: <a href="/reports/">all Kadena network reports</a>. Supply and the frozen platform share: <a href="/tokenomics/">KDA tokenomics</a>. New to Kadena? Start with <a href="/community-edition/">What is Kadena Community Edition?</a></p>
      <p class="updated">Kadena Nexus is an independent community project and is not affiliated with Kadena LLC. Nothing here is financial advice.</p>
    </div>
  </article>
</main>'''
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(shell(site, ttl, desc, url, ld, "", body))
    return {"year": year, "month": month, "slug": slg, "title": ttl, "full": full, "last": last,
            "other": oth_c, "hashrate": hr_c, "modified": pub}


# ---------------------------------------------------------------- index
def build_index(all_days, site, today):
    days = prepare(all_days)
    rows = []
    for y, m in reversed(months_in(days)):
        cur = [d for d in days if (d["dt"].year, d["dt"].month) == (y, m)]
        if (y, m) < (2026, 10):        # September 2026 is only comparison data for October
            continue
        last = cur[-1]["dt"]
        full = last.day == calendar.monthrange(y, m)[1]
        rows.append((y, m, cur, last, full))
    items = "".join(
        f'<li><a href="/reports/{slug(y, m)}/"><b>{calendar.month_name[m]} {y}</b></a> – '
        f'{fmt(avg(cur, "other"))} transactions a day{" outside the block-history recorder" if any(d["recorder_transactions"] for d in cur) else ""}, '
        f'{avg(cur, "hashrate_phs"):.1f} PH/s hashrate. {"Full month." if full else f"Data through {fdate(last)}; updated weekly."}</li>'
        for y, m, cur, last, full in rows)
    url = BASE
    ttl = "Kadena network reports"
    desc = ("Monthly reports on Kadena mainnet from Kadena Nexus: daily transactions, blocks and mining hashrate on all 20 chains, "
            "from public chain data, updated every week, with CSV downloads.")
    ld = {"@context": "https://schema.org", "@graph": [
        ORG,
        {"@type": "CollectionPage", "name": ttl, "url": url, "description": desc, "inLanguage": "en",
         "dateModified": today.isoformat(), "publisher": {"@id": "https://kadena.ws/#org"},
         "mainEntity": {"@type": "ItemList", "itemListElement": [
             {"@type": "ListItem", "position": i + 1, "url": BASE + slug(y, m) + "/", "name": title(y, m)}
             for i, (y, m, *_r) in enumerate(rows)]}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Kadena Nexus", "item": "https://kadena.ws/"},
            {"@type": "ListItem", "position": 2, "name": ttl, "item": url}]}]}
    first = days[0]["dt"]
    body = f'''<main id="main">
  <article class="policy" aria-labelledby="r-title">
    <div class="wrap">
      <div class="topbar"><p class="crumb"><a href="/">Kadena Nexus</a> / Reports</p>{badge(today, days[-1]["dt"])}</div>
      <h1 id="r-title">Kadena network reports</h1>
      <p class="lede">One report per month on how Kadena mainnet is used: transactions, blocks and mining hashrate across all 20 chains, measured by Kadena Nexus from public chain data. The current month's report is updated every week.</p>
      <h2>Monthly reports</h2>
      <ul class="sum">{items}</ul>
      <h2>Data</h2>
      <p>Every day since {fdate(first)}, {first.year} is in one file, with transactions per chain and recorder calls counted separately: <a href="/reports/data/kadena-daily.csv" download>Kadena daily network data (CSV)</a>. It is free to use with credit to Kadena Nexus (CC BY 4.0).</p>
      <h2>Live numbers</h2>
      <p>For what is happening right now, see the <a href="https://nodes.kadena.ws/">Kadena Network Monitor</a> and today's <a href="https://adoption.kadena.ws/">Adoption Index</a>. Daily news: <a href="/news/">Kadena news</a>.</p>
      <p class="updated">Kadena Nexus is an independent community project and is not affiliated with Kadena LLC. Nothing here is financial advice.</p>
    </div>
  </article>
</main>'''
    os.makedirs(os.path.join(site, "reports"), exist_ok=True)
    with open(os.path.join(site, "reports", "index.html"), "w", encoding="utf-8") as f:
        f.write(shell(site, ttl, desc, url, ld, "", body))
    return [(y, m) for y, m, *_r in rows]


if __name__ == "__main__":
    data, site_dir, ym = sys.argv[1], sys.argv[2], sys.argv[3]
    y_, m_ = map(int, ym.split("-"))
    print(build_month(read_csv(data), y_, m_, site_dir, snapshot()))
    build_index(read_csv(data), site_dir, dt.date.today())
