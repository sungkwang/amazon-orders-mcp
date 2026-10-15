"""Fetch Amazon's printable order summary with the saved session.

One read-only page load per order, using the cookies from the saved jar.
If Amazon redirects to sign-in, raise the same error the server maps to the
`refresh_session` tool.
"""

import re
from pathlib import Path
from typing import Any, Callable, Tuple

from playwright.sync_api import sync_playwright

from amazon_orders_mcp.client import NonInteractiveAuthRequired
from amazon_orders_mcp.secure_session import COOKIE_JAR_PATH
from amazon_orders_mcp.session_capture import browser_cookies

ORDER_ID_RE = re.compile(r"^\d{3}-\d{7}-\d{7}$")
PRINT_URL = "https://www.amazon.com/gp/css/summary/print.html?orderID={order_id}"


def fetch_print_page(
    order_id: str,
    jar_path: Path = COOKIE_JAR_PATH,
    playwright_factory: Callable[[], Any] = sync_playwright,
) -> Tuple[str, str]:
    """Return (visible text, HTML) of the printable summary for one order."""
    if not ORDER_ID_RE.match(order_id):
        raise ValueError(f"Not an Amazon order number: {order_id!r}")

    with playwright_factory() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            context.add_cookies(browser_cookies(jar_path))
            page = context.new_page()
            page.goto(PRINT_URL.format(order_id=order_id), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            if "/ap/signin" in page.url:
                raise NonInteractiveAuthRequired(
                    "Amazon redirected to sign-in; the saved session has expired."
                )
            html = page.content()
            text = page.evaluate("() => document.body.innerText")
        finally:
            browser.close()
    return text, html
