"""Save order summaries as PDFs, with a standard name.

The caller names the output folder. The tools never pick a location and never
overwrite an existing file. The file name is
<YYYY-MM-DD>_<order_id>_Invoice.pdf, built from the order date on the page.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List

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


def _check_inputs(order_ids: List[str], output_dir: Path) -> None:
    for order_id in order_ids:
        if not ORDER_ID_RE.match(order_id):
            raise ValueError(f"Not an Amazon order number: {order_id!r}")
    if not output_dir.is_dir():
        raise ValueError(f"Output folder does not exist: {output_dir}")


def _save_one(page: Any, order_id: str, output_dir: Path) -> Path:
    """Open one summary page and save it. Raises FileExistsError if already saved."""
    url = PRINT_URL.format(order_id=order_id)
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
    page.pdf(path=str(target), format="Letter", print_background=False)
    return target


def _open_page(p: Any, jar_path: Path) -> Any:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    context.add_cookies(browser_cookies(jar_path))
    return browser, context.new_page()


def save_order_invoice_pdf(
    order_id: str,
    output_dir: Path,
    jar_path: Path = COOKIE_JAR_PATH,
    playwright_factory: Callable[[], Any] = sync_playwright,
) -> Path:
    """Save one order's summary as a PDF in output_dir and return its path."""
    output_dir = Path(output_dir)
    _check_inputs([order_id], output_dir)
    with playwright_factory() as p:
        browser, page = _open_page(p, jar_path)
        try:
            return _save_one(page, order_id, output_dir)
        finally:
            browser.close()


def save_order_invoices(
    order_ids: List[str],
    output_dir: Path,
    jar_path: Path = COOKIE_JAR_PATH,
    playwright_factory: Callable[[], Any] = sync_playwright,
) -> List[Dict[str, Any]]:
    """Save many orders in one browser session.

    Each result is {order_id, status, path, message}, where status is "saved",
    "skipped" (a file with that name already exists), or "error". One bad order
    does not stop the batch. An expired session does: NonInteractiveAuthRequired
    is raised, and the files saved so far stay in output_dir.
    """
    output_dir = Path(output_dir)
    order_ids = list(dict.fromkeys(order_ids))  # drop repeats, keep order
    _check_inputs(order_ids, output_dir)
    results: List[Dict[str, Any]] = []
    with playwright_factory() as p:
        browser, page = _open_page(p, jar_path)
        try:
            for order_id in order_ids:
                try:
                    target = _save_one(page, order_id, output_dir)
                    results.append({"order_id": order_id, "status": "saved", "path": str(target), "message": ""})
                except FileExistsError as e:
                    results.append({"order_id": order_id, "status": "skipped", "path": "", "message": str(e)})
                except NonInteractiveAuthRequired:
                    raise
                except Exception as e:  # keep going; report the order
                    results.append({"order_id": order_id, "status": "error", "path": "", "message": f"{type(e).__name__}: {e}"})
        finally:
            browser.close()
    return results
