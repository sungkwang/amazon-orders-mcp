"""Check a public Amazon product page for the "FSA or HSA eligible" label.

Read-only. Uses a fresh browser context with no cookies, so it never touches
the signed-in session. One page load per call; callers pass only candidates.
"""

import re
from datetime import date
from typing import Any, Callable, Dict, Optional

from playwright.sync_api import sync_playwright

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
LABEL_RE = re.compile(r"FSA or HSA eligible", re.IGNORECASE)
PRODUCT_URL = "https://www.amazon.com/dp/{asin}"


def check_product_eligibility(
    asin: str,
    playwright_factory: Callable[[], Any] = sync_playwright,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Return {asin, fsa_hsa_eligible, matched_text, checked_date} for one product."""
    asin = asin.strip().upper()
    if not ASIN_RE.match(asin):
        raise ValueError(f"Not a product ASIN (10 letters or digits): {asin!r}")

    with playwright_factory() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_context().new_page()
            page.goto(PRODUCT_URL.format(asin=asin), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            text = page.evaluate("() => document.body.innerText")
        finally:
            browser.close()

    match = next((line.strip() for line in text.splitlines() if LABEL_RE.search(line)), None)
    return {
        "asin": asin,
        "fsa_hsa_eligible": match is not None,
        "matched_text": match[:200] if match else None,
        "checked_date": (today or date.today()).isoformat(),
    }
