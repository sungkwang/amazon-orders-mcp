"""Tests for the order-history text parser, using a synthetic fixture."""

from pathlib import Path

from amazon_orders_mcp.order_list import parse_order_list_text

FIXTURE = Path(__file__).parent / "fixtures" / "order_list_sample.txt"


def _orders():
    return parse_order_list_text(FIXTURE.read_text(encoding="utf-8"))


def test_finds_each_order_with_id_date_and_total():
    orders = _orders()
    assert [o["order_id"] for o in orders] == [
        "111-0000000-0000001",
        "111-0000000-0000002",
        "111-0000000-0000003",
    ]
    assert orders[0]["order_date"] == "October 13, 2026"
    assert orders[0]["total"] == "$8.98"


def test_item_titles_come_before_action_links():
    orders = _orders()
    assert orders[0]["item_titles"] == ["Sample USB Cable 3M Right Angle For Sample Devices"]
    assert orders[1]["item_titles"] == [
        "Sample Body Wash, Gentle, 16.9oz",
        "Sample Face Wash With Sample Acid, 6.8oz",
    ]


def test_shipping_name_is_not_an_item():
    for order in _orders():
        assert all("Sample Person" not in t for t in order["item_titles"])


def test_sold_by_line_marks_the_title_before_it():
    assert _orders()[2]["item_titles"] == ["Sample Wine Bottles (Pack of 12) With Caps"]


def test_empty_text_gives_no_orders():
    assert parse_order_list_text("") == []


def test_progress_callback_reports_each_page(tmp_path):
    from types import SimpleNamespace

    from amazon_orders_mcp.order_list import list_orders_for_year
    from tests.conftest import persistent

    sample = FIXTURE.read_text(encoding="utf-8")
    texts = [sample, ""]  # page 1 has orders, page 2 is empty and ends the loop

    class FakePage:
        url = ""

        def __init__(self):
            self.index = 0

        def goto(self, url, **kwargs):
            self.url = url

        def wait_for_timeout(self, ms):
            pass

        def evaluate(self, script):
            text = texts[min(self.index, len(texts) - 1)]
            self.index += 1
            return text

    class FakeContext:
        def __init__(self, page):
            self.page = page

        def add_cookies(self, cookies):
            pass

        def new_page(self):
            return self.page

    class FakeBrowser:
        def __init__(self):
            self.page = FakePage()

        def new_context(self):
            return FakeContext(self.page)

        def close(self):
            pass

    browser = FakeBrowser()
    jar = tmp_path / "cookies.json"
    jar.write_text('{"x-main": "abc"}')

    class _Playwright:
        chromium = SimpleNamespace(launch=lambda **kwargs: browser, launch_persistent_context=persistent(lambda: browser))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    calls = []
    result = list_orders_for_year(
        2026,
        jar_path=jar,
        playwright_factory=lambda: _Playwright(),
        on_page=lambda page, count, seconds: calls.append((page, count)),
    )

    assert len(result["orders"]) == 3
    assert result["truncated"] is False
    assert calls == [(1, 3)]


def test_action_links_are_never_titles():
    from amazon_orders_mcp.order_list import parse_order_list_text

    text = (
        "ORDER PLACED\nOctober 14, 2026\nTOTAL\n$8.98\nORDER # 111-0000000-0000009\n"
        "Sample Item Title That Is Long Enough\nTrack package\nView or edit order\n"
        "Return or replace items\n"
        "Auto-delivered: Every 6 months\nTrack package\n"
    )
    orders = parse_order_list_text(text)
    assert orders[0]["item_titles"] == ["Sample Item Title That Is Long Enough"]
