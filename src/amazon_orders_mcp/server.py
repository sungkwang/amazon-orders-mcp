"""Amazon Orders MCP Server — main server implementation.

Exposes Amazon.com personal order history and payment transactions as MCP tools
by wrapping the `amazon-orders` Python library.

All tools that perform network I/O are `async def` and dispatch their blocking
work to a worker thread via `asyncio.to_thread()`. Each tool is additionally
wrapped in `asyncio.wait_for()` with a wall-clock timeout, so a single stuck
Amazon request can never freeze the MCP server's event loop.
"""

import asyncio
import json
import logging
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, cast

import truststore

truststore.inject_into_ssl()  # use the Windows certificate store (corporate/AV proxies)

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from amazon_orders_mcp.client import NonInteractiveAuthRequired
from amazon_orders_mcp.secure_session import cookie_jar_exists, load_credentials
from amazon_orders_mcp.session_capture import capture_session
from amazon_orders_mcp.errors import ParseStructureError
from amazon_orders_mcp.print_fetch import PRINT_URL, fetch_print_page
from amazon_orders_mcp.print_parser import parse_print_page, validate_order_summary
from amazon_orders_mcp.order_list import list_orders_for_year, match_orders_by_amount
from amazon_orders_mcp.product_check import check_product_eligibility


class TransactionQuery(BaseModel):
    """A single external-transaction lookup request for `match_transactions_by_amount`.

    Extra fields on the input dict are preserved and echoed back in the response,
    so callers can round-trip their own metadata (e.g. account name, memo).
    """

    model_config = ConfigDict(extra="allow")

    date: date
    amount: float
    window_days: int = Field(default=3, ge=0, le=30)
    id: Optional[str] = None


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

mcp = MCPServer("Amazon Orders MCP Server")

# Wall-clock timeouts per tool (seconds). These are an upper bound — actual
# requests are also capped at DEFAULT_HTTP_TIMEOUT (see client.py). These
# hard timeouts ensure the MCP event loop stays responsive even if something
# goes wrong at a lower layer.
TIMEOUT_SINGLE_CALL = 60.0  # one Amazon page load
TIMEOUT_PAGED_CALL = 300.0  # multi-page fetches (order history, transactions)


def _json(data: Any) -> str:
    """JSON-serialize a payload for MCP return values."""
    return json.dumps(data, indent=2, default=str)


def _error(message: str, **extra: Any) -> str:
    payload: Dict[str, Any] = {"error": message}
    payload.update(extra)
    return _json(payload)


async def _run_blocking(
    fn: Callable[..., Any],
    *args: Any,
    timeout: float,
    tool_name: str,
    **kwargs: Any,
) -> str:
    """Run a blocking function on a worker thread with a wall-clock timeout.

    The blocking function is dispatched via `asyncio.to_thread()` so it does
    not freeze the MCP server event loop. `asyncio.wait_for` enforces a hard
    upper bound — if the thread doesn't complete in time, we return an error
    JSON payload (the thread may continue running in the background, but it
    will eventually unblock when the HTTP timeout in client.py fires).
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(f"{tool_name} timed out after {timeout}s")
        return _error(
            f"{tool_name} timed out after {timeout} seconds. Amazon may be "
            "rate-limiting or a connection is stuck. Wait a bit and try again.",
            tool=tool_name,
            timeout_seconds=timeout,
        )
    except NonInteractiveAuthRequired as e:
        return _error(
            f"{e} Call the refresh_session tool, sign in, then retry.",
            action_required="refresh_session",
        )
    except ParseStructureError as e:
        logger.warning(f"{tool_name} could not read the page: {e}")
        return _error(str(e), exception_type="ParseStructureError", url=e.url, snippet=e.snippet, tool=tool_name)
    except Exception as e:
        logger.exception(f"{tool_name} failed")
        return _error(f"{tool_name} failed: {e}", exception_type=type(e).__name__)


def _with_auto_refresh(fn: Callable[..., Any]) -> Callable[..., Any]:
    """On an expired session, open the sign-in window once and retry the call.

    Runs on the worker thread. If sign-in does not finish, the original
    NonInteractiveAuthRequired is raised and _run_blocking reports it as before.
    """

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except NonInteractiveAuthRequired:
            logger.info("Amazon session expired; opening the sign-in window")
            if not capture_session(timeout_seconds=REFRESH_TIMEOUT_DEFAULT)["ok"]:
                raise
            return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Auth / status tools
# ---------------------------------------------------------------------------


@mcp.tool()
def setup_authentication() -> str:
    """Get instructions for setting up Amazon authentication."""
    return """🛒 Amazon Orders MCP — Sign-in is required first

