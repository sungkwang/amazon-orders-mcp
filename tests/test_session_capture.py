"""Tests for session_capture.capture_session, using fake browser objects.

No real browser is launched and nothing contacts Amazon.
"""

from tests.conftest import persistent
import json
import sys
from types import SimpleNamespace

import pytest
from playwright.sync_api import Error as PlaywrightError

from amazon_orders_mcp.session_capture import capture_session


class FakeBrowser:
    """Minimal stand-in for the Playwright chain used by capture_session."""

    def __init__(self, cookie_batches):
        self._batches = cookie_batches  # list of cookie lists, one per call
        self._calls = 0
        self.closed = False
        self.page = SimpleNamespace(
            url="https://www.amazon.com/gp/your-account/order-history",
            goto=lambda *a, **k: None,
            wait_for_load_state=lambda *a, **k: None,
        )
        self.context = SimpleNamespace(
            cookies=self._next_cookies,
            new_page=lambda: self.page,
        )

    def _next_cookies(self):
        batch = self._batches[min(self._calls, len(self._batches) - 1)]
        self._calls += 1
        if isinstance(batch, Exception):
            raise batch
        return batch

    def new_context(self):
        return self.context

    def close(self):
        self.closed = True


def fake_playwright_factory(browser):
    """Return a factory whose result works as `with factory() as p:`."""

    class _Playwright:
        def __init__(self):
            self.chromium = SimpleNamespace(launch=lambda **kwargs: browser, launch_persistent_context=persistent(lambda: browser))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return lambda: _Playwright()


def _cookie(name, domain=".amazon.com", value="v"):
    return {"name": name, "domain": domain, "value": value}


def test_success_writes_flat_cookie_jar(tmp_path):
    signed_in = [
        _cookie("x-main", value="main-value"),
        _cookie("session-id", value="sid"),
        _cookie("tracker", domain=".example.com"),
    ]
    browser = FakeBrowser([[], signed_in])
    jar = tmp_path / "cookies.json"

    result = capture_session(
        timeout_seconds=10,
        jar_path=jar,
        playwright_factory=fake_playwright_factory(browser),
        sleep=lambda s: None,
    )

    assert result["ok"] is True
    assert result["cookie_count"] == 2  # only amazon.com cookies are kept
    assert json.loads(jar.read_text()) == {"x-main": "main-value", "session-id": "sid"}
    assert browser.closed is True


def test_timeout_writes_nothing(tmp_path):
    browser = FakeBrowser([[]])  # never signs in
    jar = tmp_path / "cookies.json"
    slept = []

    result = capture_session(
        timeout_seconds=4,
        poll_interval=2,
        jar_path=jar,
        playwright_factory=fake_playwright_factory(browser),
        sleep=slept.append,
    )

    assert result["ok"] is False
    assert "Timed out" in result["message"]
    assert not jar.exists()
    assert sum(slept) == 4  # polled for exactly the timeout
    assert browser.closed is True


def test_browser_closed_returns_failure(tmp_path):
    browser = FakeBrowser([PlaywrightError("Target closed")])
    jar = tmp_path / "cookies.json"

    result = capture_session(
        timeout_seconds=10,
        jar_path=jar,
        playwright_factory=fake_playwright_factory(browser),
        sleep=lambda s: None,
    )

    assert result["ok"] is False
    assert "closed" in result["message"]
    assert not jar.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes are ignored on Windows")
def test_cookie_file_is_private_on_posix(tmp_path):
    browser = FakeBrowser([[_cookie("x-main")]])
    jar = tmp_path / "cookies.json"

    capture_session(
        timeout_seconds=10,
        jar_path=jar,
        playwright_factory=fake_playwright_factory(browser),
        sleep=lambda s: None,
    )

    assert jar.stat().st_mode & 0o777 == 0o600


def test_browser_cookies_adds_domain_path_and_secure(tmp_path):
    from amazon_orders_mcp.session_capture import browser_cookies

    jar = tmp_path / "cookies.json"
    jar.write_text(json.dumps({"x-main": "abc", "session-id": "123"}))

    cookies = browser_cookies(jar)

    assert {c["name"] for c in cookies} == {"x-main", "session-id"}
    for c in cookies:
        assert c["domain"] == ".amazon.com"
        assert c["path"] == "/"
        assert c["secure"] is True


def test_jar_is_replaced_without_leaving_a_temp_file(tmp_path):
    jar = tmp_path / "cookies.json"
    jar.write_text('{"old": "value"}')
    browser = FakeBrowser([[_cookie("x-main", value="new")]])

    capture_session(
        timeout_seconds=10,
        jar_path=jar,
        playwright_factory=fake_playwright_factory(browser),
        sleep=lambda s: None,
    )

    assert json.loads(jar.read_text()) == {"x-main": "new"}
    assert not (tmp_path / "cookies.json.tmp").exists()


class FakeBox:
    def __init__(self, present, checked=False):
        self.present, self.checked, self.first = present, checked, self

    def count(self):
        return 1 if self.present else 0

    def is_checked(self):
        return self.checked

    def check(self):
        self.checked = True


def _page(box, label_box=None):
    return SimpleNamespace(
        locator=lambda sel: box,
        get_by_label=lambda text: label_box or FakeBox(False),
        on=lambda *a, **k: None,
    )


def test_keep_signed_in_is_ticked_once_and_never_untouched_afterwards():
    from amazon_orders_mcp.session_capture import _keep_signed_in_ticker

    box = FakeBox(True)
    tick = _keep_signed_in_ticker(_page(box))
    tick()
    assert box.checked is True
    box.checked = False  # the user unticks it
    tick()
    assert box.checked is False


def test_keep_signed_in_falls_back_to_the_label_and_tolerates_a_missing_box():
    from amazon_orders_mcp.session_capture import _keep_signed_in_ticker

    by_label = FakeBox(True)
    _keep_signed_in_ticker(_page(FakeBox(False), by_label))()
    assert by_label.checked is True

    tick = _keep_signed_in_ticker(_page(FakeBox(False)))
    tick()  # nothing found: no error
    assert tick.state["done"] is False


def test_old_cookie_is_not_enough_when_amazon_still_shows_the_sign_in_page(tmp_path):
    browser = FakeBrowser([[_cookie("x-main", value="old")]])
    browser.page.url = "https://www.amazon.com/ap/signin?openid.pape.max_auth_age=3600"
    jar = tmp_path / "cookies.json"

    result = capture_session(
        timeout_seconds=4,
        jar_path=jar,
        playwright_factory=fake_playwright_factory(browser),
        sleep=lambda s: None,
    )

    assert result["ok"] is False and "Timed out" in result["message"]
    assert not jar.exists()
