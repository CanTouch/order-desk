"""Chat simulator for demos when Meta is not reachable. Enabled only with DEMO_MODE=1.

It runs the real bot flow (flow.handle_inbound), the real checkout page and the real paid-order
logic. Only the transport differs: messages to "demo-..." recipients stay in memory and are drawn
on this page instead of going to WhatsApp. The payment is the mock provider.
"""
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from . import whatsapp as wa
from .config import settings
from .db import Business, Contact, Deal, Payment, get_session
from .flow import handle_inbound
from .payments import get_provider
from .service import settle

router = APIRouter()


def _guard():
    if not settings.demo_mode:
        raise HTTPException(404)


def _session(raw: str) -> str:
    sid = (raw or "").strip()
    if not sid.startswith("demo-") or not (6 <= len(sid) <= 30) or not sid[5:].isalnum():
        raise HTTPException(400, "bad session")
    return sid


def _drain(sid: str) -> dict:
    out = {}
    for key, box_id in (("customer", sid), ("seller", "sellerdemo-" + sid)):
        out[key] = wa.DEMO_BOXES.pop(box_id, [])
    return out


@router.get("/demo", response_class=HTMLResponse)
def demo_page():
    _guard()
    return PAGE


@router.post("/demo/send")
async def demo_send(request: Request):
    _guard()
    body = await request.json()
    sid = _session(body.get("session"))
    kind = body.get("kind")
    if kind not in ("text", "button"):
        raise HTTPException(400, "bad kind")
    db = get_session()
    try:
        biz = db.scalar(select(Business).order_by(Business.id))
        if not biz:
            raise HTTPException(409, "no business seeded")
        handle_inbound(
            db,
            {
                "phone_number_id": biz.wa_phone_number_id,
                "wa_id": sid,
                "name": "Demo customer",
                "message_id": "demo-" + uuid.uuid4().hex,
                "kind": kind,
                "value": str(body.get("value", ""))[:500],
            },
        )
    finally:
        db.close()
    return _drain(sid)


@router.get("/demo/poll")
def demo_poll(session: str):
    _guard()
    return _drain(_session(session))


@router.post("/demo/approve")
async def demo_approve(request: Request):
    """Stands in for the customer entering their PIN on the phone (mock provider only)."""
    _guard()
    sid = _session((await request.json()).get("session"))
    db = get_session()
    try:
        pay = db.scalar(
            select(Payment)
            .join(Deal, Payment.deal_id == Deal.id)
            .join(Contact, Deal.contact_id == Contact.id)
            .where(Contact.wa_id == sid, Payment.status == "pending")
            .order_by(Payment.id.desc())
        )
        if not pay:
            raise HTTPException(409, "no pending payment: tap Pay Now and start the payment first")
        if pay.provider != "mock":
            raise HTTPException(409, "approval is only simulated for the mock provider")
        get_provider("mock").approve(pay.provider_ref)
        settle(db, pay)
    finally:
        db.close()
    return _drain(sid)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Order Desk demo</title>
