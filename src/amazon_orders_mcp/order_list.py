"""List one year of Amazon orders from the order-history pages.

Text-based, like tools/list-orders: each order on the page is a block that
starts with "ORDER PLACED". Item titles are the lines just before the action
links that follow them ("Buy it again", "Track package", ...).
"""

import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import sync_playwright

from amazon_orders_mcp.client import NonInteractiveAuthRequired
from amazon_orders_mcp.secure_session import COOKIE_JAR_PATH
from amazon_orders_mcp.session_capture import browser_cookies

ORDER_NUMBER_RE = re.compile(r"ORDER #\s*(\d{3}-\d{7}-\d{7})", re.IGNORECASE)
DATE_RE = re.compile(r"^([A-Z][a-z]+ \d{1,2}, \d{4})$")
MONEY_RE = re.compile(r"^\$[\d,]+\.\d{2}$")
# Action links and status lines are never item titles, even when another link follows them
NON_TITLE_RE = re.compile(
    r"^(Track package|View or edit order|Return or replace items|Write a product review|"
    r"Buy it again|Ask Product Question|Get product support|View your item|View order details|"
    r"View invoice|Ask Alexa|Leave seller feedback|Archive order|View return|Auto-delivered|"
    r"Arriving|Delivered|Return window|Return complete|Refund|Sold by:|Supplied by:)",
    re.IGNORECASE,
)
ITEM_ACTIONS = (
    "Buy it again",
    "Track package",
    "View or edit order",
    "Ask Product Question",
    "Write a product review",
    "Get product support",
    "View your item",
)
PAGE_URL = "https://www.amazon.com/your-orders/orders?timeFilter=year-{year}&startIndex={start}"
PAGE_SIZE = 10
MAX_PAGES = 100


def _order_blocks(text: str) -> List[List[str]]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    blocks: List[List[str]] = []
    for line in lines:
        if line == "ORDER PLACED":
            blocks.append([])
        elif blocks:
            blocks[-1].append(line)
    return blocks


def _parse_block(block: List[str]) -> Dict[str, Any]:
    order_id = None
    order_date = None
    total = None
    titles: List[str] = []
    for i, line in enumerate(block):
        number = ORDER_NUMBER_RE.search(line)
        if order_id is None and number:
            order_id = number.group(1)
        if order_date is None and DATE_RE.match(line):
            order_date = line
        if total is None and line == "TOTAL" and i + 1 < len(block) and MONEY_RE.match(block[i + 1]):
            total = block[i + 1]
        nxt = block[i + 1] if i + 1 < len(block) else ""
        if nxt.startswith(ITEM_ACTIONS) or nxt.startswith("Sold by:"):
            if line not in titles and len(line) > 12 and not NON_TITLE_RE.match(line):
                titles.append(line)
    return {"order_id": order_id, "order_date": order_date, "total": total, "item_titles": titles}


def parse_order_list_text(text: str) -> List[Dict[str, Any]]:
    """Return one dict per order block in a single page of order-history text."""
    orders = [_parse_block(b) for b in _order_blocks(text)]
    return [o for o in orders if o["order_id"]]


def list_orders_for_year(
    year: int,
    jar_path: Path = COOKIE_JAR_PATH,
    playwright_factory: Callable[[], Any] = sync_playwright,
    on_page: Optional[Callable[[int, int, float], None]] = None,
) -> List[Dict[str, Any]]:
    """Page through one year of orders until a page adds nothing new.

    `on_page(page_number, orders_so_far, seconds_elapsed)` is called after each
    page, so a caller can show progress.
    """
    seen = set()
    orders: List[Dict[str, Any]] = []
    started = time.monotonic()
    with playwright_factory() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            context.add_cookies(browser_cookies(jar_path))
            page = context.new_page()
            for page_index in range(MAX_PAGES):
                start = page_index * PAGE_SIZE
                page.goto(PAGE_URL.format(year=year, start=start), wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)
                if "/ap/signin" in page.url:
                    raise NonInteractiveAuthRequired("Amazon redirected to sign-in; the saved session has expired.")
                found = parse_order_list_text(page.evaluate("() => document.body.innerText"))
                new = [o for o in found if o["order_id"] not in seen]
                if not new:
                    break
                for o in new:
                    seen.add(o["order_id"])
                    orders.append(o)
                if on_page:
                    on_page(page_index + 1, len(orders), time.monotonic() - started)
        finally:
            browser.close()
    return orders


def _order_date(text: Optional[str]):
    from datetime import datetime

    return datetime.strptime(text, "%B %d, %Y").date() if text else None


def _order_amount(text: Optional[str]) -> Optional[float]:
    return float(text.lstrip("$").replace(",", "")) if text else None


def match_orders_by_amount(
    orders: List[Dict[str, Any]],
    queries: List[Dict[str, Any]],
    tolerance: float = 0.01,
) -> List[Dict[str, Any]]:
    """Find orders whose total matches each query's amount near its date.

    Each query has `date` (a date), `amount` (a number, sign ignored),
    `window_days` (int), and optional extra fields that are echoed back.
    Order dates are the day the order was placed, so the window should allow
    for the gap between ordering and charging.
    """
    results = []
    for q in queries:
        matches = []
        for order in orders:
            placed = _order_date(order.get("order_date"))
            total = _order_amount(order.get("total"))
            if placed is None or total is None:
                continue
            offset = (placed - q["date"]).days
            if abs(offset) <= q["window_days"] and abs(total - abs(q["amount"])) <= tolerance:
                matches.append({"date_offset_days": offset, **order})
        results.append({"query": q, "match_count": len(matches), "matches": matches})
    return results
