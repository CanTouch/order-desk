import pytest
from fastapi.testclient import TestClient

SID = "demo-abc12345"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/d.db")
    monkeypatch.setenv("DEV_MODE", "0")
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("WA_ACCESS_TOKEN", "dead-token")  # must never be used for demo recipients
    monkeypatch.delenv("WA_APP_SECRET", raising=False)
    from app import db as dbm, seed, whatsapp as wa
    from app.main import app

    dbm.init_db()
    seed.seed("TEST_PNID", "256700000001")
    wa.OUTBOX.clear()
    wa.DEMO_BOXES.clear()
    return TestClient(app)


def post(c, kind, value):
    r = c.post("/demo/send", json={"session": SID, "kind": kind, "value": value})
    assert r.status_code == 200, r.text
    return r.json()


def test_demo_off_by_default(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "0")
    assert client.get("/demo").status_code == 404
    assert client.post("/demo/send", json={"session": SID, "kind": "text", "value": "hi"}).status_code == 404


def test_demo_full_loop_without_meta(client, monkeypatch):
    import httpx

    def boom(*a, **k):
        raise AssertionError("demo traffic must never reach Meta")

    monkeypatch.setattr(httpx, "post", boom)
    assert "Simulator" in client.get("/demo").text
    assert "Phone case" in post(client, "text", "hi")["customer"][0]["text"]["body"]
    assert "Total" in post(client, "text", "2")["customer"][0]["interactive"]["body"]["text"]
    cta = post(client, "button", "confirm")["customer"][0]["interactive"]
    assert cta["type"] == "cta_url"
    token = cta["action"]["parameters"]["url"].split("/pay/")[1]
    assert client.get(f"/pay/{token}").status_code == 200
    assert client.post(f"/pay/{token}/start", json={"msisdn": "0772123456"}).json()["status"] == "pending"
    out = client.post("/demo/approve", json={"session": SID}).json()
    assert "Payment received" in out["customer"][0]["text"]["body"]
    assert "New paid order" in out["seller"][0]["text"]["body"]
    assert client.get(f"/pay/{token}/status").json()["stage"] == "paid"


def test_approve_needs_a_pending_payment(client):
    assert client.post("/demo/approve", json={"session": SID}).status_code == 409


def test_bad_session_rejected(client):
    r = client.post("/demo/send", json={"session": "256772123456", "kind": "text", "value": "hi"})
    assert r.status_code == 400
