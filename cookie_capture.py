#!/usr/bin/env python3
"""
Cookie capture for the Amazon Orders MCP server (terminal entry point).

The sign-in logic lives in `amazon_orders_mcp.session_capture`, which the
`refresh_session` tool also uses. This script just runs it and then checks
that the saved cookies work.

Why this exists: amazon-orders uses a plain `requests.Session` to log in,
which Amazon's JavaScript-based WAF frequently blocks with a captcha. Cookies
captured from a real browser after sign-in sidestep that challenge.

Run from the repo root:
    python cookie_capture.py
"""

import sys
from pathlib import Path

# Make the package importable when running as a script
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from amazon_orders_mcp.session_capture import capture_session  # noqa: E402


def main() -> int:
    print("\n🛒 Amazon Orders MCP — Cookie Capture")
    print("=" * 45)
    print("A Chromium window will open. Sign in to Amazon there,")
    print("including any 2FA code. Press Ctrl+C to cancel.\n")

    result = capture_session()
    print(result["message"])
    if not result["ok"]:
        print("No cookies were saved. Run the script again to retry.")
        return 1

    from datetime import date

    from amazon_orders_mcp.order_list import list_orders_for_year

    year = date.today().year
    print(f"\n🧪 Testing cookies by listing {year} orders (about 2-3 seconds per page)...")

    def show_progress(page_number, orders_so_far, seconds):
        per_page = seconds / page_number
        print(
            f"   page {page_number}: {orders_so_far} orders so far "
            f"({seconds:.0f}s elapsed, {per_page:.1f}s per page)",
            flush=True,
        )

    try:
        result = list_orders_for_year(year, on_page=show_progress)
        orders = result["orders"]
        print(f"✅ Found {len(orders)} orders for {year}")
    except Exception as e:
        print(f"⚠️  Test fetch failed: {type(e).__name__}: {e}")
        print("   Cookies were saved but may not be valid.")
        return 1

    print("\n🎉 Cookie capture complete. The MCP server is ready to use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
