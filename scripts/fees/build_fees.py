#!/usr/bin/env python3
"""Build kadena.ws/research/fees/ – what a simple transfer costs today, chain by chain.

Runs in the daily site build:
  python3 scripts/fees/build_fees.py

For each chain: (fee rate from a public source) x (standard size of a transfer),
converted to US dollars with CoinGecko prices. Kadena's figures are measured
from recent mainnet blocks (median gas price and gas used by real coin.transfer
transactions).

Writes site/research/fees/index.html, fees.json and fees-history.csv.
Never fails the build: a chain whose source cannot be read keeps its last
published value, marked stale with its date; if nothing can be read at all,
the committed page stays.
Environment: FEES_OFFLINE=1 skips network access.
Python 3 standard library only.
"""
import base64
import csv
import datetime as dt
import html
import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SITE = os.path.join(ROOT, "site")
OUT = os.path.join(SITE, "research", "fees")
sys.path.insert(0, os.path.join(ROOT, "scripts", "report"))
import build_report as br  # noqa: E402  (page shell, table helper)

URL = "https://kadena.ws/research/fees/"
LIVE = "https://kadena.ws/research/fees/"
NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
TODAY = NOW.date()
UA = "KadenaNexus-fees (+https://kadena.ws/research/fees/)"

KDA_NODE = "https://api.chainweb-community.org/chainweb/0.0/mainnet01"
KDA_TRANSFER_GAS_FALLBACK = 245     # NR-001: 408 TPS at 150,000 gas per block, 20 chains, 30 s blocks
KDA_TOKEN_GAS = 1000                # upper estimate for a fungible-v2 token transfer (kb-USDC, USDT)

EVM = {
    "ethereum": ("https://ethereum-rpc.publicnode.com", "ethereum"),
    "base": ("https://base-rpc.publicnode.com", "ethereum"),
    "bnb": ("https://bsc-rpc.publicnode.com", "binancecoin"),
    "polygon": ("https://polygon-bor-rpc.publicnode.com", "polygon-ecosystem-token"),
}
NATIVE_GAS, ERC20_GAS = 21000, 65000
BASE_ORACLE = "0x420000000000000000000000000000000000000F"   # Base GasPriceOracle
NATIVE_BYTES, ERC20_BYTES = 110, 175                          # signed tx sizes for the L1 data fee

CHAINS = [  # key, name, coin, stablecoin label, CoinGecko id, note
    ("kadena", "Kadena", "KDA", "kb-USDC / USDT", "kadena",
     "Median gas price and gas used by real coin.transfer and transfer-create transactions in the last 3 hours of mainnet blocks. Token transfer uses an upper estimate of 1,000 gas."),
    ("ethereum", "Ethereum", "ETH", "USDC / USDT", "ethereum",
     "Base fee plus median priority fee of the last 5 blocks; 21,000 gas for ETH, 65,000 gas for a token transfer."),
    ("base", "Base", "ETH", "USDC", "ethereum",
     "Same as Ethereum, plus Base's fee for posting the transaction to Ethereum (upper bound from Base's fee oracle)."),
    ("bnb", "BNB Chain", "BNB", "USDT", "binancecoin",
     "Gas price from the last 5 blocks; 21,000 gas for BNB, 65,000 gas for a token transfer."),
    ("polygon", "Polygon PoS", "POL", "USDC", "polygon-ecosystem-token",
     "Base fee plus median priority fee of the last 5 blocks; 21,000 gas for POL, 65,000 gas for a token transfer."),
    ("solana", "Solana", "SOL", "USDC", "solana",
     "5,000 lamport base fee plus the median recent priority fee, for 450 compute units (SOL) and 6,000 (USDC)."),
    ("tron", "Tron", "TRX", "USDT", "tron",
     "TRX transfer uses 268 bandwidth (free up to 600 a day). USDT transfer uses 64,285 energy, burned at the network price; near zero for senders who stake TRX for energy."),
    ("bitcoin", "Bitcoin", "BTC", None, "bitcoin",
     "mempool.space recommended fee for the next 30 minutes, for a 141 vB one-input, two-output transfer."),
    ("stellar", "Stellar", "XLM", "USDC", "stellar",
     "Median fee charged in recent ledgers (Horizon fee_stats); one operation."),
    ("xrpl", "XRP Ledger", "XRP", "RLUSD", "ripple",
     "Current open-ledger fee from a public rippled server; one payment."),
]


