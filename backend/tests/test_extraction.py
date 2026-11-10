from datetime import date
from decimal import Decimal

import pytest

from app.config import settings
from app.schemas import LLMInvoice, LLMLineItem
from app.services import extraction
from app.services.extraction import ExtractionError, build_draft, extract_invoice


def raw(items, stated_total=None, **kw) -> LLMInvoice:
    fields = dict(recipient_email="buyer@example.com", recipient_name=None, currency="USD",
                  due_date=None, note=None)
    fields.update(kw)
    return LLMInvoice(items=[LLMLineItem(name=n, quantity=q, unit_price=p) for n, q, p in items],
                      stated_total=stated_total, **fields)


def test_total_is_computed_in_python():
    d = build_draft(raw([("Logo", "1", "450"), ("Hosting", "3", "19.99")], stated_total="509.97",
                        due_date="2026-11-30"))
    assert [i.line_total for i in d.items] == [Decimal("450.00"), Decimal("59.97")]
    assert d.total == Decimal("509.97")
    assert d.due_date == date(2026, 11, 30)
    assert d.currency == "USD"


def test_rounding_is_half_up():
    # 1.5 * 33.33 = 49.995 -> 50.00 (banker's rounding would give 50.00 too, so pin 0.5 * 0.01)
    assert build_draft(raw([("Hours", "1.5", "33.33")])).total == Decimal("50.00")
    assert build_draft(raw([("Half", "0.5", "0.01")])).total == Decimal("0.01")
    # sub-cent unit prices are rounded before multiplying, matching what PayPal is sent
    assert build_draft(raw([("Unit", "3", "0.335")])).total == Decimal("1.02")


def test_missing_currency_defaults_to_usd():
    assert build_draft(raw([("A", "1", "1")], currency=None)).currency == "USD"


@pytest.mark.parametrize("items,kw", [
    ([("A", "2", "10")], {"stated_total": "25.00"}),   # LLM/source total disagrees with the math
    ([("A", "0", "10")], {}),                           # zero quantity
    ([("A", "1", "-5")], {}),                           # negative price
    ([("A", "1", "ten")], {}),                          # not a number
    ([("A", "NaN", "10")], {}),                         # Decimal accepts NaN; we must not
    ([], {}),                                           # nothing extracted
    ([("A", "1", "10")], {"due_date": "next friday"}),  # unresolved date
    ([("A", "1", "10")], {"currency": "dollars"}),
])
def test_bad_extractions_are_rejected(items, kw):
    with pytest.raises(ExtractionError):
        build_draft(raw(items, **kw))


def test_extract_invoice_sends_text_and_image(monkeypatch):
    seen = {}

    def fake_llm(content):
        seen["content"] = content
        return raw([("A", "2", "10")])

    monkeypatch.setattr(extraction, "_llm", fake_llm)
    d = extract_invoice(text="2 x A at $10", image=b"\x89PNG")
    assert d.total == Decimal("20.00")
    assert [p["type"] for p in seen["content"]] == ["text", "image_url"]
    assert seen["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_extract_invoice_needs_input():
    with pytest.raises(ExtractionError):
        extract_invoice(text="  ")


# --- live: the 5 chat fixtures from the Phase 2 "done when" ------------------
LIVE = [
    ("Bill maria@acme.test for 3 hours of consulting at $120/hr, due Nov 30 2026.",
     "360.00", "maria@acme.test"),
    ("hey can u invoice bob@shop.test — 2 logo concepts @ 250 each and 1 brand guide for 400. total 900",
     "900.00", "bob@shop.test"),
    ("Invoice lee@cafe.test: 12 bags of espresso beans, $18.50 a bag. Net 14.",
     "222.00", "lee@cafe.test"),
    ("Send ana@studio.test a bill. Website maintenance October — $1,250.00 flat. Plus 4 stock photos at $9.99.",
     "1289.96", "ana@studio.test"),
    ("pls charge tom@build.test 1.5 days on site at 480 per day and 35 for parking",
     "755.00", "tom@build.test"),
]


@pytest.mark.skipif(not settings.openai_api_key, reason="OPENAI_API_KEY not set")
@pytest.mark.parametrize("chat,total,email", LIVE)
def test_live_chat_fixtures(chat, total, email):
    d = extract_invoice(text=chat)
    assert d.total == Decimal(total)
    assert d.recipient_email == email
