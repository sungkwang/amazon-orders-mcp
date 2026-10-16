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


LINK_RE = re.compile(
    r"/dp/([A-Z0-9]{10})\?ref_=ppx_printOD_(?:title|image)_dt_b_fed_asin_title_(\d+)_(\d+)"
)
IMAGE_ANCHOR_RE = re.compile(r"ppx_printOD_image_dt_b_fed_asin_title_(\d+)_(\d+)")
IMAGE_URL_RE = re.compile(r"media-amazon\.com/images/I/([^\"'\s?]+?)\._SS\d+_\.jpg")


TITLE_ANCHOR_RE = re.compile(r"ppx_printOD_title_dt_b_fed_asin_title_(\d+)_(\d+)[^>]*>(.*?)</a>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", text or "")).strip().lower()


def _slot(match: "re.Match[str]", first_group: int) -> int:
    """One number per link: Amazon names links title_<a>_<b>, so both numbers pick the slot."""
    return int(match.group(first_group)) * 1000 + int(match.group(first_group + 1))


def item_links(html: str) -> Dict[int, Dict[str, str]]:
    """Map the page's link number to its product ASIN, image id, and title text.

    The link number does not always follow the item text order (for example when an
    order ships in several packages), so parse_print_page matches by title when the
    page gives the title text.
    """
    links: Dict[int, Dict[str, str]] = {}
    for match in LINK_RE.finditer(html):
        links.setdefault(_slot(match, 2), {})["asin"] = match.group(1)
    for match in IMAGE_ANCHOR_RE.finditer(html):
        image = IMAGE_URL_RE.search(html, match.end(), match.end() + 1500)
        if image:
            links.setdefault(_slot(match, 1), {})["image_id"] = image.group(1)
    for match in TITLE_ANCHOR_RE.finditer(html):
        text = _norm(match.group(3))
        if text:
            links.setdefault(_slot(match, 1), {})["title"] = text
    return links


def parse_print_page(text: str, html: str) -> Dict[str, Any]:
    """Combine the text summary with per-item ASINs and image ids.

    Items are matched to links by title. An item that matches no link gets no ASIN and
    no image, never someone else's. Without title text on the page, the link number is used.
    """
    parsed = parse_print_text(text)
    links = item_links(html)
    titled = {n: link for n, link in links.items() if link.get("title")}
    used = set()
    for index, item in enumerate(parsed["items"]):
        found = None
        if titled:
            key = _norm(item["title"])
            for n, link in titled.items():
                t = link["title"]
                if n not in used and (t == key or t.startswith(key[:40]) or key.startswith(t[:40])):
                    found = n
                    break
        elif index * 1000 in links:
            found = index * 1000
        if found is not None:
            used.add(found)
            item.update({k: v for k, v in links[found].items() if k != "title"})
    return parsed


def validate_order_summary(parsed: Dict[str, Any], url: str, text: str) -> None:
    """Raise ParseStructureError if a printable summary lacks its required fields."""
    from amazon_orders_mcp.errors import ParseStructureError, snippet_of

    missing = []
    if not parsed.get("items"):
        missing.append("items")
    if parsed.get("totals", {}).get("grand_total") is None:
        missing.append("grand total")
    if not parsed.get("order_date"):
        missing.append("order date")
    if missing:
        raise ParseStructureError(
            f"Order summary is missing: {', '.join(missing)}. Amazon may have changed the page layout.",
            url=url,
            snippet=snippet_of(text),
        )
