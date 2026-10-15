"""Parse the text of Amazon's payments transactions page.

Each transaction is a block: a date and merchant line, the card, the order
number, a signed amount, and a status. Works on visible text, so it can be
tested offline with a fixture.
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

HEADER_RE = re.compile(r"^([A-Z][a-z]{2} \d{1,2}, \d{4})\s*·\s*(.+)$")
ORDER_RE = re.compile(r"^Order #(\d{3}-\d{7}-\d{7})$")
AMOUNT_RE = re.compile(r"^(-?)\$([\d,]+\.\d{2})$")
CARD_RE = re.compile(r"^(.*?)••••(\d{4})$")
STATUSES = {"Charged", "Refunded", "Pending", "Declined"}


def _iso_date(text: str) -> str:
    return datetime.strptime(text, "%b %d, %Y").date().isoformat()


def parse_transactions_text(text: str) -> List[Dict[str, Any]]:
    """Return one dict per transaction block, in page order."""
    transactions: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        header = HEADER_RE.match(line)
        if header:
            current = {
                "date": _iso_date(header.group(1)),
                "merchant": header.group(2).strip(),
                "card_last4": None,
                "card_name": None,
                "order_id": None,
                "amount": None,
                "status": None,
            }
            transactions.append(current)
            continue
        if current is None:
            continue
        card = CARD_RE.match(line)
        order = ORDER_RE.match(line)
        amount = AMOUNT_RE.match(line)
        if card and current["card_last4"] is None:
            current["card_name"] = card.group(1).strip() or None
            current["card_last4"] = card.group(2)
        elif order and current["order_id"] is None:
            current["order_id"] = order.group(1)
        elif amount and current["amount"] is None:
            sign = -1 if amount.group(1) else 1
            current["amount"] = sign * float(amount.group(2).replace(",", ""))
        elif line in STATUSES and current["status"] is None:
            current["status"] = line
    return transactions
