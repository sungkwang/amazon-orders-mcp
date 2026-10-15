"""Tests for matching external amounts against the order list (synthetic data)."""

from datetime import date

from amazon_orders_mcp.order_list import match_orders_by_amount

ORDERS = [
    {"order_id": "111-0000000-0000001", "order_date": "October 13, 2026", "total": "$8.98", "item_titles": ["Sample cable"]},
    {"order_id": "111-0000000-0000002", "order_date": "October 12, 2026", "total": "$8.98", "item_titles": ["Sample tape"]},
    {"order_id": "111-0000000-0000003", "order_date": "October 1, 2026", "total": "$22.00", "item_titles": []},
]


def test_matches_total_within_window():
    q = [{"date": date(2026, 10, 14), "amount": -8.98, "window_days": 3, "id": "bank-1"}]
    result = match_orders_by_amount(ORDERS, q)[0]
    ids = [m["order_id"] for m in result["matches"]]
    assert result["match_count"] == 2
    assert ids == ["111-0000000-0000001", "111-0000000-0000002"]
    assert result["query"]["id"] == "bank-1"  # extra fields are echoed back


def test_outside_window_is_not_a_match():
    q = [{"date": date(2026, 10, 25), "amount": -8.98, "window_days": 3}]
    assert match_orders_by_amount(ORDERS, q)[0]["match_count"] == 0


def test_amount_must_match_within_tolerance():
    q = [{"date": date(2026, 10, 1), "amount": -22.05, "window_days": 0}]
    assert match_orders_by_amount(ORDERS, q, tolerance=0.01)[0]["match_count"] == 0
    assert match_orders_by_amount(ORDERS, q, tolerance=0.10)[0]["match_count"] == 1


def test_offset_is_reported():
    q = [{"date": date(2026, 10, 14), "amount": 8.98, "window_days": 2}]
    offsets = sorted(m["date_offset_days"] for m in match_orders_by_amount(ORDERS, q)[0]["matches"])
    assert offsets == [-2, -1]
