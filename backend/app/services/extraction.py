"""AI intake: chat text or a screenshot -> validated InvoiceDraft.

The LLM only reads quantity and unit_price off the source. Every total is
recomputed here in Decimal, and a total written in the source must match.
"""
import base64
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from openai import OpenAI

from app.config import settings
from app.schemas import InvoiceDraft, LineItem, LLMInvoice
from app.services.paypal_client import CENT

SYSTEM_PROMPT = """You extract invoice details from a seller's chat message or screenshot.
Today is {today}.
Rules:
- quantity and unit_price are plain decimal strings ("3", "49.99"): no currency symbols, no thousands separators.
- unit_price is the price of ONE unit. If only a line total is given for several units, set quantity "1" and unit_price to that line total.
- Never calculate anything. stated_total is the grand total exactly as written in the source, or null if none is written.
- due_date is ISO YYYY-MM-DD (resolve relative dates against today), or null.
- currency is the ISO 4217 code, or null if not stated.
- Use null for anything not present. Do not invent an email address."""


class ExtractionError(ValueError):
    pass


def _decimal(raw: str, field: str) -> Decimal:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, AttributeError):
        raise ExtractionError(f"{field} is not a number: {raw!r}") from None
    if not value.is_finite():
        raise ExtractionError(f"{field} is not a number: {raw!r}")
    return value


def build_draft(raw: LLMInvoice) -> InvoiceDraft:
    if not raw.items:
        raise ExtractionError("no line items found")
    items = []
    for i in raw.items:
        quantity = _decimal(i.quantity, "quantity")
        # Round the unit price first: PayPal only accepts 2 decimals, so our total must be built from the same number.
        unit_price = _decimal(i.unit_price, "unit_price").quantize(CENT, rounding=ROUND_HALF_UP)
        if quantity <= 0:
            raise ExtractionError(f"quantity must be positive for {i.name!r}")
        if unit_price < 0:
            raise ExtractionError(f"unit_price must not be negative for {i.name!r}")
        items.append(LineItem(
            name=i.name.strip(), quantity=quantity, unit_price=unit_price,
            line_total=(quantity * unit_price).quantize(CENT, rounding=ROUND_HALF_UP),
        ))
    total = sum((i.line_total for i in items), Decimal("0.00"))

    if raw.stated_total is not None:
        stated = _decimal(raw.stated_total, "stated_total").quantize(CENT, rounding=ROUND_HALF_UP)
        if stated != total:
            raise ExtractionError(f"stated total {stated} does not match computed total {total}")

    due_date = None
    if raw.due_date:
        try:
            due_date = date.fromisoformat(raw.due_date)
        except ValueError:
            raise ExtractionError(f"due_date is not a date: {raw.due_date!r}") from None

    currency = (raw.currency or "USD").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ExtractionError(f"currency is not an ISO code: {raw.currency!r}")

    return InvoiceDraft(
        recipient_email=(raw.recipient_email or "").strip() or None,
        recipient_name=(raw.recipient_name or "").strip() or None,
        currency=currency, due_date=due_date, items=items, total=total, note=raw.note,
    )


def _llm(content: list[dict]) -> LLMInvoice:
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)
    r = client.chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(today=date.today().isoformat())},
            {"role": "user", "content": content},
        ],
        response_format=LLMInvoice,
    )
    msg = r.choices[0].message
    if msg.parsed is None:
        raise ExtractionError(msg.refusal or "model returned no structured output")
    return msg.parsed


def extract_invoice(text: str | None = None, image: bytes | None = None,
                    image_mime: str = "image/png") -> InvoiceDraft:
    content: list[dict] = []
    if text and text.strip():
        content.append({"type": "text", "text": text})
    if image:
        b64 = base64.b64encode(image).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{b64}"}})
    if not content:
        raise ExtractionError("provide text or an image")
    return build_draft(_llm(content))
