"""Interactive Amazon sign-in that saves cookies for the MCP server.

Used by the `refresh_session` tool and by cookie_capture.py, so the sign-in
logic lives in one place. The browser, clock, and cookie path can be injected
so tests run without opening Amazon.
"""

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from amazon_orders_mcp.secure_session import COOKIE_JAR_PATH

# Cookie that amazon-orders uses to detect an authenticated session
REQUIRED_COOKIE = "x-main"

SIGN_IN_URL = (
    "https://www.amazon.com/ap/signin?openid.pape.max_auth_age=900"
    "&openid.return_to=https%3A%2F%2Fwww.amazon.com%2Fgp%2Fyour-account%2Forder-history"
    "&openid.assoc_handle=usflex&openid.mode=checkid_setup"
    "&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0"
)
SIGNED_IN_LANDING_URL = "https://www.amazon.com/gp/your-account/order-history"


def _amazon_cookies(cookies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [c for c in cookies if c.get("domain") and "amazon.com" in c["domain"]]


def _result(ok: bool, message: str, **extra: Any) -> Dict[str, Any]:
    return {"ok": ok, "message": message, **extra}


def capture_session(
    timeout_seconds: int = 300,
    poll_interval: float = 2,
    jar_path: Path = COOKIE_JAR_PATH,
    playwright_factory: Callable[[], Any] = sync_playwright,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """Open a visible browser, wait for sign-in, and save Amazon cookies.

    Returns a dict with `ok` and `message`. On success it also has
    `cookie_count` and `path`. Nothing is written unless sign-in completes.
    """
    with playwright_factory() as p:
        browser = p.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(SIGN_IN_URL)

            elapsed = 0.0
            while True:
                try:
                    cookies = _amazon_cookies(context.cookies())
                except PlaywrightError:
                    return _result(False, "The browser window was closed before sign-in completed.")
                if any(c["name"] == REQUIRED_COOKIE for c in cookies):
                    break
                if elapsed >= timeout_seconds:
                    return _result(
                        False,
                        f"Timed out after {timeout_seconds} seconds waiting for sign-in.",
                    )
                sleep(poll_interval)
                elapsed += poll_interval

            # Let post-login cookies settle, then visit the order history once
            sleep(2)
            try:
                page.goto(SIGNED_IN_LANDING_URL, timeout=15000)
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass  # keep the cookies captured so far

            flat = {c["name"]: c["value"] for c in _amazon_cookies(context.cookies())}
        finally:
            try:
                browser.close()
            except PlaywrightError:
                pass  # already closed by the user

    jar_path.parent.mkdir(parents=True, exist_ok=True)
    jar_path.write_text(json.dumps(flat))
    try:
        jar_path.chmod(0o600)
    except OSError:
        pass  # Windows ignores POSIX modes
    return _result(
        True,
        f"Saved {len(flat)} Amazon cookies to {jar_path}.",
        cookie_count=len(flat),
        path=str(jar_path),
    )