Amazon blocks scripted sign-in, so this server uses the session from a real
browser window. Sign in once before the order tools will work.

1️⃣  Call the `refresh_session` tool. A Chromium window opens on Amazon's
    sign-in page.

2️⃣  Sign in as usual, including any 2FA code. The window closes when the
    session is saved to ~/.amazon-orders-mcp/cookies.json.

3️⃣  Then these tools work without another sign-in:
    • get_order_history(year) - orders for one year
    • get_order(order_id) - totals and items for one order
    • match_transactions_by_amount - match bank amounts to orders
    • check_asin_eligibility(asin) - "FSA or HSA eligible" label (no sign-in)

✅ No password is stored; only the session cookies
🔁 If Amazon ends the session, the order tools open the sign-in window once
   and retry automatically. If sign-in isn't finished in about 3 minutes,
   the request fails; try again."""


@mcp.tool()
def check_auth_status() -> str:
    """Check if cookies are stored and usable.

    This tool does not hit Amazon — it only checks local file presence and
    queries the keyring. Safe to call at any time.
    """
    has_cookies = cookie_jar_exists()
    creds = load_credentials()
    has_creds = creds is not None

    status_lines = []

    if has_cookies:
        status_lines.append("✅ Cookie jar exists at ~/.amazon-orders-mcp/cookies.json")
        status_lines.append(
            "   Try `get_order_history(year=2026)` to verify they still work."
        )
    else:
        status_lines.append("❌ No cookie jar found")
        status_lines.append(
            "   Call the `refresh_session` tool to sign in and save a session."
        )

    if has_creds:
        status_lines.append(
            "\nℹ️  Credentials also found in keyring (optional fallback)"
        )

    return "\n".join(status_lines)


REFRESH_TIMEOUT_DEFAULT = 180
REFRESH_TIMEOUT_MIN = 60
REFRESH_TIMEOUT_MAX = 300


def _clamp_refresh_timeout(seconds: int) -> int:
    return max(REFRESH_TIMEOUT_MIN, min(REFRESH_TIMEOUT_MAX, int(seconds)))


def _blocking_refresh_session(timeout_seconds: int) -> str:
    return _json(capture_session(timeout_seconds=timeout_seconds))


@mcp.tool()
async def refresh_session(timeout_seconds: int = REFRESH_TIMEOUT_DEFAULT) -> str:
    """Open a browser window for Amazon sign-in and save fresh cookies.

    Sign in in the window, including any 2-factor step. The tool returns once
    sign-in completes, or after the timeout (60-300 seconds).
    """
    seconds = _clamp_refresh_timeout(timeout_seconds)
    return await _run_blocking(
        _blocking_refresh_session,
        seconds,
        timeout=seconds + 60,
        tool_name="refresh_session",
    )


# ---------------------------------------------------------------------------
# Order tools — each dispatches the blocking work to a worker thread
# ---------------------------------------------------------------------------


def _blocking_get_order_history(
    year: Optional[int],
    time_filter: Optional[str],
    full_details: bool,
    start_index: Optional[int],
) -> str:
    unsupported = [name for name, given in (
        ("time_filter", time_filter is not None),
        ("full_details", full_details),
        ("start_index", start_index is not None),
    ) if given]
    if unsupported:
        return _error(
            f"Not supported yet: {', '.join(unsupported)}. Pass a year only.",
            tool="get_order_history",
        )
    target_year = year or date.today().year
    return _json(list_orders_for_year(target_year))


@mcp.tool()
async def get_order_history(
    year: Optional[int] = None,
    time_filter: Optional[str] = None,
    full_details: bool = False,
    start_index: Optional[int] = None,
) -> str:
    """Fetch Amazon order history.

    Args:
        year: Calendar year to fetch (e.g. 2026). Default: current year if
            neither `year` nor `time_filter` is supplied.
        time_filter: Alternative to `year`. One of: "last30", "months-3",
            "year-YYYY". Cannot be combined with `year`.
        full_details: If True, fetch each order's full detail page (slower).
        start_index: Paging offset into results.

    Returns:
        JSON array of orders: order_id, order_date, total, item_titles.
    """
    return await _run_blocking(
        _with_auto_refresh(_blocking_get_order_history),
        year,
        time_filter,
        full_details,
        start_index,
        timeout=TIMEOUT_PAGED_CALL + REFRESH_TIMEOUT_DEFAULT,
        tool_name="get_order_history",
    )


def _blocking_get_order(order_id: str) -> str:
    text, html = fetch_print_page(order_id)
    parsed = parse_print_page(text, html)
    validate_order_summary(parsed, url=PRINT_URL.format(order_id=order_id), text=text)
    return _json(parsed)


@mcp.tool()
async def get_order(order_id: str) -> str:
    """Fetch full details for a single Amazon order.

    Args:
        order_id: Amazon order number (e.g. "112-1234567-1234567").

    Returns:
        JSON object: order_id, order_date, totals, and items (title, seller, price, refund_status, asin, image_id).
    """
    return await _run_blocking(
        _with_auto_refresh(_blocking_get_order),
        order_id,
        timeout=TIMEOUT_SINGLE_CALL + REFRESH_TIMEOUT_DEFAULT,
        tool_name="get_order",
    )


# ---------------------------------------------------------------------------
# Transaction tools
# ---------------------------------------------------------------------------


def _blocking_match_transactions_by_amount(
    parsed_queries: List[TransactionQuery],
    tolerance: float,
) -> str:
    if not parsed_queries:
        return _json([])
    earliest = min(q.date - timedelta(days=q.window_days) for q in parsed_queries)
    latest = max(q.date + timedelta(days=q.window_days) for q in parsed_queries)
    orders: List[Dict[str, Any]] = []
    for year in sorted({earliest.year, latest.year}):
        orders.extend(list_orders_for_year(year))
    queries = [q.model_dump() for q in parsed_queries]
    return _json(match_orders_by_amount(orders, queries, tolerance))


@mcp.tool()
async def match_transactions_by_amount(
    queries: List[Dict[str, Any]],
    tolerance: float = 0.01,
) -> str:
    """Cross-reference external transactions (e.g. bank/credit card) against Amazon orders.

    Convenience tool for the Monarch-review workflow: given a list of
    {date, amount} pairs, find Amazon transactions that plausibly match.

    Args:
        queries: List of dicts with keys:
            - `date` (str YYYY-MM-DD): external transaction date
            - `amount` (float): external amount as it appears on the bank
              statement — negative for purchases, positive for refunds
            - `id` (str, optional): your own identifier to round-trip
            - `window_days` (int, optional, default 3, max 30): how many
              days of slop to allow around the date when matching
            - Any additional fields are preserved and echoed back in the
              response for round-tripping caller metadata.
        tolerance: Dollar tolerance for amount matches. Default $0.01.

    Returns:
        JSON array of {query, match_count, matches} objects.
    """
    try:
        parsed_queries = [TransactionQuery.model_validate(q) for q in queries]
    except ValidationError as e:
        return _error(
            "Invalid queries payload — each entry needs `date` (YYYY-MM-DD) "
            "and `amount` (number).",
            validation_errors=e.errors(include_url=False),
        )

    return await _run_blocking(
        _with_auto_refresh(_blocking_match_transactions_by_amount),
        parsed_queries,
        tolerance,
        timeout=TIMEOUT_PAGED_CALL + REFRESH_TIMEOUT_DEFAULT,
        tool_name="match_transactions_by_amount",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _blocking_check_asin_eligibility(asin: str) -> str:
    return _json(check_product_eligibility(asin))


@mcp.tool()
async def check_asin_eligibility(asin: str) -> str:
    """Check a public Amazon product page for the FSA or HSA eligible label.

    No sign-in is used; one product page is loaded. Call only for candidate
    items, not for every order.

    Args:
        asin: The product ID (10 letters or digits), from an order's item link.

    Returns:
        JSON object: asin, fsa_hsa_eligible, matched_text, checked_date.
    """
    return await _run_blocking(
        _blocking_check_asin_eligibility,
        asin,
        timeout=TIMEOUT_SINGLE_CALL,
        tool_name="check_asin_eligibility",
    )


def main() -> None:
    """Main entry point for the server."""
    logger.info("Starting Amazon Orders MCP Server...")
    try:
        mcp.run()
    except Exception as e:
        logger.error(f"Failed to run server: {e}")
        raise


# Export for `mcp run`
app = mcp


if __name__ == "__main__":
    main()
