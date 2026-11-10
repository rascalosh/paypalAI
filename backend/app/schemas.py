from datetime import date
from decimal import Decimal

from pydantic import BaseModel


# --- What the LLM returns. Numbers are strings so no float ever exists; no defaults
# --- because Structured Outputs requires every field to be present.
class LLMLineItem(BaseModel):
    name: str
    quantity: str
    unit_price: str


class LLMInvoice(BaseModel):
    recipient_email: str | None
    recipient_name: str | None
    currency: str | None
    due_date: str | None
    items: list[LLMLineItem]
    stated_total: str | None
    note: str | None


# --- Validated draft: every amount below was computed in Python.
class LineItem(BaseModel):
    name: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class InvoiceDraft(BaseModel):
    recipient_email: str | None
    recipient_name: str | None
    currency: str
    due_date: date | None
    items: list[LineItem]
    total: Decimal
    note: str | None