# ---------------------------------------------------------------- fetching
def get(url, body=None, timeout=30, accept="application/json"):
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                               headers={"content-type": "application/json", "accept": accept, "User-Agent": UA})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


def rpc(url, method, params):
    r = get(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if "error" in r:
        raise RuntimeError(r["error"])
    return r["result"]


def b64(s):
    return json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))


def kadena():
    """Median gas price and gas used of plain coin.transfer txs in recent blocks."""
    cut = get(f"{KDA_NODE}/cut")
    prices, gas = [], []
    for c, h in sorted(cut["hashes"].items(), key=lambda kv: int(kv[0])):
        hi = h["height"]
        hdrs = get(f"{KDA_NODE}/chain/{c}/header?minheight={max(0, hi - 360)}&maxheight={hi}&limit=360",
                   timeout=60, accept="application/json;blockheader-encoding=object")
        hashes = [x["payloadHash"] for x in hdrs.get("items", []) if isinstance(x, dict) and "payloadHash" in x]
        if not hashes:
            continue
        for p in get(f"{KDA_NODE}/chain/{c}/payload/outputs/batch", hashes, timeout=60):
            for tx, out in p.get("transactions", []):
                cmd = json.loads(b64(tx)["cmd"])
                code = (cmd.get("payload", {}).get("exec") or {}).get("code", "")
                if not code.strip().startswith(("(coin.transfer ", "(coin.transfer-create ")):
                    continue
                o = b64(out)
                if o.get("result", {}).get("status") != "success":
                    continue
                prices.append(float(cmd["meta"]["gasPrice"]))
                gas.append(int(o["gas"]))
        if len(gas) >= 60:
            break
    if gas:
        g, gp, n = statistics.median(gas), statistics.median(prices), len(gas)
    else:  # quiet network: no plain transfers found, use the protocol minimum
        g, gp, n = KDA_TRANSFER_GAS_FALLBACK, 1e-8, 0  # minimum gas price; gas per transfer from NR-001
    return {"native": g * gp, "stable": KDA_TOKEN_GAS * gp, "unit": "KDA",
            "detail": f"gas price {gp:.10f}".rstrip("0") + f" KDA, {g:.0f} gas per transfer" + (f" (median of {n} recent mainnet transfers)" if n else " (no transfers in the last 3 hours: minimum gas price, gas per transfer from NR-001)")}


def evm(key):
    url, _ = EVM[key]
    fh = rpc(url, "eth_feeHistory", ["0x5", "latest", [50]])
    base = int(fh["baseFeePerGas"][-1], 16)
    tips = [int(r[0], 16) for r in fh.get("reward", []) if r]
    tip = int(statistics.median(tips)) if tips else 0
    if key == "bnb" or base == 0:
        price = int(rpc(url, "eth_gasPrice", []), 16)
    else:
        price = base + tip
    native, stable = NATIVE_GAS * price / 1e18, ERC20_GAS * price / 1e18
    extra = ""
    if key == "base":
        def l1(n):
            data = "0xf1c7a58b" + format(n, "064x")
            return int(rpc(url, "eth_call", [{"to": BASE_ORACLE, "data": data}, "latest"]), 16) / 1e18
        a, b = l1(NATIVE_BYTES), l1(ERC20_BYTES)
        native, stable = native + a, stable + b
        extra = f", L1 data fee up to {a:.2e} ETH"
    return {"native": native, "stable": stable, "unit": "ETH" if key in ("ethereum", "base") else EVM[key][1],
            "detail": f"gas price {price / 1e9:.3g} gwei{extra}"}


