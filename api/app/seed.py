"""Create (or update) a demo business + menu.

Usage: python -m app.seed <wa_phone_number_id> [seller_wa_id]

seller_wa_id is the seller's own WhatsApp number in digits (e.g. 256786535249); paid-order
alerts go there. Safe to run again: an existing business is updated, not duplicated.
"""
import sys

from sqlalchemy import select

from .db import Business, Offering, get_session, init_db


def seed(phone_number_id: str = "TEST_PNID", seller_wa_id: str | None = None):
    init_db()
    db = get_session()
    biz = db.scalar(select(Business).where(Business.wa_phone_number_id == phone_number_id))
    if biz is None:
        biz = Business(
            name="Demo Shop",
            wa_phone_number_id=phone_number_id,
            config={"greeting": "Hi! Welcome to Demo Shop."},
        )
        db.add(biz)
        db.flush()
        for name, price in [("Phone case", 25000), ("Wireless earbuds", 120000), ("Power bank 10000mAh", 85000)]:
            db.add(Offering(business_id=biz.id, name=name, price=price))
    if seller_wa_id:
        biz.config = {**(biz.config or {}), "seller_wa_id": seller_wa_id.lstrip("+").replace(" ", "")}
    db.commit()
    db.close()


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else "TEST_PNID", sys.argv[2] if len(sys.argv) > 2 else None)
