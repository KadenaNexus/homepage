#!/usr/bin/env python3
"""Put the Receipt Proof verifier on kadena.ws/proof/.

    python3 scripts/proof/publish.py <verifier.html> <receipt_proof.py>

The verifier is built elsewhere as one HTML file with its list of registry
contracts inside (build.py of Receipt Proof, address https://kadena.ws/proof/).
This adds only what the site needs in <head>: canonical address, preview
tags and structured data. Nothing in the page's body or scripts changes.
receipt_proof.py, the same check as a script, is published beside it."""
import json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "site", "proof")
URL = "https://kadena.ws/proof/"
DESCRIPTION = ("Check that a file matches the version recorded on Kadena, and when. "
               "Runs in your browser; the file is not uploaded.")

HEAD = f"""<link rel="canonical" href="{URL}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Kadena Nexus">
<meta property="og:title" content="Receipt Proof verifier">
<meta property="og:description" content="{DESCRIPTION}">
<meta property="og:url" content="{URL}">
<meta property="og:image" content="https://kadena.ws/og/og-home.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@KadenaNexus">
<script type="application/ld+json">{json.dumps({
    "@context": "https://schema.org", "@type": "WebApplication", "name": "Receipt Proof verifier",
    "url": URL, "description": DESCRIPTION, "applicationCategory": "UtilitiesApplication",
    "operatingSystem": "Any", "isAccessibleForFree": True,
    "publisher": {"@type": "Organization", "name": "Kadena Nexus", "url": "https://kadena.ws/"}})}</script>
"""


def main(page_path, script_path):
    page = open(page_path, encoding="utf-8").read()
    if 'const HOME = "https://kadena.ws/proof/"' not in page or "const DEPLOYMENTS = [];" in page:
        raise SystemExit("Build the verifier with its list of contracts and the address https://kadena.ws/proof/.")
    if 'rel="canonical"' in page or page.count("</head>") != 1:
        raise SystemExit("Not a fresh build of the verifier.")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(page.replace("</head>", HEAD + "</head>"))
    shutil.copyfile(script_path, os.path.join(OUT, "receipt_proof.py"))
    print("wrote site/proof/index.html and site/proof/receipt_proof.py")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
