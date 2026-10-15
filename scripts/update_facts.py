#!/usr/bin/env python3
"""Refresh the changing facts on the Kadena Nexus homepage, FAQ and How to buy KDA pages.

Run from anywhere: python3 scripts/update_facts.py   (runs daily before deploy)

Only text inside <span data-auto="NAME">...</span> markers is replaced. The
explanations around them stay hand-written. Sources:
  - kda-chain.org/ecosystem.html  exchanges and DEXs listed by the Kadena
                                  Community Edition site
  - kda-chain.org/wallets.html    self-custody wallets listed there
  - GitHub kda-community/chainweb-node latest release
  - Kadena Network Monitor 24h transactions and Adoption Index score
  - KDA in circulation and the frozen platform share from site/tokenomics/
    tokenomics.json (built just before by scripts/tokenomics/build_tokenomics.py)

Safety: every source has a timeout and a sanity check. If a source fails or
looks wrong, that marker keeps its current text. The FAQPage JSON-LD answers
are re-synced from the visible answers. "Last updated" and dateModified move
to today only when a fact differs from the live page. The script never fails
the build: on any unexpected error it leaves the files untouched and exits 0.

Environment: GITHUB_TOKEN (optional), FACTS_OFFLINE=1 (skip all fetches).
Python 3 standard library only.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
PAGES = {"index.html": "https://kadena.ws/", "faq/index.html": "https://kadena.ws/faq/", "buy-kda/index.html": "https://kadena.ws/buy-kda/"}
UA = "KadenaNexus-facts-updater (+https://kadena.ws/faq/)"
TIMEOUT = 25
OFFLINE = os.environ.get("FACTS_OFFLINE") == "1"
TODAY = dt.datetime.now(dt.timezone.utc).date()


def warn(msg):
    print(f"update_facts: {msg}", file=sys.stderr)


def fetch(url, data=None):
    if OFFLINE:
        raise RuntimeError("offline")
    headers = {"User-Agent": UA}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def join(items, word):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" {word} " + items[-1]


def esc(s):
    return html.escape(s, quote=True)


def long_date(d):
    return f"{d:%B} {d.day}, {d.year}"


# ---------------------------------------------------------------- sources
def ecosystem():
    """Exchanges and DEXs from kda-chain.org, as [(name, url)]."""
    t = fetch("https://kda-chain.org/ecosystem.html")
    out = {"exchanges": [], "dex": []}
    for card in re.split(r'class="project-card', t)[1:]:
        cat = re.search(r'data-category="([^"]*)"', card)
        name = re.search(r"<h3[^>]*>\s*([^<]{1,40}?)\s*</h3>", card)
        site = re.search(r'<a href="(https://[^"\s]+)"[^>]*?aria-label="[^"]*Website"', card, re.S)
        if not (cat and name and site):
            continue
        for key in out:
            if key in cat.group(1).split():
                out[key].append((html.unescape(name.group(1)).strip(), site.group(1)))
    for key, rows in out.items():
        if not 1 <= len(rows) <= 10:
            raise ValueError(f"{key}: implausible count {len(rows)}")
    return out


def wallets():
    t = fetch("https://kda-chain.org/wallets.html")
    names = []
    for card in re.split(r'class="(?:wallet-card|project-card)', t)[1:]:
        n = re.search(r"<h3[^>]*>\s*([^<]{1,40}?)\s*</h3>", card)
        if n:
            names.append(html.unescape(n.group(1)).strip())
    if not 1 <= len(names) <= 12:
        raise ValueError(f"wallets: implausible count {len(names)}")
    return names


def node_release():
    r = json.loads(fetch("https://api.github.com/repos/kda-community/chainweb-node/releases/latest"))
    tag = r["tag_name"].lstrip("v")
    if not re.fullmatch(r"\d+\.\d+(\.\d+)?", tag):
        raise ValueError(f"release tag {tag!r}")
    day = dt.date.fromisoformat(r["published_at"][:10])
    return f"chainweb-node {tag} ({day:%B} {day.year})"


def network_today():
    parts = []
    try:
        tx = int(float(fetch("https://nodes.kadena.ws/data/tx24h").split()[0]))
        if 0 < tx < 10_000_000:
            parts.append(f"{tx:,} transactions in the last 24 hours")
    except Exception as e:  # noqa: BLE001
        warn(f"tx24h: {e}")
    try:
        a = json.loads(fetch("https://adoption.kadena.ws/api/index"))
        if a.get("state") == "ready" and 0 < float(a["score"]) < 1000:
            parts.append(f"Adoption Index {a['score']} (baseline 50)")
    except Exception as e:  # noqa: BLE001
        warn(f"adoption: {e}")
    if not parts:
        raise ValueError("no network numbers")
    return " · ".join(parts)


def tokenomics():
    """Circulating supply and frozen platform share, as counted by
    scripts/tokenomics/build_tokenomics.py earlier in the same build."""
    t = json.load(open(os.path.join(SITE, "tokenomics", "tokenomics.json")))
    v, fz = float(t["circulating"]), float(t["frozen"])
    if not (2e8 < v < 1e9 and 0 <= fz < 2e8):
        raise ValueError(f"tokenomics {v} {fz}")
    return v, fz


# ---------------------------------------------------------------- facts
def gather():
    facts = {}

    def put(fn, build):
        try:
            facts.update(build(fn()))
        except Exception as e:  # noqa: BLE001
            warn(f"{fn.__name__}: kept current text ({e})")

    def eco(o):
        ex, dx = o["exchanges"], o["dex"]
        return {
            "exchanges-or": esc(join([n for n, _ in ex], "or")),
            "exchanges-and": esc(join([n for n, _ in ex], "and")),
            "exchanges-links": join([f'<a href="{esc(u)}"><strong>{esc(n)}</strong></a>' for n, u in ex], "and"),
            "dex-or": esc(join([n for n, _ in dx], "or")),
            "dex-links": join([f'<a href="{esc(u)}">{esc(n)}</a>' for n, u in dx], "or"),
        }

    put(ecosystem, lambda o: {**eco(o), "month": f"{TODAY:%B} {TODAY.year}"})
    put(wallets, lambda w: {"wallets-and": esc(join(w, "and"))})
    put(node_release, lambda s: {"node-release": esc(s)})
    put(network_today, lambda s: {"network-today": esc(s)})
    put(tokenomics, lambda s: {"supply": f"about {s[0] / 1e6:.0f} million KDA", "frozen": f"{s[1]:,.0f} KDA"})
    return facts


SPAN = re.compile(r'(<span data-auto="([a-z-]+)">)(.*?)(</span>)', re.S)


def spans(t):
    return {m.group(2): m.group(3) for m in SPAN.finditer(t)}


def apply(t, facts):
    return SPAN.sub(lambda m: m.group(1) + facts.get(m.group(2), m.group(3)) + m.group(4), t)


def strip(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def sync_faq_ld(t):
    """Set each FAQPage answer to the visible answer under the same question."""
    m = re.search(r'(<script type="application/ld\+json">\s*)(.*?)(\s*</script>)', t, re.S)
    if not m:
        return t
    data = json.loads(m.group(2))
    for node in data.get("@graph", []):
        if node.get("@type") != "FAQPage":
            continue
        for q in node.get("mainEntity", []):
            vis = re.search(r"<h3>\s*" + re.escape(esc(q["name"]).replace("&#x27;", "'")) + r"\s*</h3>\s*<p>(.*?)</p>", t, re.S)
            if vis:
                q["acceptedAnswer"]["text"] = strip(vis.group(1))
    return t[:m.start(2)] + json.dumps(data, indent=1, ensure_ascii=False) + t[m.end(2):]


def set_dates(t, day):
    t = re.sub(r'("dateModified":\s*")\d{4}-\d{2}-\d{2}(")', lambda m: m.group(1) + day.isoformat() + m.group(2), t)
    return re.sub(r"(Last updated )[A-Z][a-z]+ \d{1,2}, \d{4}(\.)", lambda m: m.group(1) + long_date(day) + m.group(2), t)


def live_state(url):
    """Marker texts and dates on the deployed page, or None."""
    try:
        t = fetch(url)
    except Exception as e:  # noqa: BLE001
        warn(f"live {url}: {e}")
        return None
    d = re.search(r'"dateModified":\s*"(\d{4}-\d{2}-\d{2})"', t)
    return spans(t), (dt.date.fromisoformat(d.group(1)) if d else None)


def main():
    facts = gather()
    for rel, url in PAGES.items():
        path = os.path.join(SITE, rel)
        try:
            t = open(path, encoding="utf-8").read()
            new = sync_faq_ld(apply(t, facts))
            live = live_state(url)
            now = spans(new)
            if live and live[0] == now and live[1]:
                day = live[1]          # nothing changed since the last deploy
            elif live is None:
                day = None             # cannot compare: keep the file's own dates
            else:
                day = TODAY
            if day:
                new = set_dates(new, day)
            for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', new, re.S):
                json.loads(b)
            if new != t:
                open(path, "w", encoding="utf-8").write(new)
            print(f"update_facts: {rel}: {len(now)} facts, dated {day or 'unchanged'}")
        except Exception as e:  # noqa: BLE001
            warn(f"{rel}: left untouched ({e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
