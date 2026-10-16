#!/usr/bin/env python3
"""
Save Amazon order summaries as PDFs, one per order, in one browser session.

Reads order numbers from a text file (one per line; blank lines and # comments
are ignored) and writes <YYYY-MM-DD>_order_amazon_<order>.pdf into the output folder.
Orders that already have a file there are skipped. Each run contacts Amazon, so
run it only when you choose to.

Run from the repo root:
    python scripts/save_invoices.py "<folder>\\2026" orders.txt
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amazon_orders_mcp.client import NonInteractiveAuthRequired  # noqa: E402
from amazon_orders_mcp.invoice import save_order_invoices  # noqa: E402


def read_order_ids(path: Path) -> list:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output_dir", type=Path, help="Existing folder for the PDFs")
    parser.add_argument("order_file", type=Path, help="Text file with one order number per line")
    args = parser.parse_args()

    order_ids = read_order_ids(args.order_file)
    print(f"Saving {len(order_ids)} order(s) into {args.output_dir}")
    try:
        results = save_order_invoices(order_ids, args.output_dir)
    except NonInteractiveAuthRequired as e:
        print(f"Stopped: {e} Run refresh_session (or cookie_capture.py), then run this again.")
        return 1
    except ValueError as e:
        print(f"Nothing was saved: {e}")
        return 1

    counts = {"saved": 0, "skipped": 0, "error": 0}
    for r in results:
        counts[r["status"]] += 1
        detail = Path(r["path"]).name if r["status"] == "saved" else r["message"]
        print(f"{r['status']:8} {r['order_id']}  {detail}")
    print(f"\nSaved {counts['saved']}, skipped {counts['skipped']}, errors {counts['error']}")
    return 0 if counts["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
