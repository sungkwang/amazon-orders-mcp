"""Parse the text of Amazon's printable order summary (print.html).

Works on the visible text of the page (`document.body.innerText`), so it needs
no HTML parser and can be tested offline with saved text fixtures.
"""

import re
from typing import Any, Dict, List, Optional

ORDER_ID_RE = re.compile(r"Order #\s*(\d{3}-\d{7}-\d{7})")
ORDER_DATE_RE = re.compile(r"Order placed\s+([A-Z][a-z]+ \d{1,2}, \d{4})")
MONEY_RE = re.compile(r"^\$[\d,]+\.\d{2}$")

TOTAL_LABELS = {
    "Item(s) Subtotal:": "subtotal",
    "Shipping & Handling:": "shipping",
    "Total before tax:": "before_tax",
    "Estimated tax to be collected:": "tax",
    "Grand Total:": "grand_total",
    "Refund Total": "refund_total",
}


def _money(value: str) -> float:
    return float(value.lstrip("$").replace(",", ""))


def _clean_lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _totals(lines: List[str]) -> Dict[str, Optional[float]]:
    totals: Dict[str, Optional[float]] = {key: None for key in TOTAL_LABELS.values()}
    for i, line in enumerate(lines):
        key = TOTAL_LABELS.get(line.rstrip())
        if key is None:
            continue
        # The amount is on the next line that looks like money
        for nxt in lines[i + 1 : i + 3]:
            if MONEY_RE.match(nxt):
                totals[key] = _money(nxt)
                break
    return totals


def _items(lines: List[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    refunded_block = False
    for i, line in enumerate(lines):
        if line.startswith("Your return is complete") or line.startswith("Return complete"):
            refunded_block = True
            continue
        # A product title is the line right before "Sold by:"
        if i + 1 < len(lines) and lines[i + 1].startswith("Sold by:"):
            seller = lines[i + 1].split(":", 1)[1].strip()
            price = None
            for nxt in lines[i + 2 : i + 8]:
                if MONEY_RE.match(nxt):
                    price = _money(nxt)
                    break
            items.append(
                {
                    "title": line,
                    "seller": seller,
                    "price": price,
                    "refund_status": "refunded" if refunded_block else None,
                }
            )
            refunded_block = False
    return items


def parse_print_text(text: str) -> Dict[str, Any]:
    """Return order id, date, totals, and items from the printable summary text."""
    lines = _clean_lines(text)
    joined = "\n".join(lines)
    order_id = ORDER_ID_RE.search(joined)
    order_date = ORDER_DATE_RE.search(joined)
    return {
        "order_id": order_id.group(1) if order_id else None,
        "order_date": order_date.group(1) if order_date else None,
        "totals": _totals(lines),
        "items": _items(lines),
    }
