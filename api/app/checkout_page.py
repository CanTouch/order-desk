from datetime import timezone
from html import escape
from zoneinfo import ZoneInfo

from .config import settings


def _local(dt):
    """Show times in the business's timezone (default Africa/Kampala), not UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(settings.timezone))

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pay {ref}</title>
<style>
:root{{--bg:#0b0b0b;--card:#161616;--line:#2a2a2a;--fg:#f2f2f2;--mut:#8a8a8a;--acc:#f5c518}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,sans-serif;padding:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin:0 auto 14px;max-width:460px}}
h1{{font-size:1.25rem;margin:8px auto 14px;max-width:460px}}.mut{{color:var(--mut);font-size:.85rem}}
.amt{{color:var(--acc);font-size:2rem;font-weight:700;text-align:center;margin:6px 0}}
.row{{display:flex;justify-content:space-between;padding:6px 0}}label{{display:block;margin:12px 0 6px}}
input{{width:100%;padding:12px;border-radius:10px;border:1px solid var(--line);background:#0f0f0f;color:var(--fg);font-size:1rem}}
button{{width:100%;margin-top:14px;padding:14px;border:0;border-radius:10px;background:var(--acc);color:#000;font-weight:700;font-size:1rem}}
button:disabled{{opacity:.5}}#msg{{margin-top:12px;text-align:center}}
</style></head><body>
<h1>Hi {name}, complete your payment</h1>
<div class="card"><div class="mut" style="text-align:center">AMOUNT DUE</div>
<div class="amt">{currency} {total}</div>
<div class="mut" style="text-align:center">Quote {ref} &middot; valid until {expires}</div></div>
<div class="card">{items}</div>
<div class="card" id="pay">
<b>Pay with mobile money</b>
<label for="msisdn">Phone number (MTN or Airtel)</label>
<input id="msisdn" inputmode="tel" value="{msisdn}">
<button id="go">Pay {currency} {total}</button>
<div id="msg" class="mut">You will get a prompt on your phone to approve.</div></div>
<script>
const T="{token}",msg=document.getElementById("msg"),go=document.getElementById("go");
function done(t){{msg.textContent=t;go.style.display="none"}}
async function poll(){{
  const r=await fetch("/pay/"+T+"/status");const s=await r.json();
  if(s.stage==="paid")return done("Payment received. You'll get a WhatsApp confirmation.");
  if(s.payment==="failed"){{go.disabled=false;msg.textContent="Payment was declined or failed. Try again.";return}}
  if(s.expired)return done("This quote has expired. Message us on WhatsApp for a new one.");
  setTimeout(poll,3000)}}
go.onclick=async()=>{{go.disabled=true;msg.textContent="Sending prompt to your phone...";
  const r=await fetch("/pay/"+T+"/start",{{method:"POST",headers:{{"Content-Type":"application/json"}},
    body:JSON.stringify({{msisdn:document.getElementById("msisdn").value}})}});
  const j=await r.json();if(!r.ok){{go.disabled=false;msg.textContent=j.detail||"Something went wrong";return}}
  msg.textContent="Confirming your payment... approve the prompt on your phone. This page updates automatically.";poll()}};
</script></body></html>"""


def render(deal) -> str:
    items = "".join(
        f'<div class="row"><span>{escape(i["name"])}</span><span>x {i["qty"]}</span></div>'
        for i in deal.items
    )
    return PAGE.format(
        ref=escape(deal.quote_ref),
        name=escape(deal.contact.name or "there"),
        currency=escape(deal.business.currency),
        total=f"{deal.total:,}",
        expires=_local(deal.expires_at).strftime("%a %d %b, %H:%M"),
        items=items,
        msisdn="+" + escape(deal.contact.wa_id),
        token=escape(deal.pay_token),
    )
