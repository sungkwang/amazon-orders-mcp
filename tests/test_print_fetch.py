"""Tests for the print-page fetch and get_order wiring, using fake browser objects."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from amazon_orders_mcp import server
from amazon_orders_mcp.client import NonInteractiveAuthRequired
from amazon_orders_mcp.print_fetch import fetch_print_page

ORDER = "112-6616953-4948205"


class FakePage:
    def __init__(self, final_url):
        self._final_url = final_url
        self.url = ""

    def goto(self, url, **kwargs):
        self.url = self._final_url or url

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return "<html>summary</html>"

    def evaluate(self, script):
        return "Order summary text"


class FakeContext:
    def __init__(self, page):
        self._page = page
        self.cookies_added = None

    def add_cookies(self, cookies):
        self.cookies_added = cookies

    def new_page(self):
        return self._page


class FakeBrowser:
    def __init__(self, page):
        self.context = FakeContext(page)
        self.closed = False

    def new_context(self):
        return self.context

    def close(self):
        self.closed = True


def fake_factory(page):
    browser = FakeBrowser(page)

    class _Playwright:
        def __init__(self):
            self.chromium = SimpleNamespace(launch=lambda **kwargs: browser)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return (lambda: _Playwright()), browser


@pytest.fixture
def jar(tmp_path):
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps({"x-main": "abc"}))
    return path


def test_fetch_loads_summary_with_saved_cookies(jar):
    factory, browser = fake_factory(FakePage(final_url=None))

    text, html = fetch_print_page(ORDER, jar_path=jar, playwright_factory=factory)

    assert text == "Order summary text"
    assert html == "<html>summary</html>"
    cookies = browser.context.cookies_added
    assert cookies[0]["name"] == "x-main"
    assert cookies[0]["domain"] == ".amazon.com"
    assert browser.closed is True


def test_redirect_to_sign_in_raises_refresh_error(jar):
    page = FakePage(final_url="https://www.amazon.com/ap/signin?openid.mode=checkid_setup")
    factory, browser = fake_factory(page)

    with pytest.raises(NonInteractiveAuthRequired):
        fetch_print_page(ORDER, jar_path=jar, playwright_factory=factory)
    assert browser.closed is True


def test_bad_order_number_is_rejected_before_browsing(jar):
    factory, browser = fake_factory(FakePage(final_url=None))

    with pytest.raises(ValueError):
        fetch_print_page("../../etc", jar_path=jar, playwright_factory=factory)
    assert browser.context.cookies_added is None  # browser never used


def test_get_order_returns_parsed_summary(monkeypatch):
    fixture_text = (
        __import__("pathlib").Path(__file__).parent / "fixtures" / "print_summary_sample.txt"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(server, "fetch_print_page", lambda order_id: (fixture_text, "<html></html>"))

    out = json.loads(asyncio.run(server.get_order(ORDER)))

    assert out["order_id"] == "112-6616953-4948205"
    assert out["totals"]["grand_total"] == 115.82
    assert len(out["items"]) == 4


def test_expired_session_in_get_order_points_to_refresh(monkeypatch):
    def expired(order_id):
        raise NonInteractiveAuthRequired("Amazon redirected to sign-in")

    monkeypatch.setattr(server, "fetch_print_page", expired)

    out = json.loads(asyncio.run(server.get_order(ORDER)))

    assert out["action_required"] == "refresh_session"
    assert "refresh_session" in out["error"]
