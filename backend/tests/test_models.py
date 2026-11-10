from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Invoice, InvoiceStatus, SettlementSession, SettlementStatus, WebhookEvent


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _invoice(**kw) -> Invoice:
    return Invoice(recipient_email="buyer@example.com",
                   items=[{"name": "Design", "quantity": "1", "unit_price": "1234.56"}],
                   total=Decimal("1234.56"), **kw)


def test_invoice_round_trip_and_parent_link(db):
    parent = _invoice()
    db.add(parent)
    db.commit()
    child = _invoice(parent_invoice_id=parent.id)
    db.add(child)
    db.commit()
    db.expire_all()

    assert parent.total == Decimal("1234.56") and isinstance(parent.total, Decimal)
    assert parent.status == InvoiceStatus.DRAFT
    assert (parent.max_discount_pct, parent.max_installments, parent.max_extension_days) == (Decimal("10.00"), 2, 14)
    assert child.parent_invoice_id == parent.id


def test_settlement_session_gets_unique_token(db):
    inv = _invoice()
    db.add(inv)
    db.commit()
    a = SettlementSession(invoice_id=inv.id, options=[])
    b = SettlementSession(invoice_id=inv.id, options=[])
    db.add_all([a, b])
    db.commit()
    assert a.token and a.token != b.token
    assert a.status == SettlementStatus.OPEN


def test_webhook_event_id_dedupes(db):
    db.add(WebhookEvent(event_id="WH-1", event_type="INVOICING.INVOICE.PAID", payload={}))
    db.commit()
    db.add(WebhookEvent(event_id="WH-1", event_type="INVOICING.INVOICE.PAID", payload={}))
    with pytest.raises(IntegrityError):
        db.commit()
