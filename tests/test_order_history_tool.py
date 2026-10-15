"""get_order_history uses the text-based list; tests use a fake list function."""

import asyncio
import json

from amazon_orders_mcp import server


def test_year_is_passed_to_the_list_function(monkeypatch):
    seen = {}

    def fake_list(year):
        seen["year"] = year
        return [{"order_id": "111-0000000-0000001", "order_date": "October 13, 2026", "total": "$8.98", "item_titles": []}]

    monkeypatch.setattr(server, "list_orders_for_year", fake_list)
    out = json.loads(asyncio.run(server.get_order_history(year=2026)))

    assert seen["year"] == 2026
    assert out[0]["order_id"] == "111-0000000-0000001"


def test_time_filter_returns_a_clear_error(monkeypatch):
    monkeypatch.setattr(server, "list_orders_for_year", lambda year: [])
    out = json.loads(asyncio.run(server.get_order_history(time_filter="last30")))
    assert "not supported" in out["error"]
