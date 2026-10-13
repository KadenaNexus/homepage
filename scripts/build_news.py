#!/usr/bin/env python3
"""Build the Kadena news page (site/news/index.html) from public data.

Run from anywhere: python3 scripts/build_news.py

Sources, each fetched with a timeout and dropped from the page if it fails:
  - kda-community GitHub: chainweb-node releases, merged pull requests (or
    commits) in chainweb-node and pact-5 from the last 8 weeks
  - Kadena Community Edition Adoption Index public API (score vs baseline 50)
  - Kadena Network Monitor data files (24h transactions, block time, chains)
The curated list site/news/nexus-updates.json is always included.

The page reuses the shell of site/faq/index.html (header, nav, footer, CSS).
The script never fails the build because a source is down. If the page cannot
be built at all (for example the FAQ template changed shape), it keeps the
existing site/news/index.html, prints a warning and exits 0.

Environment:
  GITHUB_TOKEN   optional, raises the GitHub API rate limit
  NEWS_OFFLINE=1 skip every network fetch (tests the fallback page)

Python 3 standard library only.
"""
import datetime as dt
import html
import json
import math
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
TEMPLATE = os.path.join(SITE, "faq", "index.html")
OUT = os.path.join(SITE, "news", "index.html")
UPDATES = os.path.join(SITE, "news", "nexus-updates.json")
SITEMAP = os.path.join(SITE, "sitemap.xml")

PAGE_URL = "https://kadena.ws/news/"
OG_IMAGE = "https://kadena.ws/og/og-home.jpg"
GITHUB_ORG = "kda-community"
RELEASE_REPO = "chainweb-node"
DEV_REPOS = ("chainweb-node", "pact-5")
DEV_WINDOW_DAYS = 56
TIMEOUT = 15
UA = "KadenaNexus-news-builder (+https://kadena.ws/news/)"

ADOPTION_API = "https://adoption.kadena.ws/api/index"
MONITOR = "https://nodes.kadena.ws/data/"

NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.date()


class BuildError(Exception):
    pass


def warn(msg):
    print(f"::warning::build_news: {msg}")


def fetch(url, want_json=False):
    """GET a URL with a timeout. Raises on any failure."""
    if os.environ.get("NEWS_OFFLINE") == "1":
        raise OSError("NEWS_OFFLINE=1")
    headers = {"User-Agent": UA}
    if url.startswith("https://api.github.com/"):
        headers["Accept"] = "application/vnd.github+json"
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read(2_000_000).decode("utf-8", "replace")
    return json.loads(body) if want_json else body


def parse_day(value):
    """'2026-10-09T12:00:00Z' or '2026-10-09' -> date, or None."""
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def long_date(d):
    return f"{d:%B} {d.day}, {d.year}"


def short_date(d):
    return f"{d:%b} {d.day}, {d.year}"


def esc(s):
    return html.escape(str(s), quote=True)


def clip(s, n=110):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# ---------------------------------------------------------------- sources


def network_stats():
    """Each stat is (label, value, note). A failing source is skipped."""
    stats, used = [], []
    try:
        first = fetch(MONITOR + "tx24h").strip().splitlines()[0].split()[0]
        n = int(first)
        if n < 0:
            raise ValueError(n)
        stats.append(("Transactions in the last 24 hours", f"{n:,}", "all 20 chains"))
        used.append("monitor")
    except Exception as e:  # noqa: BLE001
        warn(f"tx24h unavailable ({e})")
    try:
        sec = float(fetch(MONITOR + "avgblocktime").strip().split()[0])
        if not (math.isfinite(sec) and 0 < sec < 3600):
            raise ValueError(sec)
        stats.append(("Average block time", f"{sec:,.2f} s", "per chain, target 30 s"))
        used.append("monitor")
    except Exception as e:  # noqa: BLE001
        warn(f"avgblocktime unavailable ({e})")
    try:
        pct = float(fetch(MONITOR + "activechains").strip().splitlines()[0].split()[0])
        if not (math.isfinite(pct) and 0 <= pct <= 100):
            raise ValueError(pct)
        shown = f"{pct:.0f}%" if abs(pct - round(pct)) < 0.05 else f"{pct:.1f}%"
        stats.append(("Active chains", shown, "of 20 chains producing blocks"))
        used.append("monitor")
    except Exception as e:  # noqa: BLE001
        warn(f"activechains unavailable ({e})")
    try:
        data = fetch(ADOPTION_API, want_json=True)
        score = data.get("score")
        day = parse_day(data.get("day"))
        if data.get("state") != "ready" or not finite(score) or score < 0 or day is None:
            raise ValueError("index not ready")
        shown = f"{score:,.0f}" if float(score).is_integer() else f"{score:,.1f}"
        stats.append(("Adoption Index score", shown, f"baseline 50, for {short_date(day)}"))
        used.append("adoption")
    except Exception as e:  # noqa: BLE001
        warn(f"adoption index unavailable ({e})")
    return stats, sorted(set(used))


