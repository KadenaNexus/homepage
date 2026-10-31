#!/usr/bin/env python3
"""Tell Bing (and other IndexNow search engines) which kadena.ws pages changed.

Runs last in the daily site build (see .github/workflows/deploy.yml):
  python3 scripts/indexnow.py

It compares each page the build produced with the version live on kadena.ws
and sends the URLs that differ to https://api.indexnow.org/indexnow, which
shares them with Bing, Yandex, Seznam and Naver. Google does not use IndexNow;
it reads the sitemap.

The key is the file site/<key>.txt (deployed with the site), as IndexNow
requires. Only the deploy job submits (it is the one that sets DEPLOY_KEY,
emptied for the build); pull-request checks and local runs only print what
they would send. Never fails the build. Python 3 standard library only.
"""
import glob
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
HOST = "kadena.ws"
UA = {"User-Agent": "KadenaNexus-indexnow (+https://kadena.ws/)"}
PAGES = ["index.html", "tokenomics/index.html", "news/index.html", "faq/index.html", "buy-kda/index.html",
         "community-edition/index.html", "reports/index.html", "whales/index.html", "tps/index.html"]


def log(m):
    print(f"indexnow: {m}", file=sys.stderr, flush=True)


def key():
    keys = [os.path.basename(p)[:-4] for p in glob.glob(os.path.join(SITE, "*.txt"))
            if re.fullmatch(r"[0-9a-f]{32}", os.path.basename(p)[:-4])]
    if len(keys) != 1:
        raise RuntimeError(f"expected one IndexNow key file in site/, found {len(keys)}")
    return keys[0]


def url_of(rel):
    path = rel[:-len("index.html")]
    return f"https://{HOST}/{path}"


def live(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None          # new page or unreachable: submit it


def main():
    k = key()
    pages = PAGES + sorted(os.path.relpath(p, SITE) for p in glob.glob(os.path.join(SITE, "reports", "*", "index.html")))
    changed = []
    for rel in pages:
        path = os.path.join(SITE, rel)
        if not os.path.exists(path):
            continue
        url = url_of(rel)
        if open(path, encoding="utf-8").read() != live(url):
            changed.append(url)
    if not changed:
        log("no page changed")
        return
    in_deploy = "DEPLOY_KEY" in os.environ or os.environ.get("INDEXNOW_SUBMIT") == "1"
    if not in_deploy:
        log(f"would submit {len(changed)}: {', '.join(changed)}")
        return
    body = json.dumps({"host": HOST, "key": k, "keyLocation": f"https://{HOST}/{k}.txt", "urlList": changed}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8", **UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        log(f"submitted {len(changed)} URLs, HTTP {r.status}: {', '.join(changed)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log(f"skipped ({e!r})")
    sys.exit(0)
