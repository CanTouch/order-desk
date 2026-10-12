"""Money logic. Deliberately plain code: no LLM anywhere near this file."""
from datetime import datetime, timezone

from sqlalchemy import select

from . import whatsapp as wa
from .db import Deal, Payment
from .payments import get_provider


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_expired(deal: Deal) -> bool:
    return _aware(deal.expires_at) < datetime.now(timezone.utc)


def start_push(db, deal: Deal, msisdn: str) -> Payment:
    if deal.stage == "paid":
        raise ValueError("already paid")
    if is_expired(deal):
        raise ValueError("quote expired")
    # one live attempt at a time: reuse a pending payment instead of double-prompting
    existing = db.scalar(
        select(Payment).where(Payment.deal_id == deal.id, Payment.status == "pending")
    )
    if existing:
        return existing
    provider = get_provider()
    res = provider.request_payment(deal.total, msisdn, deal.quote_ref)
    pay = Payment(
        deal_id=deal.id,
        provider=provider.name,
        provider_ref=res.provider_ref,
        status="pending",
        amount=deal.total,
        msisdn=msisdn,
    )
    db.add(pay)
    db.commit()
    return pay


def settle(db, pay: Payment) -> Payment:
    """Verify with the provider and update state. Safe to call repeatedly (poll + webhook)."""
    if pay.status != "pending":
        return pay
    res = get_provider(pay.provider).verify(pay.provider_ref)
    if res.status == "succeeded":
        mark_paid(db, pay)
    elif res.status == "failed":
        pay.status = "failed"
        db.commit()
    return pay


def mark_paid(db, pay: Payment) -> None:
    deal = pay.deal
    if pay.status == "succeeded" and deal.stage == "paid":
        return  # idempotent
    if pay.amount != deal.total:
        pay.status = "failed"  # amount mismatch is never accepted silently
        db.commit()
        return
    pay.status = "succeeded"
    first_time = deal.stage != "paid"
    deal.stage = "paid"
    db.commit()
    if first_time:
        wa.send_text(
            deal.business.wa_phone_number_id,
            deal.contact.wa_id,
            f"Payment received: {deal.business.currency} {deal.total:,} for {deal.quote_ref}. "
            f"Thank you! We're getting your order ready.",
        )