def github_items():
    """Releases plus recent merged PRs (or commits) from kda-community."""
    api = "https://api.github.com/repos/" + GITHUB_ORG + "/"
    cutoff = TODAY - dt.timedelta(days=DEV_WINDOW_DAYS)
    releases, dev = [], []
    try:
        for r in fetch(api + RELEASE_REPO + "/releases?per_page=10", want_json=True):
            day = parse_day(r.get("published_at"))
            url = r.get("html_url", "")
            if r.get("draft") or not day or not url.startswith("https://github.com/"):
                continue
            name = clip(r.get("tag_name") or r.get("name") or "", 60)
            if not name:
                continue
            kind = "pre-release" if r.get("prerelease") else "release"
            releases.append((day, f"{RELEASE_REPO} {name}", kind, url))
        releases = sorted(releases, reverse=True)[:3]
    except Exception as e:  # noqa: BLE001
        warn(f"GitHub releases unavailable ({e})")

    for repo in DEV_REPOS:
        found = []
        try:
            pulls = fetch(api + repo + "/pulls?state=closed&sort=updated&direction=desc&per_page=50", want_json=True)
            for p in pulls:
                day = parse_day(p.get("merged_at"))
                url = p.get("html_url", "")
                if not day or day < cutoff or not url.startswith("https://github.com/"):
                    continue
                if (p.get("user") or {}).get("type") == "Bot":
                    continue
                found.append((day, f"{repo}: {clip(p.get('title', ''))}", f"merged PR #{p.get('number')}", url))
        except Exception as e:  # noqa: BLE001
            warn(f"GitHub pull requests for {repo} unavailable ({e})")
            continue
        if not found:
            try:
                commits = fetch(api + repo + f"/commits?since={cutoff.isoformat()}T00:00:00Z&per_page=30", want_json=True)
                for c in commits:
                    info = c.get("commit") or {}
                    day = parse_day((info.get("committer") or {}).get("date"))
                    url = c.get("html_url", "")
                    msg = (info.get("message") or "").splitlines()[0] if info.get("message") else ""
                    if not day or not msg or msg.startswith("Merge ") or not url.startswith("https://github.com/"):
                        continue
                    found.append((day, f"{repo}: {clip(msg)}", "commit", url))
                found = found[:5]
            except Exception as e:  # noqa: BLE001
                warn(f"GitHub commits for {repo} unavailable ({e})")
        dev.extend(found)
    dev = sorted(dev, reverse=True)[:10]
    return releases, dev


