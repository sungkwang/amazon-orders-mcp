"""Save an order's printable summary as a PDF, with a standard name.

The caller names the output folder. The tool never picks a location, and it
never overwrites an existing file. The file name is
<YYYY-MM-DD>_<order_id>_Invoice.pdf, built from the order date on the page.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import sync_playwright

from amazon_orders_mcp.client import NonInteractiveAuthRequired
from amazon_orders_mcp.errors import ParseStructureError, snippet_of
from amazon_orders_mcp.print_fetch import PRINT_URL, ORDER_ID_RE
from amazon_orders_mcp.print_parser import parse_print_text
from amazon_orders_mcp.secure_session import COOKIE_JAR_PATH
from amazon_orders_mcp.session_capture import browser_cookies


def invoice_filename(order_date: str, order_id: str) -> str:
    """Build the standard file name from the page's order date, e.g. "January 1, 2026"."""
    if not ORDER_ID_RE.match(order_id):
        raise ValueError(f"Not an Amazon order number: {order_id!r}")
    try:
        day = datetime.strptime(order_date, "%B %d, %Y").date()
    except ValueError as e:
        raise ValueError(f"Not an order date: {order_date!r}") from e
    return f"{day.isoformat()}_{order_id}_Invoice.pdf"


def save_order_invoice_pdf(
    order_id: str,
    output_dir: Path,
    jar_path: Path = COOKIE_JAR_PATH,
    playwright_factory: Callable[[], Any] = sync_playwright,
) -> Path:
    """Render the printable summary to a PDF in output_dir and return its path."""
    if not ORDER_ID_RE.match(order_id):
        raise ValueError(f"Not an Amazon order number: {order_id!r}")
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        raise ValueError(f"Output folder does not exist: {output_dir}")

    url = PRINT_URL.format(order_id=order_id)
    with playwright_factory() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            context.add_cookies(browser_cookies(jar_path))
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            if "/ap/signin" in page.url:
                raise NonInteractiveAuthRequired("Amazon redirected to sign-in; the saved session has expired.")
            text = page.evaluate("() => document.body.innerText")
            order_date = parse_print_text(text)["order_date"]
            if not order_date:
                raise ParseStructureError("No order date on the summary page.", url=url, snippet=snippet_of(text))

            target = output_dir / invoice_filename(order_date, order_id)
            if target.exists():
                raise FileExistsError(f"Already saved, not overwritten: {target}")
            page.pdf(path=str(target), format="Letter", print_background=True)
        finally:
            browser.close()
    return target
