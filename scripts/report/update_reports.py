#!/usr/bin/env python3
"""Keep the Kadena network reports on kadena.ws up to date, with no commits.

Runs in the daily site build (see .github/workflows/deploy.yml):
  python3 scripts/report/update_reports.py

1. Starts from the daily data already published at
   https://kadena.ws/reports/data/kadena-daily.csv (or the copy committed in
   site/reports/data/ if that is newer or the site is unreachable).
2. Once a week, when the newest day is 7 or more days old, and also as soon as
   a month has ended, collects the missing days from the public Chainweb
   indexer with collect_network.py. This happens only in the deploy job (not
   in pull-request checks) and takes about 1–2 minutes per day of data.
3. Rebuilds the page of every month that got new days, plus any month whose
   page is missing or was made by an older template. Months with nothing new
   keep their published page exactly as it is.
4. Rebuilds /reports/, the master CSV and the report entries in sitemap.xml.

It never fails the build: if collecting fails, the pages are built from the
data already published, and if anything else goes wrong the committed files
are left as they are. Environment: REPORT_OFFLINE=1 skips all network access,
REPORT_COLLECT=1 forces collecting even outside the deploy job.
"""
import datetime as dt
import json
import os
import re
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_report as br  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
SITE = os.path.join(ROOT, "site")
MASTER = os.path.join(SITE, "reports", "data", "kadena-daily.csv")
LIVE = "https://kadena.ws/reports/"
OFFLINE = os.environ.get("REPORT_OFFLINE") == "1"
UA = {"User-Agent": "KadenaNexus-report (+https://kadena.ws/reports/)"}
TODAY = dt.datetime.now(dt.timezone.utc).date()
YESTERDAY = TODAY - dt.timedelta(days=1)
WEEK = 7
MAX_DAYS = 35


def log(msg):
    print(f"update_reports: {msg}", file=sys.stderr, flush=True)


def fetch(url, binary=False):
    if OFFLINE:
        raise RuntimeError("offline")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        b = r.read()
    return b if binary else b.decode("utf-8", "replace")


def merged_data():
    rows = {d["date"]: d for d in br.read_csv(MASTER)}
    try:
        tmp = os.path.join(tempfile.mkdtemp(), "live.csv")
        open(tmp, "wb").write(fetch(LIVE + "data/kadena-daily.csv", binary=True))
        live = br.read_csv(tmp)
        rows.update({d["date"]: d for d in live})
        log(f"live data: {len(live)} days through {live[-1]['date'] if live else '-'}")
    except Exception as e:  # noqa: BLE001
        log(f"live data unavailable, using the committed copy ({e})")
    return [rows[k] for k in sorted(rows)]