def nexus_updates():
    try:
        with open(UPDATES, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:  # noqa: BLE001
        warn(f"{UPDATES} unreadable ({e})")
        return []
    items = []
    for u in raw if isinstance(raw, list) else []:
        day = parse_day(u.get("date")) if isinstance(u, dict) else None
        text = u.get("text") if isinstance(u, dict) else None
        if not day or not isinstance(text, str) or not text.strip():
            continue
        body = esc(text)
        for phrase, url in (u.get("links") or {}).items():
            p = esc(phrase)
            if p in body and isinstance(url, str) and re.match(r"^(/|https://)", url):
                body = body.replace(p, f'<a href="{esc(url)}">{p}</a>', 1)
        label = u.get("display_date") or short_date(day)
        items.append((day, esc(label), body))
    return sorted(items, key=lambda i: i[0], reverse=True)


# ---------------------------------------------------------------- page

NEWS_CSS = """<style>
.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:14px;overflow:hidden;margin:0 0 .6rem}
.stats div{background:var(--ink);padding:1rem 1.1rem}
.stats div:last-child:nth-child(odd){grid-column:1 / -1}
.stats b{display:block;font:700 1.75rem/1.1 var(--display);color:var(--sand);font-variant-numeric:tabular-nums}
.stats .lbl{display:block;margin-top:.3rem;color:var(--sand);font-weight:500;font-size:.95rem}
.stats .note{display:block;font-size:.85rem}
.asof{font-size:.9rem;margin:0 0 1rem}
.policy .feed{list-style:none;padding:0;margin:0 0 1rem;border-top:1px solid var(--line)}
.feed li{padding:.75rem 0;border-bottom:1px solid var(--line);margin:0;overflow-wrap:anywhere}
.feed time,.feed .when{display:block;font-size:.85rem}
.feed .kind{font-size:.85rem;white-space:nowrap}
</style>
"""


def build_main(stats, stat_sources, releases, dev, updates):
    out = []
    a = out.append
    a('<main id="main">')
    a('  <article class="policy" aria-labelledby="news-title">')
    a('    <div class="wrap">')
    a('      <h1 id="news-title">Kadena news</h1>')
    a('      <p class="lede">What changed on Kadena this week: node releases, core development, network numbers and new community tools. Updated every week by Kadena Nexus.</p>')
    if stats:
        a("")
        a("      <h2>This week in numbers</h2>")
        a('      <div class="stats">')
        for label, value, note in stats:
            a(f'        <div><b>{esc(value)}</b><span class="lbl">{esc(label)}</span><span class="note">{esc(note)}</span></div>')
        a("      </div>")
        a(f'      <p class="asof">As of {long_date(TODAY)} (UTC). Live numbers: <a href="https://nodes.kadena.ws/">Kadena Network Monitor</a> and <a href="https://adoption.kadena.ws/">Adoption Index</a>.</p>')
    if releases or dev:
        a("")
        a("      <h2>Node releases and core development</h2>")
        a(f"      <p>New releases of the Kadena Community Edition node and changes merged in the last {DEV_WINDOW_DAYS // 7} weeks, from the public kda-community repositories on GitHub.</p>")
        a('      <ul class="feed">')
        for day, title, kind, url in releases + dev:
            a(f'        <li><time datetime="{day.isoformat()}">{short_date(day)}</time><a href="{esc(url)}">{esc(title)}</a> <span class="kind">({esc(kind)})</span></li>')
        a("      </ul>")
    a("")
    a("      <h2>From Kadena Nexus</h2>")
    if updates:
        a('      <ul class="feed">')
        for day, label, body in updates:
            a(f'        <li><time datetime="{day.isoformat()}">{label}</time>{body}</li>')
        a("      </ul>")
    else:
        a('      <p>See the <a href="/">Kadena Nexus home page</a> for our live tools.</p>')
    a("")
    a("      <h2>About Kadena</h2>")
    a('      <p>Kadena is a proof-of-work blockchain that runs 20 chains in parallel, called Chainweb, with smart contracts written in Pact. Its coin is KDA. After Kadena LLC wound down in late 2025, former Kadena engineers and community developers kept the network running as Kadena Community Edition. New here? Start with <a href="/community-edition/">What is Kadena Community Edition?</a>, the <a href="/faq/">Kadena FAQ</a> or <a href="/buy-kda/">How to buy KDA</a>.</p>')
    a("")
    a("      <h2>Sources</h2>")
    a('      <ul class="sources">')
    if releases or dev:
        a(f'        <li><a href="https://github.com/{GITHUB_ORG}">kda-community on GitHub</a> (chainweb-node and pact-5)</li>')
    if "monitor" in stat_sources:
        a('        <li><a href="https://nodes.kadena.ws/">Kadena Network Monitor</a>, Kadena Nexus</li>')
    if "adoption" in stat_sources:
        a('        <li><a href="https://adoption.kadena.ws/methodology">Adoption Index methodology</a>, Kadena Nexus</li>')
    a('        <li><a href="https://kda-chain.org/">kda-chain.org</a>, the Kadena Community Edition site</li>')
    a("      </ul>")
    a(f'      <p class="updated">Updated {long_date(TODAY)}. Built automatically every Monday from the public sources above by Kadena Nexus, an independent community project not affiliated with Kadena LLC. Not financial advice.</p>')
    a("    </div>")
    a("  </article>")
    a("</main>")
    return "\n".join(out)


def json_ld(description):
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": "https://kadena.ws/#org",
                "name": "Kadena Nexus",
                "url": "https://kadena.ws/",
                "logo": "https://kadena.ws/logo-kadena-nexus.png",
                "sameAs": ["https://x.com/KadenaNexus", "https://t.me/KadenaNexus", "https://github.com/KadenaNexus"],
            },
            {
                "@type": "CollectionPage",
                "@id": PAGE_URL + "#page",
                "name": "Kadena news",
                "headline": f"Kadena news: weekly updates for {TODAY:%B} {TODAY.year}",
                "description": description,
                "url": PAGE_URL,
                "inLanguage": "en",
                "dateModified": TODAY.isoformat(),
                "publisher": {"@id": "https://kadena.ws/#org"},
                "image": OG_IMAGE,
                "about": ["Kadena", "KDA", "Kadena Community Edition", "Chainweb"],
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Kadena Nexus", "item": "https://kadena.ws/"},
                    {"@type": "ListItem", "position": 2, "name": "Kadena news", "item": PAGE_URL},
                ],
            },
        ],
    }
    return '<script type="application/ld+json">\n' + json.dumps(graph, indent=1, ensure_ascii=False) + "\n</script>"