def solana():
    url = "https://api.mainnet-beta.solana.com"
    fees = [f["prioritizationFee"] for f in rpc(url, "getRecentPrioritizationFees", [])]
    micro = statistics.median(fees) if fees else 0
    lam = lambda cu: 5000 + micro * cu / 1e6  # noqa: E731
    return {"native": lam(450) / 1e9, "stable": lam(6000) / 1e9, "unit": "SOL",
            "detail": f"median priority fee {micro:g} micro-lamports per compute unit"}


def tron():
    p = {x["key"]: x.get("value") for x in get("https://api.trongrid.io/wallet/getchainparameters")["chainParameter"]}
    energy, band = p["getEnergyFee"], p["getTransactionFee"]
    return {"native": 268 * band / 1e6, "stable": 64285 * energy / 1e6, "unit": "TRX",
            "native_note": "free for most senders (600 free bandwidth a day)",
            "stable_note": "if TRX is burned; near zero with staked energy",
            "detail": f"energy {energy} sun, bandwidth {band} sun per byte"}


def bitcoin():
    f = get("https://mempool.space/api/v1/fees/recommended")["halfHourFee"]
    return {"native": f * 141 / 1e8, "stable": None, "unit": "BTC", "detail": f"{f} sat/vB"}


def stellar():
    s = get("https://horizon.stellar.org/fee_stats")
    p = int(s["fee_charged"]["p50"])
    return {"native": p / 1e7, "stable": p / 1e7, "unit": "XLM", "detail": f"{p} stroops"}


def xrpl():
    r = get("https://xrplcluster.com", {"method": "fee", "params": [{}]})["result"]
    d = int(r["drops"]["open_ledger_fee"])
    return {"native": d / 1e6, "stable": d / 1e6, "unit": "XRP", "detail": f"{d} drops"}


FETCH = {"kadena": kadena, "solana": solana, "tron": tron, "bitcoin": bitcoin, "stellar": stellar, "xrpl": xrpl,
         **{k: (lambda k=k: evm(k)) for k in EVM}}


