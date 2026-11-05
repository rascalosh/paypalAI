"""Create, send, inspect (and optionally cancel) a PayPal Sandbox invoice.

Run from backend/:  python scripts/test_paypal_sandbox.py --to buyer@example.com [--amount 125.00] [--cancel]
"""
import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.paypal_client import PayPalError, paypal  # noqa: E402


def show(label: str, inv: dict) -> None:
    detail = inv.get("detail", {})
    print(f"{label}: status={inv.get('status')} number={detail.get('invoice_number')} "
          f"total={inv.get('amount', {}).get('value')} {inv.get('amount', {}).get('currency_code')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="sandbox buyer email")
    ap.add_argument("--amount", default="125.00")
    ap.add_argument("--cancel", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        draft = paypal.create_draft_invoice(
            a.to, [{"name": "Paycord test service", "quantity": Decimal("1"), "unit_price": Decimal(a.amount)}])
        inv_id = draft["id"]
        print(f"created draft id={inv_id}")
        show("after create", paypal.get_invoice(inv_id))

        sent = paypal.send_invoice(inv_id)
        inv = paypal.get_invoice(inv_id)
        show("after send  ", inv)
        print("payer link:", inv.get("detail", {}).get("metadata", {}).get("recipient_view_url")
              or sent.get("href"))

        if a.cancel:
            paypal.cancel_invoice(inv_id)
            show("after cancel", paypal.get_invoice(inv_id))
    except PayPalError as e:
        print(f"FAILED status={e.status} debug_id={e.debug_id}\n{e.body}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
