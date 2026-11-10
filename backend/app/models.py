import secrets
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class SettlementStatus(StrEnum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    paypal_invoice_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    parent_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    recipient_email: Mapped[str] = mapped_column(String(254))
    recipient_name: Mapped[str | None] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    # [{name, quantity, unit_price}] with numbers as strings: JSON has no Decimal
    items: Mapped[list] = mapped_column(JSON)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default=InvoiceStatus.DRAFT, index=True)
    payer_url: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    # Seller negotiation bounds, enforced in Python before any option is saved or shown.
    max_discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("10.00"))
    max_installments: Mapped[int] = mapped_column(default=2)
    max_extension_days: Mapped[int] = mapped_column(default=14)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SettlementSession(Base):
    __tablename__ = "settlement_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: secrets.token_urlsafe(16))
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    options: Mapped[list] = mapped_column(JSON)
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=SettlementStatus.OPEN)
    accepted_option: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    # PayPal event id as primary key: the constraint is the dedupe.
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
