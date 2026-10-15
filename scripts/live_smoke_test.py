#!/usr/bin/env python3
"""
Manual live check against Amazon. NOT run by pytest (the name has no test_ prefix).

Makes a small, fixed set of real requests so you can confirm the parsers still
match Amazon's current pages:
  1. list one year of orders (a few pages)
  2. get one known order's printable summary
  3. check one ASIN's "FSA or HSA eligible" label on its public product page

Run only with explicit approval, from the repo root:
    python scripts/live_smoke_test.py --year 2026 --order 111-0000000-0000000 --asin B000000000
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from amazon_orders_mcp.client import NonInteractiveAuthRequired  # noqa: E402
from amazon_orders_mcp.errors import ParseStructureError  # noqa: E402
from amazon_orders_mcp.order_list import list_orders_for_year  # noqa: E402
from amazon_orders_mcp.print_fetch import fetch_print_page  # noqa: E402
from amazon_orders_mcp.print_parser import parse_print_page, validate_order_summary  # noqa: E402
from amazon_orders_mcp.product_check import check_product_eligibility  # noqa: E402
from amazon_orders_mcp.secure_session import COOKIE_JAR_PATH  # noqa: E402


def check(label, fn):
    try:
        ok, detail = fn()
    except NonInteractiveAuthRequired as e:
        ok, detail = False, f"session expired: {e} (run refresh_session or cookie_capture.py)"
    except ParseStructureError as e:
        ok, detail = False, f"page layout changed at {e.url}: {e.snippet}"
    except Exception as e:  # noqa: BLE001 - a smoke test reports every failure
        ok, detail = False, f"{type(e).__name__}: {e}"
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--order", required=True, help="One known order number to read")
    parser.add_argument("--asin", required=True, help="One ASIN to check for FSA/HSA eligibility")
    args = parser.parse_args()

    results = []

    def list_year():
        result = list_orders_for_year(args.year, jar_path=COOKIE_JAR_PATH, playwright_factory=sync_playwright)
        titles = sum(len(o["item_titles"]) for o in result["orders"])
        detail = f"{len(result['orders'])} orders, {titles} item titles, truncated={result['truncated']}"
        return bool(result["orders"]) and not result["truncated"], detail

    def read_order():
        text, html = fetch_print_page(args.order, COOKIE_JAR_PATH, sync_playwright)
        parsed = parse_print_page(text, html)
        validate_order_summary(parsed, f"order {args.order}", text)
        return True, f"{len(parsed['items'])} items, grand total {parsed['grand_total']}"

    def check_asin():
        result = check_product_eligibility(args.asin, sync_playwright, today=None)
        return True, f"fsa_hsa_eligible={result['fsa_hsa_eligible']}, matched={result['matched_text']!r}"

    results.append(check(f"list orders for {args.year}", list_year))
    results.append(check(f"read order {args.order}", read_order))
    results.append(check(f"eligibility for {args.asin}", check_asin))

    print("\nAll checks passed." if all(results) else "\nSome checks failed. Nothing was saved except what the checks printed.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
