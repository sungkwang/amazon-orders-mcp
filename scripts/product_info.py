"""Read Amazon's category path and FSA/HSA label from public product pages, cached by ASIN.

Usage: python scripts/product_info.py [--year 2026] [--data-dir PATH] ASIN [ASIN ...]
Product pages need no sign-in. One page at a time, a half-second apart; stops on a robot check.
The cache is <data folder>/<year>/_app/product_cache.json (asin_info_<year>.json in the older layout) (data folder: --data-dir, HSA_DATA_DIR, or
~/.hsa-review/config.json; never the code folder); each product keeps the date it was read.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

# The badge near the price is the only signal. A link named "FSA Eligible Items" also appears on
# non-eligible Health and Personal care pages (checked), so it is a store link and is ignored.
LABEL = re.compile(r"FSA or HSA eligible", re.I)

parser = argparse.ArgumentParser()
parser.add_argument("--year", default="2026")
parser.add_argument("--data-dir")
parser.add_argument("asins", nargs="+")
args = parser.parse_args()


def find_data_dir(cli):
    config = Path.home() / ".hsa-review" / "config.json"
    try:
        from_config = json.loads(config.read_text(encoding="utf-8")).get("data_dir")
    except (OSError, ValueError):
        from_config = None
    for value in (cli, os.environ.get("HSA_DATA_DIR"), from_config):
        if value and Path(value).expanduser().is_dir():
            return Path(value).expanduser().resolve()
    sys.exit("No data folder set. Run setup (or pass --data-dir).")


ROOT = find_data_dir(args.data_dir)
_year = ROOT / args.year
_legacy = (_year / f"hsa_data_{args.year}.json").exists() and not (_year / "_app" / "data.json").exists()
cache_path = (_year / f"asin_info_{args.year}.json") if _legacy else (_year / "_app" / "product_cache.json")
cache_path.parent.mkdir(parents=True, exist_ok=True)
cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
todo = [a for a in dict.fromkeys(args.asins) if a not in cache]
print(f"{len(todo)} products to read (cached: {len(args.asins) - len(todo)}); about {len(todo) * 5.6 / 60:.1f} min", flush=True)
started = time.time()
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_context().new_page()
    for n, asin in enumerate(todo, 1):
        page.goto(f"https://www.amazon.com/dp/{asin}", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        crumbs = page.evaluate("() => { const e = document.querySelector('#wayfinding-breadcrumbs_feature_div'); return e ? e.innerText : ''; }")
        text = page.evaluate("() => document.body.innerText")
        title = page.evaluate("() => (document.querySelector('#productTitle') || {}).innerText || document.title")
        path = [c.strip() for c in re.split(r"\s*[›>]\s*|\n+", crumbs) if c.strip()]
        label = next((line.strip()[:120] for line in text.splitlines() if LABEL.search(line)), None)
        blocked = "captcha" in page.url.lower() or "robot" in text[:400].lower()
        cache[asin] = {"path": path, "fsa": label, "title": title.strip()[:80], "blocked": blocked, "read": date.today().isoformat()}
        cache_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
        elapsed = time.time() - started
        print(f"{n}/{len(todo)} {asin} {' > '.join(path) or '(no category)'} | {'badge' if label else 'no badge'} | {elapsed:.0f}s elapsed, about {elapsed / n * (len(todo) - n):.0f}s left", flush=True)
        if blocked:
            print("STOP: Amazon showed a robot check.", flush=True)
            break
        time.sleep(0.5)
    browser.close()
