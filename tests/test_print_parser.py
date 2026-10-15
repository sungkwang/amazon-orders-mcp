"""Tests for the print-summary text parser, using a sanitized saved fixture."""

from pathlib import Path

import pytest

from amazon_orders_mcp.print_parser import parse_print_text

FIXTURE = Path(__file__).parent / "fixtures" / "print_summary_sample.txt"


@pytest.fixture
def parsed():
    return parse_print_text(FIXTURE.read_text(encoding="utf-8"))


def test_order_header(parsed):
    assert parsed["order_id"] == "112-6616953-4948205"
    assert parsed["order_date"] == "January 1, 2026"


def test_totals(parsed):
    totals = parsed["totals"]
    assert totals["subtotal"] == 108.76
    assert totals["shipping"] == 0.00
    assert totals["tax"] == 7.06
    assert totals["grand_total"] == 115.82
    assert totals["refund_total"] == 31.88


def test_items_have_title_seller_and_price(parsed):
    items = {item["seller"]: item for item in parsed["items"]}
    assert len(parsed["items"]) == 4
    assert items["Sample Seller A"]["price"] == 23.99
    assert items["Sample Seller B"]["price"] == 27.99
    assert items["Sample Seller C"]["price"] == 26.99
    assert items["Amazon.com"]["price"] == 29.79


def test_item_titles_are_the_product_lines(parsed):
    bug_bite = next(i for i in parsed["items"] if i["seller"] == "Sample Seller C")
    assert bug_bite["title"].startswith("Sample First Aid Tool")


def test_refunded_item_is_flagged_and_others_are_not(parsed):
    flags = {i["seller"]: i["refund_status"] for i in parsed["items"]}
    assert flags["Amazon.com"] == "refunded"  # the wine bottles
    assert flags["Sample Seller C"] is None


def test_empty_text_gives_no_items():
    parsed = parse_print_text("")
    assert parsed["order_id"] is None
    assert parsed["items"] == []
    assert all(v is None for v in parsed["totals"].values())