def due(last):
    """True when new days should be collected now."""
    if last >= YESTERDAY:
        return False
    month_end = (last.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return (YESTERDAY - last).days >= WEEK or month_end <= YESTERDAY and last < month_end


def sane(d):
    return 50_000 <= d["blocks"] <= 60_000 and 0 <= d["recorder_transactions"] <= d["transactions"] < 5_000_000 \
        and 1 < d["hashrate_phs"] < 1000


def collect(start, end):
    import collect_network as cn
    out = os.path.join(tempfile.mkdtemp(), "days.json")
    cn.main(start.isoformat(), end.isoformat(), out)
    new = []
    for d in json.load(open(out))["days"]:
        if not sane(d):
            log(f"{d['date']} looks wrong ({d['blocks']} blocks); stopping before it")
            break
        new.append(d)
    return new


def keep_live_page(year, month):
    """Copy the published page and its CSV files into site/. True if it is current."""
    s = br.slug(year, month)
    try:
        page = fetch(f"{LIVE}{s}/")
    except Exception as e:  # noqa: BLE001
        log(f"{s}: no live page ({e})")
        return False
    if f'content="{br.GENERATOR}"' not in page:
        log(f"{s}: live page uses an older template")
        return False
    out = os.path.join(SITE, "reports", s)
    os.makedirs(out, exist_ok=True)
    for name in set(re.findall(r'href="(kadena-daily-[\w.-]+\.csv)"', page)):
        open(os.path.join(out, name), "wb").write(fetch(f"{LIVE}{s}/{name}", binary=True))
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(page)
    return True


def published_date(year, month):
    for src in (lambda: fetch(f"{LIVE}{br.slug(year, month)}/"),
                lambda: open(os.path.join(SITE, "reports", br.slug(year, month), "index.html"), encoding="utf-8").read()):
        try:
            m = re.search(r'"datePublished": "(\d{4}-\d{2}-\d{2})"', src())
            if m:
                return dt.date.fromisoformat(m.group(1))
        except Exception:  # noqa: BLE001
            pass
    return None


def update_sitemap(months, modified):
    path = os.path.join(SITE, "sitemap.xml")
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"\s*<url><loc>https://kadena\.ws/reports/[^<]*</loc>.*?</url>", "", t)
    entries = [f'  <url><loc>{LIVE}</loc><lastmod>{TODAY.isoformat()}</lastmod><priority>0.8</priority></url>']
    for y, m in months:
        lm = modified.get((y, m)) or TODAY
        entries.append(f'  <url><loc>{LIVE}{br.slug(y, m)}/</loc><lastmod>{lm.isoformat()}</lastmod><priority>0.7</priority></url>')
    anchor = "  <url><loc>https://kadena.ws/news/</loc>"
    t = t.replace(anchor, "\n".join(entries) + "\n" + anchor, 1) if anchor in t else t.replace("</urlset>", "\n".join(entries) + "\n</urlset>")
    open(path, "w", encoding="utf-8").write(t)


def main():
    data = merged_data()
    last = dt.date.fromisoformat(data[-1]["date"])
    changed = set()
    # Collect in the deploy job only (it is the one that sets DEPLOY_KEY, emptied for the build), or when run by hand.
    in_deploy = ("GITHUB_ACTIONS" not in os.environ or "DEPLOY_KEY" in os.environ
                 or os.environ.get("REPORT_COLLECT") == "1")
    if not OFFLINE and in_deploy and due(last):
        end = min(YESTERDAY, last + dt.timedelta(days=MAX_DAYS))
        log(f"collecting {last + dt.timedelta(days=1)} to {end}")
        try:
            new = collect(last + dt.timedelta(days=1), end)
            have = {d["date"] for d in data}
            data += [d for d in new if d["date"] not in have]
            data.sort(key=lambda d: d["date"])
            changed = {(dt.date.fromisoformat(d["date"]).year, dt.date.fromisoformat(d["date"]).month) for d in new}
            log(f"added {len(new)} days")
        except Exception as e:  # noqa: BLE001
            log(f"collecting failed, publishing the existing data ({e})")
    else:
        log(f"no collection (newest day {last}, deploy job: {in_deploy})")

    br.write_csv(MASTER, data)
    days = br.prepare(data)
    months = [ym for ym in br.months_in(days) if ym >= (2026, 10)]
    snap = None
    modified = {}
    for y, m in months:
        if (y, m) not in changed and not OFFLINE and keep_live_page(y, m):
            p = open(os.path.join(SITE, "reports", br.slug(y, m), "index.html"), encoding="utf-8").read()
            d = re.search(r'"dateModified": "(\d{4}-\d{2}-\d{2})"', p)
            modified[(y, m)] = dt.date.fromisoformat(d.group(1)) if d else None
            continue
        if snap is None:
            snap = br.snapshot() if not OFFLINE else {"when": TODAY}
        r = br.build_month(data, y, m, SITE, snap, published=published_date(y, m))
        modified[(y, m)] = r["modified"]
        log(f"built {r['slug']} (data through {r['last']})")
    br.build_index(data, SITE, TODAY)
    update_sitemap(months, modified)
    for root, _, names in os.walk(os.path.join(SITE, "reports")):
        for n in names:
            if n.endswith(".html"):
                for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                                    open(os.path.join(root, n), encoding="utf-8").read(), re.S):
                    json.loads(b)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        log(f"left the committed report files as they are ({e!r})")
        sys.exit(0)