def prices(prev_rows):
    """CoinGecko prices, with two retries; falls back to yesterday's published prices."""
    import time
    ids = ",".join(sorted({c[4] for c in CHAINS}))
    for attempt in range(3):
        try:
            return {k: v["usd"] for k, v in get(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd").items()}, False
        except Exception as e:  # noqa: BLE001
            print(f"build_fees: prices attempt {attempt + 1} failed ({e})", file=sys.stderr)
            time.sleep(30)
    old = {c[4]: prev_rows[c[0]]["price_usd"] for c in CHAINS if c[0] in prev_rows}
    if not old:
        raise RuntimeError("no prices")
    return old, True


# ---------------------------------------------------------------- previous data
def previous():
    """Last published fees.json and history CSV (live site first, then the committed copy)."""
    prev, hist = {}, ""
    try:
        prev = get(LIVE + "fees.json")
    except Exception:  # noqa: BLE001
        try:
            prev = json.load(open(os.path.join(OUT, "fees.json")))
        except (OSError, ValueError):
            pass
    try:
        r = urllib.request.Request(LIVE + "fees-history.csv", headers={"User-Agent": UA})
        hist = urllib.request.urlopen(r, timeout=30).read().decode()
    except Exception:  # noqa: BLE001
        try:
            hist = open(os.path.join(OUT, "fees-history.csv")).read()
        except OSError:
            pass
    return prev, hist


# ---------------------------------------------------------------- formatting
def usd(v):
    """Dollars with two significant figures, written out in full (no scientific notation)."""
    if v is None:
        return "–"
    if v == 0:
        return "$0"
    if v >= 1:
        return f"${v:,.2f}"
    digits = f"{v:.2g}"
    if "e" in digits:
        m, e = digits.split("e")
        places = -int(e) + max(0, len(m.replace(".", "")) - 1)
        return "$" + f"{v:.{places}f}"
    return "$" + digits


def plain(v):
    if v is None:
        return ""
    return f"{v:.10f}".rstrip("0").rstrip(".") if v < 1 else f"{v:.4f}"


def cheaper(a, b):
    """How many times cheaper a is than b, in words."""
    if not a or not b or b <= a:
        return None
    x = b / a
    if x >= 1e6:
        return f"over {x / 1e6:,.0f} million times"
    if x >= 1000:
        return f"about {x / 1000:,.0f} thousand times"
    return f"about {x:,.0f} times"


# ---------------------------------------------------------------- build
def main():
    if os.environ.get("FEES_OFFLINE"):
        print("build_fees: offline, keeping the committed page")
        return
    prev, hist = previous()
    prev_rows = {r["key"]: r for r in prev.get("chains", [])}
    try:
        px, old_prices = prices(prev_rows)
    except Exception as e:  # noqa: BLE001
        print(f"build_fees: prices unavailable ({e}), keeping the published page", file=sys.stderr)
        return
    rows, fresh = [], 0
    for key, name, coin, stable_label, cg, note in CHAINS:
        try:
            d = FETCH[key]()
            price = px[cg]
            row = {"key": key, "name": name, "coin": coin, "stablecoin": stable_label, "price_usd": price,
                   "native_coin": d["native"], "stable_coin": d["stable"],
                   "native_usd": d["native"] * price, "stable_usd": None if d["stable"] is None else d["stable"] * price,
                   "detail": d["detail"], "native_note": d.get("native_note"), "stable_note": d.get("stable_note"),
                   "method": note, "measured": NOW.isoformat().replace("+00:00", "Z"), "stale": False}
            fresh += 1
        except Exception as e:  # noqa: BLE001
            print(f"build_fees: {name} unavailable ({e})", file=sys.stderr)
            if key not in prev_rows:
                continue
            row = dict(prev_rows[key], stale=True)
        rows.append(row)
    if not fresh or not any(r["key"] == "kadena" for r in rows):
        print("build_fees: no fresh data, keeping the published page", file=sys.stderr)
        return

    os.makedirs(OUT, exist_ok=True)
    data = {"updated": NOW.isoformat().replace("+00:00", "Z"), "source": URL, "prices_from_previous_day": old_prices, "chains": rows}
    json.dump(data, open(os.path.join(OUT, "fees.json"), "w"), indent=1)

    # history: one row per chain per day, today's replaced
    fields = ["date", "chain", "native_usd", "stablecoin_usd"]
    old = [r for r in csv.DictReader(io.StringIO(hist))] if hist.startswith("date,") else []
    old = [r for r in old if r["date"] != TODAY.isoformat()]
    new = [{"date": TODAY.isoformat(), "chain": r["key"], "native_usd": plain(r["native_usd"]),
            "stablecoin_usd": plain(r["stable_usd"])} for r in rows if not r["stale"]]
    with open(os.path.join(OUT, "fees-history.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(old + new)

    write_page(rows)
    write_card(rows)
    print(f"build_fees: {fresh}/{len(CHAINS)} chains measured, Kadena transfer {usd(next(r for r in rows if r['key'] == 'kadena')['native_usd'])}")


def write_page(rows):
    esc = html.escape
    by_native = sorted(rows, key=lambda r: r["native_usd"])
    kda = next(r for r in rows if r["key"] == "kadena")
    rank = by_native.index(kda) + 1
    big = [r for r in rows if r["key"] in ("ethereum", "bitcoin", "solana", "tron", "bnb")]
    beats = [r["name"] for r in big if r["native_usd"] > kda["native_usd"]]
    cheaper_eth = cheaper(kda["native_usd"], next((r["native_usd"] for r in rows if r["key"] == "ethereum"), None))

    lead = (f"Today a simple KDA transfer costs {usd(kda['native_usd'])}. That is "
            + ("the lowest" if rank == 1 else f"number {rank}")
            + f" of the {len(rows)} chains below"
            + (f", and cheaper than {', '.join(beats[:-1]) + ' and ' + beats[-1] if len(beats) > 1 else beats[0]}" if beats else "")
            + ".")
    if cheaper_eth:
        lead += f" It is {cheaper_eth} cheaper than the same transfer on Ethereum."

    trs = []
    for r in by_native:
        n = usd(r["native_usd"]) + (f'<small>{esc(r["native_note"])}</small>' if r.get("native_note") else "")
        s = ("–" if r["stable_usd"] is None else usd(r["stable_usd"])) + (f'<small>{esc(r["stable_note"])}</small>' if r.get("stable_note") else "")
        stale = f'<small class="stale">last measured {r["measured"][:10]}</small>' if r.get("stale") else ""
        cls = ' class="kda"' if r["key"] == "kadena" else ""
        trs.append(f'<tr{cls}><th scope="row">{esc(r["name"])}{stale}</th><td>{n}</td>'
                   f'<td>{s}<small>{esc(r["stablecoin"] or "")}</small></td></tr>')
    table = ('<div class="tw"><table class="fees"><thead><tr><th>Chain</th><th>Send the chain\'s coin</th>'
             '<th>Send a stablecoin</th></tr></thead><tbody>' + "".join(trs) + "</tbody></table></div>")

    how = "".join(f'<li><b>{esc(r["name"])}</b>: {esc(r["method"])} Today: {esc(r["detail"])}; '
                  f'{esc(r["coin"])} at ${r["price_usd"]:,.6g}.</li>' for r in rows)

    body = f'''<main id="main" class="policy">
  <article class="wrap">
    <div class="topbar"><p class="crumb"><a href="/">Kadena Nexus</a> / <a href="/research/">Research</a> / Transfer fees</p>
      <p class="upd"><span class="dot" aria-hidden="true"></span><span>Updated {NOW:%b} {NOW.day}, {NOW.year}, {NOW:%H:%M} UTC · daily</span></p></div>
    <h1>What does it cost to send money today?</h1>
    <p class="lede">{lead}</p>
    <p class="meta">The cost of one simple transfer on each chain, in US dollars, measured from public data every day. Cheapest first.</p>
    {table}
    <p class="note">Fees change all the time; these are today's typical values, not quotes. Bridge, exchange and wallet fees are not included. <a class="dl" href="fees.json">Today's data (JSON)</a><a class="dl" href="fees-history.csv">Daily history (CSV)</a></p>

    <h2>Before you compare</h2>
    <ul class="sum">
      <li>Kadena's fees are low partly because KDA's price and network use are low today. In our <a href="/tps/">mainnet stress test (NR-001)</a> fees stayed at the minimum even with every block full, and 20 parallel chains leave room to grow.</li>
      <li>Stellar and the XRP Ledger are also built for very cheap payments, so several chains here cost a tiny fraction of a cent. Kadena is the only proof-of-work chain among them.</li>
      <li>On Tron, a USDT transfer is expensive if the sender burns TRX and nearly free for senders who stake TRX for energy. We show the burned price.</li>
      <li>Transfer sizes are standard estimates. The exact cost depends on the wallet, the token contract and how busy the network is.</li>
    </ul>

    <h2>How each figure is measured</h2>
    <ul class="sum how">{how}</ul>
    <p class="note">Prices in US dollars from CoinGecko. If a source cannot be read, the chain keeps its last value and shows the date it was measured. Questions or corrections: <a href="mailto:Saudi.KDA@kadena.ws">Saudi.KDA@kadena.ws</a>. Nothing here is financial advice.</p>
    <p class="back"><a href="/research/">← Back to Nexus Research</a></p>
  </article>
</main>'''
    css = """.policy .fees td,.policy .fees th{vertical-align:top}
.policy .fees tbody th{text-align:left;font-weight:600;color:var(--sand)}
.policy .fees small{display:block;font-size:.78rem;color:var(--mist);font-weight:400;margin-top:.15rem}
.policy .fees small.stale{color:#B45309}
.policy .fees tr.kda{background:#ECF7F1}
.policy .fees tr.kda th,.policy .fees tr.kda td{color:#17603C;font-weight:700}
.policy .fees td{font-size:1rem}
.policy .how li{font-size:.92rem}
.policy .fees sup{font-size:.7em}"""
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "Dataset", "name": "Daily transfer fees across blockchains", "url": URL,
         "description": "The US dollar cost of one simple transfer on Kadena and nine other chains, measured daily from public data.",
         "creator": br.ORG, "license": "https://creativecommons.org/licenses/by/4.0/",
         "dateModified": TODAY.isoformat(), "distribution": [
             {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": URL + "fees.json"},
             {"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": URL + "fees-history.csv"}]},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Kadena Nexus", "item": "https://kadena.ws/"},
            {"@type": "ListItem", "position": 2, "name": "Nexus Research", "item": "https://kadena.ws/research/"},
            {"@type": "ListItem", "position": 3, "name": "Transfer fees", "item": URL}]}]}
    page = br.shell(SITE, "Transfer fees today: Kadena vs Ethereum, Solana, Bitcoin, Tron and more",
                    f"What one simple transfer costs today in US dollars on Kadena, Ethereum, Base, BNB Chain, Polygon, Solana, Tron, Bitcoin, Stellar and the XRP Ledger. Measured daily from public data.",
                    URL, ld, css, body)
    if os.path.exists(os.path.join(OUT, "card.png")):  # today's table as the link preview
        page = page.replace("https://kadena.ws/og/og-nodes.jpg", URL + "card.png")
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(page)