<style>
:root{--bg:#efeae2;--me:#d9fdd3;--bot:#fff;--head:#075e54;--ink:#111b21;--mute:#667781;--line:#d1d7db}
*{box-sizing:border-box}
body{margin:0;background:#e5ddd5;color:var(--ink);font:16px/1.4 system-ui,sans-serif;display:flex;justify-content:center}
.wrap{width:100%;max-width:460px;min-height:100vh;display:flex;flex-direction:column;background:var(--bg)}
.banner{background:#fff3cd;color:#664d03;font-size:13px;padding:8px 16px;text-align:center}
header{background:var(--head);color:#fff;padding:12px 16px;display:flex;justify-content:space-between;align-items:center}
header b{display:block}header small{opacity:.8}
.tabs{display:flex;background:#fff;border-bottom:1px solid var(--line)}
.tabs button{flex:1;padding:10px;border:0;background:none;font:inherit;color:var(--mute);border-bottom:3px solid transparent;cursor:pointer}
.tabs button.on{color:var(--head);border-color:var(--head);font-weight:600}
.chat{flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-direction:column;gap:8px}
.m{max-width:85%;padding:8px 10px;border-radius:8px;white-space:pre-wrap;word-wrap:break-word;box-shadow:0 1px 1px rgba(0,0,0,.12)}
.m.bot{background:var(--bot);align-self:flex-start}.m.me{background:var(--me);align-self:flex-end}
.btns{display:flex;flex-direction:column;gap:6px;margin-top:8px;border-top:1px solid var(--line);padding-top:6px}
.btns button,.btns a{display:block;text-align:center;padding:8px;border:0;background:none;color:#027eb5;font:inherit;font-weight:600;text-decoration:none;cursor:pointer}
.empty{color:var(--mute);text-align:center;margin-top:24px;font-size:14px}
form{display:flex;gap:8px;padding:10px 12px;background:#f0f2f5}
input{flex:1;padding:11px 14px;border:1px solid var(--line);border-radius:22px;font:inherit}
.send{background:var(--head);color:#fff;border:0;border-radius:22px;padding:0 18px;font:inherit;cursor:pointer}
.tools{padding:8px 12px;background:#f0f2f5;border-top:1px solid var(--line);display:flex;gap:8px;align-items:center;font-size:13px;color:var(--mute)}
.tools button{padding:8px 12px;border:1px solid var(--head);background:#fff;color:var(--head);border-radius:8px;font:inherit;cursor:pointer}
</style></head><body><div class="wrap">
<div class="banner">Simulator. No real WhatsApp and no real money. The payment is a test.</div>
<header><div><b>Demo Shop</b><small>Order Desk bot</small></div><small id="who"></small></header>
<div class="tabs"><button id="t1" class="on">Customer phone</button><button id="t2">Seller phone</button></div>
<div class="chat" id="c1"><div class="empty">Type <b>hi</b> to start.</div></div>
<div class="chat" id="c2" hidden><div class="empty">The seller alert appears here after a payment.</div></div>
<div class="tools"><span>After the payment page shows "waiting":</span><button id="approve">Approve payment (test)</button></div>
<form id="f"><input id="i" autocomplete="off" placeholder="Type a message"><button class="send">Send</button></form>
</div><script>
const sid="demo-"+Math.random().toString(16).slice(2,10);
document.getElementById("who").textContent=sid;
const $=id=>document.getElementById(id);
function bubble(box,cls,text){const d=document.createElement("div");d.className="m "+cls;d.textContent=text;box.append(d);return d}
function clearEmpty(box){const e=box.querySelector(".empty");if(e)e.remove()}
function draw(msgs,box){
  for(const p of msgs){clearEmpty(box);
    if(p.type==="text"){bubble(box,"bot",p.text.body)}
    else if(p.type==="interactive"){const it=p.interactive,d=bubble(box,"bot",it.body.text),w=document.createElement("div");w.className="btns";
      if(it.type==="button"){for(const b of it.action.buttons){const x=document.createElement("button");x.textContent=b.reply.title;
        x.onclick=()=>send("button",b.reply.id,b.reply.title);w.append(x)}}
      else if(it.type==="cta_url"){const a=document.createElement("a");a.textContent=it.action.parameters.display_text;a.href=it.action.parameters.url;a.target="_blank";a.rel="noopener";w.append(a)}
      d.append(w)}}
  box.scrollTop=box.scrollHeight}
function render(r){draw(r.customer||[],$("c1"));draw(r.seller||[],$("c2"));if((r.seller||[]).length)$("t2").textContent="Seller phone (1 new)"}
async function post(url,body){const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!r.ok){const e=await r.json().catch(()=>({}));alert(e.detail||"Something went wrong");return{}}return r.json()}
async function send(kind,value,label){clearEmpty($("c1"));bubble($("c1"),"me",label||value);$("c1").scrollTop=$("c1").scrollHeight;
  render(await post("/demo/send",{session:sid,kind,value}))}
$("f").onsubmit=e=>{e.preventDefault();const v=$("i").value.trim();if(!v)return;$("i").value="";send("text",v)};
$("approve").onclick=async()=>render(await post("/demo/approve",{session:sid}));
$("t1").onclick=()=>{$("c1").hidden=false;$("c2").hidden=true;$("t1").className="on";$("t2").className=""};
$("t2").onclick=()=>{$("c1").hidden=true;$("c2").hidden=false;$("t2").className="on";$("t1").className="";$("t2").textContent="Seller phone"};
setInterval(async()=>{try{render(await (await fetch("/demo/poll?session="+sid)).json())}catch(e){}},1500);
</script></body></html>"""
