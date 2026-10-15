"""Tests for the payments transactions text parser, using a synthetic fixture."""

from pathlib import Path

from amazon_orders_mcp.transactions_parser import parse_transactions_text

FIXTURE = Path(__file__).parent / "fixtures" / "transactions_sample.txt"


def test_parses_each_block_in_order():
    rows = parse_transactions_text(FIXTURE.read_text(encoding="utf-8"))
    assert [r["order_id"] for r in rows] == [
        "111-0000000-0000001",
        "111-0000000-0000002",
        "111-0000000-0000003",
    ]


def test_dates_are_iso_and_merchants_kept():
    rows = parse_transactions_text(FIXTURE.read_text(encoding="utf-8"))
    assert rows[0]["date"] == "2026-10-14"
    assert rows[0]["merchant"] == "AMZN Mktp US"
    assert rows[2]["date"] == "2026-02-04"


def test_amounts_are_signed_charges_negative():
    rows = parse_transactions_text(FIXTURE.read_text(encoding="utf-8"))
    assert [r["amount"] for r in rows] == [-8.98, -18.29, 6.78]


def test_card_and_status_fields():
    rows = parse_transactions_text(FIXTURE.read_text(encoding="utf-8"))
    assert rows[0]["card_last4"] == "0000"
    assert rows[0]["card_name"] == "Prime Visa"
    assert rows[0]["status"] == "Charged"
    assert rows[2]["status"] == "Refunded"


def test_empty_text_gives_no_rows():
    assert parse_transactions_text("") == []
