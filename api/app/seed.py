"""Create a demo business + menu. Usage: python -m app.seed <wa_phone_number_id>"""
import sys

from .db import Business, Offering, get_session, init_db


def seed(phone_number_id: str = "TEST_PNID"):
    init_db()
    db = get_session()
    biz = Business(
        name="Demo Shop",
        wa_phone_number_id=phone_number_id,
        config={"greeting": "Hi! Welcome to Demo Shop."},
    )
    db.add(biz)
    db.flush()
    for name, price in [("Phone case", 25000), ("Wireless earbuds", 120000), ("Power bank 10000mAh", 85000)]:
        db.add(Offering(business_id=biz.id, name=name, price=price))
    db.commit()
    db.close()


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else "TEST_PNID")
