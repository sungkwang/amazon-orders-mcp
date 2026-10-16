"""Interactive Amazon sign-in that saves cookies for the MCP server.

Used by the `refresh_session` tool and by cookie_capture.py, so the sign-in
logic lives in one place. The browser, clock, and cookie path can be injected
so tests run without opening Amazon.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from amazon_orders_mcp.browser_profile import launch_context, needs_sign_in, profile_lock, record_sign_in
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


def _keep_signed_in_ticker(page: Any) -> Callable[[], None]:
    """Return a function that ticks "Keep me signed in" once, if the box is on the page.

    Never fills the email or password. If the box is unticked by the user afterwards,
    it is left alone. If the box is not found, a note goes to stderr and sign-in continues.
    """
    state = {"done": False}

    def tick() -> None:
        if state["done"]:
            return
        try:
            box = page.locator('input[name="rememberMe"]')
            if box.count() == 0:
                box = page.get_by_label("Keep me signed in")
            if box.count() == 0:
                return
            state["done"] = True
            if not box.first.is_checked():
                box.first.check()
        except Exception:
            pass  # the page may be mid-navigation; the next page load tries again

    try:
        page.on("framenavigated", lambda frame: tick())
    except Exception:
        pass
    tick.state = state  # type: ignore[attr-defined]
    return tick


def _on_order_history(page: Any) -> bool:
    url = str(getattr(page, "url", ""))
    return "order-history" in url and not needs_sign_in(url)


def capture_session(
    timeout_seconds: int = 300,
    poll_interval: float = 2,
    jar_path: Path = COOKIE_JAR_PATH,
    playwright_factory: Callable[[], Any] = sync_playwright,
    sleep: Callable[[float], None] = time.sleep,
    profile_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Open a visible browser, wait for sign-in, and save Amazon cookies.

    Returns a dict with `ok` and `message`. On success it also has
    `cookie_count` and `path`. Nothing is written unless sign-in completes.
    """
    with playwright_factory() as p, profile_lock():
        context = launch_context(p, headless=False, profile_dir=profile_dir)
        try:
            page = context.new_page()
            tick = _keep_signed_in_ticker(page)
            # Start at the order history: Amazon asks for a fresh sign-in there even when old cookies exist.
            # The window is done only when that page really opens, not when a cookie shows up.
            page.goto(SIGNED_IN_LANDING_URL)
            tick()

            elapsed = 0.0
            while True:
                try:
                    cookies = _amazon_cookies(context.cookies())
                except PlaywrightError:
                    return _result(False, "The browser window was closed before sign-in completed.")
                if any(c["name"] == REQUIRED_COOKIE for c in cookies) and _on_order_history(page):
                    break
                if elapsed >= timeout_seconds:
                    return _result(
                        False,
                        f"Timed out after {timeout_seconds} seconds waiting for sign-in.",
                    )
                sleep(poll_interval)
                elapsed += poll_interval
                tick()

            if not tick.state["done"]:  # type: ignore[attr-defined]
                print('Note: the "Keep me signed in" box was not found; sign-in continued without it.', file=sys.stderr)

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
                context.close()
            except PlaywrightError:
                pass  # already closed by the user

    jar_path.parent.mkdir(parents=True, exist_ok=True)
    # Write a temp file, then swap it in, so an interrupted write never leaves a truncated jar
    tmp_path = jar_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(flat))
    try:
        tmp_path.chmod(0o600)
    except OSError:
        pass  # Windows ignores POSIX modes
    os.replace(tmp_path, jar_path)
    record_sign_in()
    return _result(
        True,
        f"Saved {len(flat)} Amazon cookies to {jar_path}.",
        cookie_count=len(flat),
        path=str(jar_path),
    )


def browser_cookies(jar_path: Path = COOKIE_JAR_PATH) -> List[Dict[str, Any]]:
    """Convert the saved flat cookie jar into cookies a browser context accepts.

    The jar keeps only names and values, so the Amazon domain, path, and secure
    flag are added back here.
    """
    flat = json.loads(jar_path.read_text())
    return [
        {"name": name, "value": value, "domain": ".amazon.com", "path": "/", "secure": True}
        for name, value in flat.items()
    ]
