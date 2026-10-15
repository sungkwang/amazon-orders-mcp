"""Tests for the print-summary text parser, using a sanitized saved fixture."""

from pathlib import Path

import pytest

from amazon_orders_mcp.print_parser import parse_print_text

FIXTURE = Path(__file__).parent / "fixtures" / "print_summary_sample.txt"


@pytest.fixture
def parsed():
    return parse_print_text(FIXTURE.read_text(encoding="utf-8"))


def test_order_header(parsed):
    assert parsed["order_id"] == "111-0000000-0000000"
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


def test_item_links_match_items_by_position():
    from amazon_orders_mcp.print_parser import item_links

    html = (Path(__file__).parent / "fixtures" / "print_item_links.txt").read_text(encoding="utf-8")
    links = item_links(html)
    assert links[0] == {"asin": "B0D8B5M9K1", "image_id": "71gCJU6br-L"}
    assert links[2] == {"asin": "B01EAS3ER8", "image_id": "51egPDp3D1L"}
    assert links[3]["asin"] == "B0CZGVZPKQ"


def test_parse_print_page_attaches_asin_to_each_item(parsed):
    from amazon_orders_mcp.print_parser import parse_print_page

    text = FIXTURE.read_text(encoding="utf-8")
    html = (Path(__file__).parent / "fixtures" / "print_item_links.txt").read_text(encoding="utf-8")
    result = parse_print_page(text, html)
    by_seller = {i["seller"]: i for i in result["items"]}
    assert by_seller["Sample Seller A"]["asin"] == "B0D8B5M9K1"
    assert by_seller["Sample Seller C"]["asin"] == "B01EAS3ER8"
    assert by_seller["Sample Seller C"]["image_id"] == "51egPDp3D1L"