def sub_once(pattern, repl, text, what):
    new, n = re.subn(pattern, lambda _m: repl, text, count=1, flags=re.S | re.I)
    if n != 1:
        raise BuildError(f"template: could not find {what}")
    return new


def render(main_html):
    with open(TEMPLATE, encoding="utf-8") as f:
        t = f.read()
    month = f"{TODAY:%B} {TODAY.year}"
    title = f"Kadena news: weekly updates for {month} | Kadena Nexus"
    desc = (f"Kadena news for {month}: Kadena Community Edition node releases, core development, "
            "network stats and new community tools, updated every week by Kadena Nexus.")
    og_desc = "Node releases, core development, network numbers and new community tools for Kadena, every week."
    t = sub_once(r"<title>.*?</title>", f"<title>{esc(title)}</title>", t, "title")
    t = sub_once(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{esc(desc)}">', t, "meta description")
    t = sub_once(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{PAGE_URL}">', t, "canonical")
    t = sub_once(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="Kadena news, {esc(month)}">', t, "og:title")
    t = sub_once(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{esc(og_desc)}">', t, "og:description")
    t = sub_once(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{PAGE_URL}">', t, "og:url")
    t = sub_once(r'<meta property="og:type" content="[^"]*">', '<meta property="og:type" content="website">', t, "og:type")
    t = sub_once(r'<meta property="og:image" content="[^"]*">', f'<meta property="og:image" content="{OG_IMAGE}">', t, "og:image")
    t = sub_once(r'<meta name="twitter:image" content="[^"]*">', f'<meta name="twitter:image" content="{OG_IMAGE}">', t, "twitter:image")
    t = sub_once(r'<script type="application/ld\+json">.*?</script>', json_ld(desc), t, "JSON-LD")
    t = sub_once(r'(?=<link rel="icon")', NEWS_CSS, t, "icon link")
    t = sub_once(r'<main id="main">.*?</main>', main_html, t, "main")
    t = t.replace('<a href="/news/">', '<a href="/news/" aria-current="page">', 1)
    validate(t)
    return t


def validate(t):
    """The same rules as the deploy SEO check, so a bad page is never written."""
    for need, pat in [
        ("title", r"<title>[^<]+</title>"),
        ("meta description", r'<meta name="description" content="[^"]+">'),
        ("canonical", r'<link rel="canonical" href="https://'),
        ("og:image", r'<meta property="og:image" content="https://'),
        ("twitter:card", r'<meta name="twitter:card" content="[^"]+">'),
        ("footer", r"</footer>"),
    ]:
        if not re.search(pat, t, re.I):
            raise BuildError(f"generated page is missing {need}")
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S)
    if len(blocks) != 1:
        raise BuildError("generated page needs exactly one JSON-LD block")
    json.loads(blocks[0])
    body = re.sub(r"<script.*?</script>", "", t, flags=re.S | re.I)
    if len(re.findall(r"<h1[\s>]", body, re.I)) != 1:
        raise BuildError("generated page needs exactly one h1")


def update_sitemap():
    try:
        with open(SITEMAP, encoding="utf-8") as f:
            s = f.read()
        new, n = re.subn(
            r"(<loc>https://kadena\.ws/news/</loc><lastmod>)\d{4}-\d{2}-\d{2}(</lastmod>)",
            lambda m: m.group(1) + TODAY.isoformat() + m.group(2), s)
        if n != 1:
            warn("sitemap.xml has no kadena.ws/news/ entry with a lastmod; left unchanged")
        elif new != s:
            with open(SITEMAP, "w", encoding="utf-8") as f:
                f.write(new)
    except OSError as e:
        warn(f"sitemap.xml not updated ({e})")


def main():
    stats, stat_sources = network_stats()
    releases, dev = github_items()
    updates = nexus_updates()
    try:
        page = render(build_main(stats, stat_sources, releases, dev, updates))
    except Exception as e:  # noqa: BLE001
        if os.path.exists(OUT):
            warn(f"keeping the existing news page: {e}")
            return 0
        print(f"::error::build_news: {e}")
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    update_sitemap()
    print(f"build_news: wrote {os.path.relpath(OUT, ROOT)} with {len(stats)} stats, "
          f"{len(releases)} releases, {len(dev)} dev items, {len(updates)} Nexus updates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
