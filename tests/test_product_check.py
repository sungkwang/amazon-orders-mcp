"""Product eligibility check with fake browsers. No Amazon contact."""

from datetime import date
from types import SimpleNamespace

import pytest

from amazon_orders_mcp.product_check import check_product_eligibility


def _factory(page_text, record):
    class _Page:
        def goto(self, url, **kwargs):
            record["url"] = url

        def wait_for_timeout(self, ms):
            pass

        def evaluate(self, script):
            return page_text

    class _Context:
        def new_page(self):
            return _Page()

    class _Browser:
        def new_context(self):
            record["context_args"] = "no cookies"
            return _Context()

        def close(self):
            record["closed"] = True

    class _Playwright:
        chromium = SimpleNamespace(launch=lambda **kwargs: _Browser())

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return lambda: _Playwright()


def test_label_present_is_reported_with_matched_text():
    record = {}
    text = "Product title\nFSA or HSA eligible Details\nPrice $5.00"
    out = check_product_eligibility("b08r5pmktt", playwright_factory=_factory(text, record), today=date(2026, 10, 14))
    assert out == {
        "asin": "B08R5PMKTT",
        "fsa_hsa_eligible": True,
        "matched_text": "FSA or HSA eligible Details",
        "checked_date": "2026-10-14",
    }
    assert record["url"] == "https://www.amazon.com/dp/B08R5PMKTT"
    assert record["context_args"] == "no cookies"
    assert record["closed"] is True


def test_label_absent_is_reported_as_not_eligible():
    out = check_product_eligibility("B0CZGVZPKQ", playwright_factory=_factory("Just a product page", {}), today=date(2026, 10, 14))
    assert out["fsa_hsa_eligible"] is False
    assert out["matched_text"] is None


def test_invalid_asin_is_rejected_before_any_browsing():
    record = {}
    with pytest.raises(ValueError):
        check_product_eligibility("../../etc", playwright_factory=_factory("x", record))
    assert record == {}
