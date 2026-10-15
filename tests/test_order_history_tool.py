"""get_order_history uses the text-based list; tests use a fake list function."""

import asyncio
import json

from amazon_orders_mcp import server


def test_year_is_passed_to_the_list_function(monkeypatch):
    seen = {}

    def fake_list(year):
        seen["year"] = year
        return {"orders": [{"order_id": "111-0000000-0000001", "order_date": "October 13, 2026", "total": "$8.98", "item_titles": []}], "truncated": False, "warning": None}

    monkeypatch.setattr(server, "list_orders_for_year", fake_list)
    out = json.loads(asyncio.run(server.get_order_history(year=2026)))

    assert seen["year"] == 2026
    assert out["orders"][0]["order_id"] == "111-0000000-0000001"
    assert out["truncated"] is False


def test_time_filter_returns_a_clear_error(monkeypatch):
    monkeypatch.setattr(server, "list_orders_for_year", lambda year: {"orders": [], "truncated": False, "warning": None})
    out = json.loads(asyncio.run(server.get_order_history(time_filter="last30")))
    assert "time_filter" in out["error"]


def test_unsupported_parameters_are_reported_not_ignored(monkeypatch):
    monkeypatch.setattr(server, "list_orders_for_year", lambda year: [])
    out = json.loads(asyncio.run(server.get_order_history(year=2026, start_index=10)))
    assert "start_index" in out["error"]


def test_status_hint_uses_a_supported_call(monkeypatch):
    monkeypatch.setattr(server, "cookie_jar_exists", lambda: True)
    monkeypatch.setattr(server, "load_credentials", lambda: None)
    text = server.check_auth_status.__wrapped__() if hasattr(server.check_auth_status, "__wrapped__") else server.check_auth_status()
    assert "time_filter" not in text
    assert "get_order_history(year=2026)" in text

def test_check_asin_tool_is_registered():
    names = [tool.name for tool in asyncio.run(server.mcp.list_tools())]
    assert "check_asin_eligibility" in names
