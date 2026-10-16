"""Fetch Amazon's printable order summary with the persistent browser profile.

One read-only page load per order, one order at a time. `fetch_print_pages` opens
the profile once for a whole approved batch. If Amazon shows a sign-in or
verification page, raise NonInteractiveAuthRequired (the server maps it to the
`refresh_session` tool); orders already fetched stay in the returned dict.
"""

import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from playwright.sync_api import sync_playwright

from amazon_orders_mcp.browser_profile import batch_context, batch_warning, describe_sign_in, needs_sign_in, sign_in_minutes_left
from amazon_orders_mcp.client import NonInteractiveAuthRequired
from amazon_orders_mcp.secure_session import COOKIE_JAR_PATH

ORDER_ID_RE = re.compile(r"^\d{3}-\d{7}-\d{7}$")
PRINT_URL = "https://www.amazon.com/gp/css/summary/print.html?orderID={order_id}"
SIGN_IN_MESSAGE = "Amazon is asking for sign-in or verification; sign in needed."


def _load(page: Any, order_id: str) -> Tuple[str, str]:
    page.goto(PRINT_URL.format(order_id=order_id), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    if needs_sign_in(page.url):
        raise NonInteractiveAuthRequired(f"{SIGN_IN_MESSAGE} ({describe_sign_in(page.url)})")
    return page.evaluate("() => document.body.innerText"), page.content()


def fetch_print_pages(
    order_ids: List[str],
    on_result: Callable[[str, str, str], None],
    jar_path: Path = COOKIE_JAR_PATH,
    playwright_factory: Callable[[], Any] = sync_playwright,
    pause: Callable[[], None] = lambda: None,
    warn: Callable[[str], None] = lambda message: print("WARNING:", message, file=sys.stderr),
) -> None:
    """Fetch many orders in one browser session, one at a time.

    `on_result(order_id, text, html)` runs after each order. A sign-in page raises
    NonInteractiveAuthRequired before that order is reported, so the caller resumes
    from it after signing in. Anything else per order is the caller's to handle.
    """
    for order_id in order_ids:
        if not ORDER_ID_RE.match(order_id):
            raise ValueError(f"Not an Amazon order number: {order_id!r}")
    message = batch_warning(len(order_ids), sign_in_minutes_left())
    if message:
        warn(message)
    with playwright_factory() as p:
        with batch_context(p, jar_path) as context:
            page = context.new_page()
            for order_id in order_ids:
                text, html = _load(page, order_id)
                on_result(order_id, text, html)
                pause()


def fetch_print_page(
    order_id: str,
    jar_path: Path = COOKIE_JAR_PATH,
    playwright_factory: Callable[[], Any] = sync_playwright,
) -> Tuple[str, str]:
    """Return (visible text, HTML) of the printable summary for one order."""
    found: Dict[str, Tuple[str, str]] = {}
    fetch_print_pages([order_id], lambda oid, t, h: found.update({oid: (t, h)}), jar_path, playwright_factory)
    return found[order_id]
