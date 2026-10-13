"""Money logic. Deliberately plain code: no LLM anywhere near this file."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from . import whatsapp as wa
from .db import Deal, Payment
from .payments import get_provider

log = logging.getLogger("orderdesk.service")


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
        notify_seller(deal)


def notify_seller(deal: Deal) -> None:
    """Tell the seller a paid order is waiting. Never raises: a failed alert must not undo a payment.

    The seller's WhatsApp number is business.config["seller_wa_id"] (digits, e.g. 2567XXXXXXXX).
    WhatsApp only delivers a free-form message if the seller wrote to this number in the last
    24 hours; outside that window Meta rejects it (error 131047) and we only log it.
    """
    biz = deal.business
    seller = (biz.config or {}).get("seller_wa_id")
    if not seller:
        log.warning("No seller_wa_id for business %s: seller not notified of %s", biz.id, deal.quote_ref)
        return
    lines = [f"{it['qty']} x {it['name']}" for it in (deal.items or [])]
    who = deal.contact.name or "Customer"
    text = (
        f"New paid order {deal.quote_ref}\n"
        + "\n".join(lines)
        + f"\nTotal: {biz.currency} {deal.total:,} (paid)\n"
        f"Customer: {who}, +{deal.contact.wa_id}"
    )
    try:
        wa.send_text(biz.wa_phone_number_id, seller, text)
    except Exception:
        log.exception("Seller alert failed for %s", deal.quote_ref)
