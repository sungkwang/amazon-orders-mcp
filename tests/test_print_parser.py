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
    assert links[2000] == {"asin": "B01EAS3ER8", "image_id": "51egPDp3D1L"}
    assert links[3000]["asin"] == "B0CZGVZPKQ"


def test_parse_print_page_attaches_asin_to_each_item(parsed):
    from amazon_orders_mcp.print_parser import parse_print_page

    text = FIXTURE.read_text(encoding="utf-8")
    html = (Path(__file__).parent / "fixtures" / "print_item_links.txt").read_text(encoding="utf-8")
    result = parse_print_page(text, html)
    by_seller = {i["seller"]: i for i in result["items"]}
    assert by_seller["Sample Seller A"]["asin"] == "B0D8B5M9K1"
    assert by_seller["Sample Seller C"]["asin"] == "B01EAS3ER8"
    assert by_seller["Sample Seller C"]["image_id"] == "51egPDp3D1L"


def test_validate_accepts_a_complete_summary(parsed):
    from amazon_orders_mcp.print_parser import validate_order_summary

    validate_order_summary(parsed, url="https://example.test/print", text=FIXTURE.read_text(encoding="utf-8"))


def test_validate_rejects_a_summary_with_no_items(parsed):
    import pytest as _pytest

    from amazon_orders_mcp.errors import ParseStructureError
    from amazon_orders_mcp.print_parser import validate_order_summary

    parsed["items"] = []
    with _pytest.raises(ParseStructureError) as info:
        validate_order_summary(parsed, url="https://example.test/print", text="Some page text")
    assert "items" in str(info.value)
    assert info.value.url == "https://example.test/print"
    assert info.value.snippet == "Some page text"


def test_validate_rejects_missing_total_and_date(parsed):
    import pytest as _pytest

    from amazon_orders_mcp.errors import ParseStructureError
    from amazon_orders_mcp.print_parser import validate_order_summary

    parsed["totals"]["grand_total"] = None
    parsed["order_date"] = None
    with _pytest.raises(ParseStructureError) as info:
        validate_order_summary(parsed, url="u", text="t")
    assert "grand total" in str(info.value) and "order date" in str(info.value)


def _link_block(n, asin, title, image):
    return (
        f'<a href="/dp/{asin}?ref_=ppx_printOD_image_dt_b_fed_asin_title_{n}"><img src="https://m.media-amazon.com/images/I/{image}._SS284_.jpg"></a>'
        f'<a href="/dp/{asin}?ref_=ppx_printOD_title_dt_b_fed_asin_title_{n}">  {title}  </a>'
    )


def test_items_match_links_by_title_when_numbering_is_shifted():
    from amazon_orders_mcp.print_parser import parse_print_page

    text = FIXTURE.read_text(encoding="utf-8")
    # Link numbers do not follow the text order, and one item has no link at all
    html = _link_block("0_0", "CCCCCCCCCC", "Sample First Aid Tool - Sample Insect Relief, 3 Pack", "imgC") + _link_block(
        "1_0", "AAAAAAAAAA", "Sample Plush Toy, 12 Inch Stuffed Animal, Sample Edition", "imgA"
    )
    result = parse_print_page(text, html)
    by_seller = {i["seller"]: i for i in result["items"]}
    assert by_seller["Sample Seller A"]["asin"] == "AAAAAAAAAA"
    assert by_seller["Sample Seller A"]["image_id"] == "imgA"
    assert by_seller["Sample Seller C"]["asin"] == "CCCCCCCCCC"
    assert "asin" not in by_seller["Sample Seller B"]  # no link: no borrowed image or ASIN


def test_two_items_in_one_package_each_get_their_own_link():
    from amazon_orders_mcp.print_parser import parse_print_page

    text = FIXTURE.read_text(encoding="utf-8")
    # Both links end in a different second number (0_0 and 0_1), as Amazon writes them for one package
    html = _link_block("0_0", "AAAAAAAAAA", "Sample Plush Toy, 12 Inch Stuffed Animal, Sample Edition", "imgA") + _link_block(
        "0_1", "CCCCCCCCCC", "Sample First Aid Tool - Sample Insect Relief, 3 Pack", "imgC"
    )
    by_seller = {i["seller"]: i for i in parse_print_page(text, html)["items"]}
    assert by_seller["Sample Seller A"]["image_id"] == "imgA"
    assert by_seller["Sample Seller C"]["image_id"] == "imgC"
