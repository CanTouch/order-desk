import json
import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select

from . import whatsapp as wa
from .checkout_page import render
from .config import settings
from .db import Deal, Payment, get_session, init_db
from .flow import handle_inbound
from .payments import get_provider
from .service import is_expired, settle, start_push

log = logging.getLogger("orderdesk")
@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Order Desk", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True}


# ---- WhatsApp webhook -------------------------------------------------
@app.get("/webhook")
def wa_verify(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    if mode == "subscribe" and token == settings.wa_verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(403, "bad verify token")


@app.post("/webhook")
async def wa_inbound(request: Request):
    raw = await request.body()
    if not wa.verify_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403, "bad signature")
    payload = json.loads(raw or b"{}")
    db = get_session()
    try:
        for m in wa.parse_inbound(payload):
            try:
                handle_inbound(db, m)
            except Exception:  # never 500 to Meta: it would retry forever
                log.exception("failed handling inbound %s", m.get("message_id"))
                db.rollback()
    finally:
        db.close()
    return {"ok": True}


# ---- Hosted checkout --------------------------------------------------
def _deal(db, token: str) -> Deal:
    deal = db.scalar(select(Deal).where(Deal.pay_token == token))
    if not deal:
        raise HTTPException(404, "unknown payment link")
    return deal


def normalize_msisdn(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("0") and len(d) == 10:
        d = "256" + d[1:]
    if not (d.startswith("256") and len(d) == 12):
        raise ValueError("Enter a valid Ugandan number, e.g. 0772123456")
    return d


@app.get("/pay/{token}", response_class=HTMLResponse)
def pay_page(token: str):
    db = get_session()
    try:
        return render(_deal(db, token))
    finally:
        db.close()


@app.post("/pay/{token}/start")
async def pay_start(token: str, request: Request):
    body = await request.json()
    db = get_session()
    try:
        deal = _deal(db, token)
        try:
            pay = start_push(db, deal, normalize_msisdn(body.get("msisdn", "")))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"status": pay.status}
    finally:
        db.close()


@app.get("/pay/{token}/status")
def pay_status(token: str):
    db = get_session()
    try:
        deal = _deal(db, token)
        pay = db.scalar(
            select(Payment).where(Payment.deal_id == deal.id).order_by(Payment.id.desc())
        )
        if pay:
            settle(db, pay)  # server-side verify: the poll also covers a lost webhook
            db.refresh(deal)
        return {
            "stage": deal.stage,
            "payment": pay.status if pay else None,
            "expired": deal.stage != "paid" and is_expired(deal),
        }
    finally:
        db.close()


# ---- Provider webhook -------------------------------------------------
@app.post("/webhooks/payments/{provider}")
async def payment_webhook(provider: str, request: Request):
    raw = await request.body()
    try:
        prov = get_provider(provider)
    except ValueError:
        raise HTTPException(404, "unknown provider")
    ref = prov.parse_webhook(dict(request.headers), raw)
    if not ref:
        raise HTTPException(403, "invalid webhook")
    db = get_session()
    try:
        pay = db.scalar(select(Payment).where(Payment.provider == provider, Payment.provider_ref == ref))
        if pay:
            settle(db, pay)
    finally:
        db.close()
    return Response(status_code=200)


# ---- Dev helper -------------------------------------------------------
@app.post("/dev/mock/{ref}/{action}")
def dev_mock(ref: str, action: str):
    if not settings.dev_mode:
        raise HTTPException(404)
    prov = get_provider("mock")
    if action == "approve":
        prov.approve(ref)
    elif action == "reject":
        prov.reject(ref)
    else:
        raise HTTPException(400, "approve|reject")
    return {"ok": True}
