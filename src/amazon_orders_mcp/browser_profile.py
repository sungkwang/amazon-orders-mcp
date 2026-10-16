"""One persistent Chromium profile shared by sign-in and every Amazon reader.

Sign-in and reading use the same browser and settings, so Amazon sees one steady
browser that keeps its own cookies. A single lock means only one browser uses the
profile at a time. Open it once per approved batch and run requests one at a time.
"""

import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import parse_qs, urlsplit

from amazon_orders_mcp.secure_session import COOKIE_JAR_PATH

PROFILE_DIR = COOKIE_JAR_PATH.parent / "profile"
LOCK_PATH = COOKIE_JAR_PATH.parent / "profile.lock"
LOCK_WAIT_SECONDS = 60

# Pages that mean "you must sign in or verify" rather than "this order failed"
SIGN_IN_MARKERS = ("/ap/signin", "/ap/mfa", "/ap/cvf", "/ap/challenge", "/ap/forgotpassword", "/errors/validateCaptcha")

_thread_lock = threading.Lock()


SIGN_IN_FILE = COOKIE_JAR_PATH.parent / "last_sign_in.txt"
SIGN_IN_VALID_SECONDS = 3600  # Amazon asks for a sign-in from the last hour on order pages (max_auth_age=3600)
SECONDS_PER_ORDER_PAGE = 3.6


def record_sign_in(now: Optional[float] = None, path: Optional[Path] = None) -> None:
    """Remember when the user last signed in."""
    path = path or SIGN_IN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(now if now is not None else time.time()))


def sign_in_minutes_left(now: Optional[float] = None, path: Optional[Path] = None) -> Optional[float]:
    """Minutes left in the one-hour sign-in window, or None if no sign-in was recorded."""
    path = path or SIGN_IN_FILE
    try:
        signed = float(path.read_text())
    except (OSError, ValueError):
        return None
    left = SIGN_IN_VALID_SECONDS - ((now if now is not None else time.time()) - signed)
    return max(left, 0) / 60


def batch_warning(pages: int, minutes_left: Optional[float]) -> Optional[str]:
    """A warning if an order-page batch may outlast the sign-in; None when it should fit."""
    eta = pages * SECONDS_PER_ORDER_PAGE / 60
    if minutes_left is None:
        return f"No sign-in time on record. This batch needs about {eta:.1f} min; sign in first if it stops."
    if minutes_left < 10 or minutes_left < eta:
        return f"Only {minutes_left:.0f} min left in the sign-in hour; this batch needs about {eta:.1f} min. Sign in again first."
    return None


class ProfileBusy(RuntimeError):
    """Another browser is already using the Amazon profile."""


def needs_sign_in(url: str) -> bool:
    return any(m in url for m in SIGN_IN_MARKERS)


def describe_sign_in(url: str) -> str:
    """Safe summary of a sign-in redirect: path, parameter names, and max_auth_age only.

    max_auth_age says how recent a sign-in Amazon requires, so it tells a time rule from a cookie problem.
    No values other than max_auth_age are kept, so no order number or token is logged.
    """
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    age = query.get("openid.pape.max_auth_age") or query.get("max_auth_age")
    return f"path={parts.path}; max_auth_age={age[0] if age else 'absent'}; params={sorted(query)}"


def _restrict_to_user(path: Path) -> None:
    try:
        if os.name == "nt":
            user = os.environ.get("USERNAME", "")
            if user:
                subprocess.run(
                    ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F"],
                    capture_output=True, check=False,
                )
        else:
            path.chmod(0o700)
    except OSError:
        pass  # best effort


def _ensure_profile(profile_dir: Path) -> None:
    fresh = not profile_dir.exists()
    profile_dir.mkdir(parents=True, exist_ok=True)
    if fresh:
        _restrict_to_user(profile_dir)


def _try_lock(handle: Any) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle: Any) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def profile_lock(lock_path: Optional[Path] = None, wait_seconds: float = LOCK_WAIT_SECONDS) -> Iterator[None]:
    """Hold the profile for one batch. Waits, then raises ProfileBusy."""
    lock_path = lock_path or LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait_seconds
    if not _thread_lock.acquire(timeout=wait_seconds):
        raise ProfileBusy("Another request in this program is using the Amazon browser profile.")
    handle = open(lock_path, "a+")
    try:
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                raise ProfileBusy("Another program is using the Amazon browser profile. Close it and try again.")
            time.sleep(0.5)
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()
        _thread_lock.release()


def launch_context(p: Any, headless: bool, profile_dir: Optional[Path] = None) -> Any:
    """Open the persistent profile. Same options for sign-in and reading."""
    profile_dir = profile_dir or PROFILE_DIR
    _ensure_profile(profile_dir)
    return p.chromium.launch_persistent_context(
        str(profile_dir),
        channel="chromium",
        headless=headless,
        viewport={"width": 1280, "height": 900},
    )


def amazon_cookies(context: Any) -> List[Dict[str, Any]]:
    return [c for c in context.cookies() if c.get("domain") and "amazon.com" in c["domain"]]


def save_cookies(context: Any, jar_path: Path = COOKIE_JAR_PATH) -> None:
    """Write Amazon's refreshed cookies back to the flat jar the other readers use."""
    flat = {c["name"]: c["value"] for c in amazon_cookies(context)}
    if "x-main" not in flat:
        return  # not signed in; keep the last good jar
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = jar_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(flat))
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    os.replace(tmp, jar_path)


@contextmanager
def batch_context(
    p: Any,
    jar_path: Path = COOKIE_JAR_PATH,
    profile_dir: Optional[Path] = None,
    lock_path: Optional[Path] = None,
) -> Iterator[Any]:
    """Lock the profile, open it headless once, and yield the browser context.

    On exit the refreshed cookies are saved back and the browser is closed.
    """
    with profile_lock(lock_path):
        context = launch_context(p, headless=True, profile_dir=profile_dir)
        try:
            yield context
        finally:
            try:
                save_cookies(context, jar_path)
            except Exception:
                pass  # the browser may already be gone
            try:
                context.close()
            except Exception:
                pass