def write_card(rows):
    """1200x675 image of today's table (for X posts and link previews), rendered with headless Chrome."""
    chrome = next((c for c in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser") if shutil.which(c)), None)
    if not chrome:
        print("build_fees: no Chrome found, card image not updated", file=sys.stderr)
        return
    rows = sorted(rows, key=lambda r: r["native_usd"])
    trs = "".join(
        f'<tr class="{"k" if r["key"] == "kadena" else ""}"><td>{html.escape(r["name"])}</td>'
        f'<td>{usd(r["native_usd"])}</td><td>{"–" if r["stable_usd"] is None else usd(r["stable_usd"]) + ("*" if r["key"] == "tron" else "")}</td></tr>'
        for r in rows)
    card = f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{width:1200px;height:675px;background:#0C1A2B;color:#C5D2DE;font-family:"Inter","Segoe UI","DejaVu Sans",Arial,sans-serif;padding:44px 56px}}
.top{{display:flex;justify-content:space-between;align-items:baseline}}
h1{{color:#fff;font-size:40px;font-weight:700;letter-spacing:-.5px}}
.d{{font-size:22px;color:#8FA5B8}}
p.s{{margin-top:6px;font-size:21px;color:#8FA5B8}}
table{{width:100%;border-collapse:collapse;margin-top:22px;font-size:23px;font-variant-numeric:tabular-nums}}
th{{text-align:right;font-size:17px;font-weight:600;color:#8FA5B8;text-transform:uppercase;letter-spacing:.06em;padding:0 14px 8px}}
th:first-child,td:first-child{{text-align:left}}
td{{text-align:right;padding:7px 14px;border-top:1px solid #22384F;color:#E2E8F0}}
tr.k td{{background:#14463A;color:#34D399;font-weight:700}}
.f{{position:absolute;left:56px;right:56px;bottom:30px;display:flex;justify-content:space-between;font-size:18px;color:#8FA5B8}}
.f b{{color:#fff}}
</style></head><body>
<div class="top"><h1>What one transfer costs today</h1><span class="d">{NOW:%b} {NOW.day}, {NOW.year}</span></div>
<p class="s">US dollars, cheapest first. Measured from public data.</p>
<table><thead><tr><th>Chain</th><th>Send the coin</th><th>Send a stablecoin</th></tr></thead><tbody>{trs}</tbody></table>
<div class="f"><span><b>Kadena Nexus Research</b> · kadena.ws/research/fees</span><span>* Tron USDT if TRX is burned · Not financial advice</span></div>
</body></html>"""
    src = os.path.join(OUT, ".card.html")
    open(src, "w", encoding="utf-8").write(card)
    png = os.path.join(OUT, "card.png")
    try:
        subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        "--window-size=1200,675", f"--screenshot={png}", "file://" + src],
                       check=True, timeout=90, capture_output=True)
    except Exception as e:  # noqa: BLE001
        print(f"build_fees: card image failed ({e})", file=sys.stderr)
    finally:
        os.remove(src)


if __name__ == "__main__":
    main()
