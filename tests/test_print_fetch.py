"""Tests for the print-page fetch and get_order wiring, using fake browser objects."""

from tests.conftest import persistent
import asyncio
import json
from types import SimpleNamespace

import pytest

from amazon_orders_mcp import server
from amazon_orders_mcp.client import NonInteractiveAuthRequired
from amazon_orders_mcp.print_fetch import fetch_print_page

ORDER = "111-0000000-0000000"


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

    def cookies(self):
        return [{"name": "x-main", "value": "refreshed", "domain": ".amazon.com"}]

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
            self.chromium = SimpleNamespace(launch=lambda **kwargs: browser, launch_persistent_context=persistent(lambda: browser))

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


def test_fetch_loads_summary_and_saves_refreshed_cookies(jar):
    factory, browser = fake_factory(FakePage(final_url=None))

    text, html = fetch_print_page(ORDER, jar_path=jar, playwright_factory=factory)

    assert text == "Order summary text"
    assert html == "<html>summary</html>"
    assert json.loads(jar.read_text()) == {"x-main": "refreshed"}  # Amazon's newer cookie is kept
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
    assert browser.closed is False  # browser never opened


def test_get_order_returns_parsed_summary(monkeypatch):
    fixture_text = (
        __import__("pathlib").Path(__file__).parent / "fixtures" / "print_summary_sample.txt"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(server, "fetch_print_page", lambda order_id: (fixture_text, "<html></html>"))

    out = json.loads(asyncio.run(server.get_order(ORDER)))

    assert out["order_id"] == "111-0000000-0000000"
    assert out["totals"]["grand_total"] == 115.82
    assert len(out["items"]) == 4


def test_expired_session_in_get_order_points_to_refresh(monkeypatch):
    def expired(order_id):
        raise NonInteractiveAuthRequired("Amazon redirected to sign-in")

    monkeypatch.setattr(server, "capture_session", lambda timeout_seconds: {"ok": False})  # never open a real window
    monkeypatch.setattr(server, "fetch_print_page", expired)

    out = json.loads(asyncio.run(server.get_order(ORDER)))

    assert out["action_required"] == "refresh_session"
    assert "refresh_session" in out["error"]


def test_get_order_with_no_items_reports_a_parse_error(monkeypatch):
    import json as _json

    from amazon_orders_mcp import server as _server

    monkeypatch.setattr(_server, "fetch_print_page", lambda order_id: ("Order Summary\nOrder placed January 1, 2026\nGrand Total:\n$1.00\n", "<html></html>"))
    out = _json.loads(asyncio.run(_server.get_order(ORDER)))
    assert out["exception_type"] == "ParseStructureError"
    assert "items" in out["error"]
    assert out["url"].startswith("https://www.amazon.com/gp/css/summary/print.html")
    assert "Order placed" in out["snippet"]


class RoutedPage(FakePage):
    """Shows a sign-in page for the orders listed in `blocked`."""

    def __init__(self, blocked):
        super().__init__(final_url=None)
        self.blocked = blocked

    def goto(self, url, **kwargs):
        self.url = "https://www.amazon.com/ap/cvf/request" if any(o in url for o in self.blocked) else url


def test_batch_stops_at_sign_in_and_keeps_earlier_orders(jar):
    from amazon_orders_mcp.print_fetch import fetch_print_pages

    orders = ["111-0000000-0000001", "111-0000000-0000002", "111-0000000-0000003"]
    factory, browser = fake_factory(RoutedPage(blocked=[orders[1]]))
    done = []

    with pytest.raises(NonInteractiveAuthRequired):
        fetch_print_pages(orders, lambda oid, t, h: done.append(oid), jar_path=jar, playwright_factory=factory)

    assert done == [orders[0]]  # resume from orders[1] after signing in
    assert browser.closed is True


def test_profile_is_used_by_one_browser_at_a_time(tmp_path):
    from amazon_orders_mcp.browser_profile import ProfileBusy, profile_lock

    lock = tmp_path / "other.lock"
    with profile_lock(lock):
        with pytest.raises(ProfileBusy):
            profile_lock(lock, wait_seconds=0.2).__enter__()
    with profile_lock(lock):  # free again after release
        pass


def test_sign_in_redirect_is_described_without_values_or_order_numbers():
    from amazon_orders_mcp.browser_profile import describe_sign_in

    url = "https://www.amazon.com/ap/signin?openid.pape.max_auth_age=900&openid.return_to=https%3A%2F%2Fwww.amazon.com%2F111-0000000-0000000&token=SECRET"
    text = describe_sign_in(url)
    assert "max_auth_age=900" in text and "/ap/signin" in text
    assert "SECRET" not in text and "111-0000000-0000000" not in text
    assert "max_auth_age=absent" in describe_sign_in("https://www.amazon.com/ap/cvf/request?x=1")


def test_batch_warns_when_the_sign_in_hour_is_nearly_over():
    from amazon_orders_mcp.browser_profile import batch_warning, record_sign_in, sign_in_minutes_left

    assert batch_warning(40, 55) is None  # 2.4 min batch, 55 min left
    assert "5 min left" in batch_warning(40, 5)  # under 10 minutes
    assert batch_warning(200, 20) is None  # a 12 min batch fits in 20 min
    assert batch_warning(300, 15) is not None  # 18 min batch does not fit in 15
    assert "No sign-in time" in batch_warning(5, None)


def test_sign_in_time_is_recorded_and_counted_down(tmp_path):
    from amazon_orders_mcp.browser_profile import record_sign_in, sign_in_minutes_left

    f = tmp_path / "last.txt"
    assert sign_in_minutes_left(path=f) is None
    record_sign_in(now=1000.0, path=f)
    assert sign_in_minutes_left(now=1000.0 + 600, path=f) == 50.0
    assert sign_in_minutes_left(now=1000.0 + 4000, path=f) == 0.0
