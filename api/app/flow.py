"""Level 2 Order Taker: menu -> pick -> confirm -> quote with Pay Now button.

Plain state machine, no LLM. Per-business wording comes from Business.config.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import whatsapp as wa
from .config import settings
from .db import Business, Contact, Deal, Message, Offering

RESET_WORDS = {"hi", "hello", "hey", "menu", "start", "restart"}


def _offerings(db, business_id):
    return list(
        db.scalars(
            select(Offering)
            .where(Offering.business_id == business_id, Offering.active.is_(True))
            .order_by(Offering.id)
        )
    )


def _menu_text(biz: Business, items: list[Offering]) -> str:
    greeting = biz.config.get("greeting", f"Welcome to {biz.name}!")
    lines = [f"{i}. {o.name} - {biz.currency} {o.price:,}" for i, o in enumerate(items, 1)]
    return (
        f"{greeting}\n\n" + "\n".join(lines) + "\n\nReply with the number you want, "
        "e.g. 2, or 2x3 for three of item 2."
    )


def _parse_choice(text: str, n_items: int):
    m = re.fullmatch(r"\s*(\d+)\s*(?:[x*,]\s*|\s+)?(\d+)?\s*", text.lower())
    if not m:
        return None
    idx, qty = int(m.group(1)), int(m.group(2) or 1)
    if not (1 <= idx <= n_items) or not (1 <= qty <= 99):
        return None
    return idx, qty


def _new_ref(db) -> str:
    while True:
        ref = f"OD-{secrets.randbelow(10**7):07d}"
        if not db.scalar(select(Deal).where(Deal.quote_ref == ref)):
            return ref


def handle_inbound(db, m: dict) -> None:
    biz = db.scalar(select(Business).where(Business.wa_phone_number_id == m["phone_number_id"]))
    if not biz:
        return
    contact = db.scalar(
        select(Contact).where(Contact.business_id == biz.id, Contact.wa_id == m["wa_id"])
    )
    if not contact:
        contact = Contact(business_id=biz.id, wa_id=m["wa_id"], name=m["name"])
        db.add(contact)
        db.flush()
    # idempotency: Meta redelivers webhooks
    try:
        db.add(Message(wa_message_id=m["message_id"], contact_id=contact.id, body=m["value"]))
        db.flush()
    except IntegrityError:
        db.rollback()
        return

    pnid, to = biz.wa_phone_number_id, contact.wa_id
    items = _offerings(db, biz.id)

    def show_menu():
        contact.state, contact.draft = "choosing", {}
        wa.send_text(pnid, to, _menu_text(biz, items))

    if m["kind"] == "text" and (m["value"].lower() in RESET_WORDS or contact.state == "idle"):
        show_menu()

    elif contact.state == "choosing" and m["kind"] == "text":
        choice = _parse_choice(m["value"], len(items))
        if not choice:
            wa.send_text(pnid, to, "Sorry, I didn't get that. Reply with an item number, e.g. 2 or 2x3.")
        else:
            o = items[choice[0] - 1]
            contact.draft = {"offering_id": o.id, "qty": choice[1]}
            contact.state = "confirming"
            total = o.price * choice[1]
            wa.send_buttons(
                pnid, to,
                f"{choice[1]} x {o.name}\nTotal: {biz.currency} {total:,}\n\nShall I prepare your quote?",
                [("confirm", "Yes, go ahead"), ("cancel", "No")],
            )

    elif contact.state == "confirming" and m["kind"] == "button" and m["value"] == "confirm":
        o = db.get(Offering, contact.draft["offering_id"])
        qty = contact.draft["qty"]
        deal = Deal(
            business_id=biz.id,
            contact_id=contact.id,
            type="order",
            stage="awaiting_payment",
            items=[{"offering_id": o.id, "name": o.name, "qty": qty, "unit_price": o.price}],
            total=o.price * qty,
            quote_ref=_new_ref(db),
            pay_token=secrets.token_urlsafe(24),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.quote_ttl_hours),
        )
        db.add(deal)
        contact.state, contact.draft = "idle", {}
        db.flush()
        wa.send_cta_url(
            pnid, to,
            f"Your quote {deal.quote_ref} is ready.\n\nTotal: {biz.currency} {deal.total:,}\n"
            f"Valid for {settings.quote_ttl_hours} hours.\n\nTap Pay Now to confirm.",
            "Pay Now",
            f"{settings.base_url}/pay/{deal.pay_token}",
        )

    elif contact.state == "confirming" and m["kind"] == "button" and m["value"] == "cancel":
        contact.state, contact.draft = "idle", {}
        wa.send_text(pnid, to, "No problem, cancelled. Send 'menu' any time to start again.")

    else:
        show_menu()
    db.commit()
