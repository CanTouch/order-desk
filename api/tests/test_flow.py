import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

PNID = "TEST_PNID"
CUSTOMER = "256772123456"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.delenv("WA_APP_SECRET", raising=False)
    monkeypatch.delenv("WA_ACCESS_TOKEN", raising=False)
    from app import db as dbm, seed, whatsapp as wa
    from app.main import app

    dbm.init_db()
    seed.seed(PNID)
    wa.OUTBOX.clear()
    return TestClient(app)


def inbound(msg_id, text=None, button=None):
    m = {"from": CUSTOMER, "id": msg_id}
    if text is not None:
        m.update(type="text", text={"body": text})
    else:
        m.update(type="interactive", interactive={"type": "button_reply", "button_reply": {"id": button, "title": "x"}})
    return {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": PNID},
            "contacts": [{"wa_id": CUSTOMER, "profile": {"name": "Daniel"}}],
            "messages": [m],
        }}]}]
    }


def send(client, **kw):
    r = client.post("/webhook", json=inbound(**kw))
    assert r.status_code == 200


def run_to_quote(client):
    from app import whatsapp as wa

    send(client, msg_id="m1", text="hi")
    assert "Phone case" in wa.OUTBOX[-1]["text"]["body"]
    send(client, msg_id="m2", text="2x3")
    assert "360,000" in wa.OUTBOX[-1]["interactive"]["body"]["text"]
    send(client, msg_id="m3", button="confirm")
    cta = wa.OUTBOX[-1]["interactive"]
    assert cta["type"] == "cta_url"
    return cta["action"]["parameters"]["url"].split("/pay/")[1]


def test_full_loop_push_paid(client):
    from app import whatsapp as wa
    from app.db import Payment, get_session

    token = run_to_quote(client)
    page = client.get(f"/pay/{token}")
    assert page.status_code == 200 and "360,000" in page.text and "+256772123456" in page.text

    r = client.post(f"/pay/{token}/start", json={"msisdn": "0772123456"})
    assert r.json()["status"] == "pending"
    assert client.get(f"/pay/{token}/status").json() == {"stage": "awaiting_payment", "payment": "pending", "expired": False}

    # double tap must not create a second prompt
    client.post(f"/pay/{token}/start", json={"msisdn": "0772123456"})
    db = get_session()
    pays = list(db.scalars(select(Payment)))
    assert len(pays) == 1
    ref = pays[0].provider_ref

    client.post(f"/dev/mock/{ref}/approve")  # customer enters PIN
    n_before = len(wa.OUTBOX)
    assert client.get(f"/pay/{token}/status").json()["stage"] == "paid"
    assert "Payment received" in wa.OUTBOX[-1]["text"]["body"]
    # webhook + further polls are idempotent: no second confirmation
    client.post("/webhooks/payments/mock", content=json.dumps({"provider_ref": ref}))
    client.get(f"/pay/{token}/status")
    assert len(wa.OUTBOX) == n_before + 1


def test_declined_then_retry(client):
    from app.db import Payment, get_session

    token = run_to_quote(client)
    client.post(f"/pay/{token}/start", json={"msisdn": "0772123456"})
    db = get_session()
    ref = db.scalar(select(Payment)).provider_ref
    client.post(f"/dev/mock/{ref}/reject")
    assert client.get(f"/pay/{token}/status").json()["payment"] == "failed"
    assert client.post(f"/pay/{token}/start", json={"msisdn": "0772123456"}).status_code == 200
    assert len(list(get_session().scalars(select(Payment)))) == 2


def test_expired_quote_rejected(client):
    from app.db import Deal, get_session

    token = run_to_quote(client)
    db = get_session()
    deal = db.scalar(select(Deal))
    deal.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    r = client.post(f"/pay/{token}/start", json={"msisdn": "0772123456"})
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    assert client.get(f"/pay/{token}/status").json()["expired"] is True


def test_bad_number_rejected(client):
    token = run_to_quote(client)
    assert client.post(f"/pay/{token}/start", json={"msisdn": "12345"}).status_code == 400


def test_duplicate_webhook_delivery_ignored(client):
    from app import whatsapp as wa

    send(client, msg_id="dup1", text="hi")
    n = len(wa.OUTBOX)
    send(client, msg_id="dup1", text="hi")
    assert len(wa.OUTBOX) == n


def test_signature_enforced(client, monkeypatch):
    monkeypatch.setenv("WA_APP_SECRET", "s3cret")
    body = json.dumps(inbound("sig1", text="hi")).encode()
    assert client.post("/webhook", content=body).status_code == 403
    good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert client.post("/webhook", content=body, headers={"x-hub-signature-256": good}).status_code == 200


def test_webhook_verify_handshake(client):
    r = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "change-me", "hub.challenge": "123"})
    assert r.text == "123"
    assert client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "1"}).status_code == 403


def test_cancel_path(client):
    from app import whatsapp as wa

    send(client, msg_id="c1", text="hi")
    send(client, msg_id="c2", text="1")
    send(client, msg_id="c3", button="cancel")
    assert "cancelled" in wa.OUTBOX[-1]["text"]["body"]


def test_page_shows_kampala_time_not_utc(client):
    from app.db import Deal, get_session

    token = run_to_quote(client)
    deal = get_session().scalar(select(Deal))
    exp = deal.expires_at if deal.expires_at.tzinfo else deal.expires_at.replace(tzinfo=timezone.utc)
    expected = (exp + timedelta(hours=3)).strftime("%H:%M")  # Kampala = UTC+3, no DST
    assert expected in client.get(f"/pay/{token}").text
