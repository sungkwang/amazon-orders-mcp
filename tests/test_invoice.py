"""Invoice PDF naming, overwrite refusal, batch saving, and input checks. Fake browser; no Amazon contact."""

from tests.conftest import persistent
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from amazon_orders_mcp.client import NonInteractiveAuthRequired
from amazon_orders_mcp.invoice import invoice_filename, save_order_invoice_pdf, save_order_invoices

ORDER = "111-0000000-0000001"
OTHER = "111-0000000-0000002"


def test_file_name_uses_iso_date_and_order_id():
    assert invoice_filename("January 1, 2026", ORDER) == f"2026-01-01_order_amazon_{ORDER}.pdf"
    assert invoice_filename("October 14, 2026", ORDER) == f"2026-10-14_order_amazon_{ORDER}.pdf"


def test_bad_order_id_or_date_is_rejected():
    with pytest.raises(ValueError):
        invoice_filename("January 1, 2026", "../../x")
    with pytest.raises(ValueError):
        invoice_filename("someday", ORDER)


class FakePage:
    """Serves summary text per order number; a page that redirects to sign-in when asked."""

    def __init__(self, texts, expired=(), record=None):
        self._texts = texts
        self._expired = set(expired)
        self._url = ""
        self.record = record if record is not None else {}

    @property
    def url(self):
        return "https://www.amazon.com/ap/signin" if self._current() in self._expired else self._url

    def _current(self):
        return self._url.rsplit("=", 1)[-1]

    def goto(self, url, **kwargs):
        self._url = url

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        return self._texts.get(self._current(), "")

    def pdf(self, path, **kwargs):
        self.record["pdf_kwargs"] = kwargs
        self.record.setdefault("pdfs", []).append(path)
        Path(path).write_bytes(b"%PDF-fake")


def _summary(order_id, date="January 1, 2026"):
    return f"Order Summary\nOrder placed {date}  Order # {order_id}\nGrand Total:\n$1.00\n"


def _factory(page, record):
    class _Browser:
        def new_context(self):
            return SimpleNamespace(add_cookies=lambda c: None, new_page=lambda: page)

        def close(self):
            record["closed"] = True

    class _Playwright:
        chromium = SimpleNamespace(launch=lambda **kwargs: _Browser(), launch_persistent_context=persistent(lambda: _Browser()))

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


@pytest.fixture
def out_dir(tmp_path):
    path = tmp_path / "2026"
    path.mkdir()
    return path


def test_saves_pdf_with_standard_name(out_dir, jar):
    record = {}
    page = FakePage({ORDER: _summary(ORDER)}, record=record)
    target = save_order_invoice_pdf(ORDER, out_dir, jar_path=jar, playwright_factory=_factory(page, record))
    assert target.name == f"2026-01-01_order_amazon_{ORDER}.pdf"
    assert target.read_bytes().startswith(b"%PDF")
    assert record["pdf_kwargs"]["print_background"] is False  # no page colors, footer band, or logo art
    assert record["closed"] is True


def test_existing_file_is_never_overwritten(out_dir, jar):
    existing = out_dir / f"2026-01-01_order_amazon_{ORDER}.pdf"
    existing.write_bytes(b"keep me")
    record = {}
    page = FakePage({ORDER: _summary(ORDER)}, record=record)
    with pytest.raises(FileExistsError):
        save_order_invoice_pdf(ORDER, out_dir, jar_path=jar, playwright_factory=_factory(page, record))
    assert existing.read_bytes() == b"keep me"
    assert "pdfs" not in record


def test_missing_output_folder_is_refused_before_browsing(tmp_path, jar):
    record = {}
    page = FakePage({ORDER: _summary(ORDER)}, record=record)
    with pytest.raises(ValueError):
        save_order_invoice_pdf(ORDER, tmp_path / "nope", jar_path=jar, playwright_factory=_factory(page, record))
    assert record == {}


def test_batch_saves_skips_and_reports_errors(out_dir, jar):
    existing = out_dir / f"2026-01-01_order_amazon_{OTHER}.pdf"
    existing.write_bytes(b"keep me")
    third = "111-0000000-0000003"
    record = {}
    texts = {
        ORDER: _summary(ORDER),
        OTHER: _summary(OTHER),
        third: "Order Summary with no date on it",
    }
    page = FakePage(texts, record=record)
    results = save_order_invoices([ORDER, OTHER, third], out_dir, jar_path=jar, playwright_factory=_factory(page, record))

    by_id = {r["order_id"]: r for r in results}
    assert by_id[ORDER]["status"] == "saved"
    assert Path(by_id[ORDER]["path"]).name == f"2026-01-01_order_amazon_{ORDER}.pdf"
    assert by_id[OTHER]["status"] == "skipped"
    assert by_id[third]["status"] == "error"
    assert existing.read_bytes() == b"keep me"
    assert record["closed"] is True


def test_batch_drops_repeated_order_ids(out_dir, jar):
    record = {}
    page = FakePage({ORDER: _summary(ORDER)}, record=record)
    results = save_order_invoices([ORDER, ORDER], out_dir, jar_path=jar, playwright_factory=_factory(page, record))
    assert [r["order_id"] for r in results] == [ORDER]
    assert len(record["pdfs"]) == 1


def test_batch_stops_when_session_expires(out_dir, jar):
    record = {}
    page = FakePage({ORDER: _summary(ORDER), OTHER: _summary(OTHER)}, expired={OTHER}, record=record)
    with pytest.raises(NonInteractiveAuthRequired):
        save_order_invoices([ORDER, OTHER], out_dir, jar_path=jar, playwright_factory=_factory(page, record))
    assert len(record["pdfs"]) == 1  # the first order was saved and kept
    assert record["closed"] is True


def test_batch_rejects_bad_id_before_browsing(out_dir, jar):
    record = {}
    page = FakePage({ORDER: _summary(ORDER)}, record=record)
    with pytest.raises(ValueError):
        save_order_invoices([ORDER, "bad"], out_dir, jar_path=jar, playwright_factory=_factory(page, record))
    assert record == {}
