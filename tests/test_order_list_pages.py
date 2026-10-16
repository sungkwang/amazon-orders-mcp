"""Page-level behavior of list_orders_for_year: broken pages, the end of the list, and the page cap.

Uses fake browser objects and synthetic text. No Amazon contact.
"""

from tests.conftest import persistent
import json
from types import SimpleNamespace

import pytest

from amazon_orders_mcp import order_list
from amazon_orders_mcp.errors import ParseStructureError
from amazon_orders_mcp.order_list import list_orders_for_year


def _order_block(order_id):
    return (
        "ORDER PLACED\nOctober 13, 2026\nTOTAL\n$8.98\n"
        f"ORDER # {order_id}\nSample Item Title That Is Long Enough\nBuy it again\n"
    )


class ScriptedPage:
    """Returns a scripted text for each goto, in order; repeats the last one."""

    def __init__(self, texts):
        self._texts = texts
        self._index = -1
        self.url = ""

    def goto(self, url, **kwargs):
        self._index = min(self._index + 1, len(self._texts) - 1)
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        return self._texts[self._index]


def _factory(page):
    class _Browser:
        def new_context(self):
            return SimpleNamespace(add_cookies=lambda c: None, new_page=lambda: page)

        def close(self):
            pass

    browser = _Browser()

    class _Playwright:
        chromium = SimpleNamespace(launch=lambda **kwargs: browser, launch_persistent_context=persistent(lambda: browser))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return lambda: _Playwright()


@pytest.fixture
def jar(tmp_path):
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps({"x-main": "abc"}))
    return path


def test_end_of_list_is_not_an_error_and_not_truncated(jar):
    page = ScriptedPage([_order_block("111-0000000-0000001"), "Your orders end here. Back to top."])
    result = list_orders_for_year(2026, jar_path=jar, playwright_factory=_factory(page))
    assert len(result["orders"]) == 1
    assert result["truncated"] is False
    assert result["warning"] is None


def test_orders_visible_but_unreadable_raises_parse_error(jar):
    broken = "ORDER PLACED\nOctober 13, 2026\nSomething new the parser does not know\n"
    page = ScriptedPage([broken])
    with pytest.raises(ParseStructureError) as info:
        list_orders_for_year(2026, jar_path=jar, playwright_factory=_factory(page))
    assert info.value.url.startswith("https://www.amazon.com/your-orders/orders")
    assert "ORDER PLACED" in info.value.snippet


def test_empty_year_with_no_order_text_returns_no_orders(jar):
    page = ScriptedPage(["You have no orders in this period."])
    result = list_orders_for_year(2026, jar_path=jar, playwright_factory=_factory(page))
    assert result["orders"] == []
    assert result["truncated"] is False


def test_reaching_the_page_cap_marks_the_list_truncated(jar, monkeypatch):
    monkeypatch.setattr(order_list, "MAX_PAGES", 3)
    # Every page has a new order, so the loop never finds an empty page
    texts = [_order_block(f"111-0000000-000000{i}") for i in range(1, 6)]
    page = ScriptedPage(texts)
    result = list_orders_for_year(2026, jar_path=jar, playwright_factory=_factory(page))
    assert len(result["orders"]) == 3
    assert result["truncated"] is True
    assert "3 pages" in result["warning"]
