"""Invoice PDF naming, overwrite refusal, and input checks. Fake browser; no Amazon contact."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from amazon_orders_mcp.invoice import invoice_filename, save_order_invoice_pdf

ORDER = "111-0000000-0000001"


def test_file_name_uses_iso_date_and_order_id():
    assert invoice_filename("January 1, 2026", ORDER) == f"2026-01-01_{ORDER}_Invoice.pdf"
    assert invoice_filename("October 14, 2026", ORDER) == f"2026-10-14_{ORDER}_Invoice.pdf"


def test_bad_order_id_or_date_is_rejected():
    with pytest.raises(ValueError):
        invoice_filename("January 1, 2026", "../../x")
    with pytest.raises(ValueError):
        invoice_filename("someday", ORDER)


class FakePage:
    def __init__(self, text, url_after=None, record=None):
        self._text = text
        self._url_after = url_after
        self.url = ""
        self.record = record if record is not None else {}

    def goto(self, url, **kwargs):
        self.url = self._url_after or url

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        return self._text

    def pdf(self, path, **kwargs):
        self.record["pdf_path"] = path
        Path(path).write_bytes(b"%PDF-fake")


def _factory(page, record):
    class _Browser:
        def new_context(self):
            return SimpleNamespace(add_cookies=lambda c: None, new_page=lambda: page)

        def close(self):
            record["closed"] = True

    class _Playwright:
        chromium = SimpleNamespace(launch=lambda **kwargs: _Browser())

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


SUMMARY = "Order Summary\nOrder placed January 1, 2026  Order # 111-0000000-0000001\nGrand Total:\n$1.00\n"


def test_saves_pdf_with_standard_name(tmp_path, jar):
    record = {}
    page = FakePage(SUMMARY, record=record)
    out_dir = tmp_path / "2026"
    out_dir.mkdir()
    target = save_order_invoice_pdf(ORDER, out_dir, jar_path=jar, playwright_factory=_factory(page, record))
    assert target.name == f"2026-01-01_{ORDER}_Invoice.pdf"
    assert target.read_bytes().startswith(b"%PDF")
    assert record["closed"] is True


def test_existing_file_is_never_overwritten(tmp_path, jar):
    out_dir = tmp_path / "2026"
    out_dir.mkdir()
    existing = out_dir / f"2026-01-01_{ORDER}_Invoice.pdf"
    existing.write_bytes(b"keep me")
    record = {}
    page = FakePage(SUMMARY, record=record)
    with pytest.raises(FileExistsError):
        save_order_invoice_pdf(ORDER, out_dir, jar_path=jar, playwright_factory=_factory(page, record))
    assert existing.read_bytes() == b"keep me"
    assert "pdf_path" not in record


def test_missing_output_folder_is_refused_before_browsing(tmp_path, jar):
    record = {}
    with pytest.raises(ValueError):
        save_order_invoice_pdf(ORDER, tmp_path / "nope", jar_path=jar, playwright_factory=_factory(FakePage(SUMMARY, record=record), record))
    assert record == {}
