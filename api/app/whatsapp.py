"""Meta WhatsApp Cloud API: send helpers, webhook signature check, inbound parsing.

With no WA_ACCESS_TOKEN set, messages go to `OUTBOX` instead of Meta (dry run), so the
whole flow can be developed and tested without a Meta account.
"""
import hashlib
import hmac
import logging

import httpx

from .config import settings

log = logging.getLogger("orderdesk.wa")
OUTBOX: list[dict] = []  # dry-run sink, inspected by tests


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    secret = settings.wa_app_secret
    if not secret:
        # No secret configured: only acceptable in dev.
        return settings.dev_mode
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def _send(phone_number_id: str, to: str, payload: dict) -> None:
    body = {"messaging_product": "whatsapp", "to": to, **payload}
    if not settings.wa_access_token:
        OUTBOX.append({"to": to, **payload})
        log.info("DRY-RUN to=%s %s", to, payload)
        return
    url = f"https://graph.facebook.com/{settings.wa_graph_version}/{phone_number_id}/messages"
    r = httpx.post(
        url, json=body, timeout=15, headers={"Authorization": f"Bearer {settings.wa_access_token}"}
    )
    if r.status_code >= 400:
        log.error("WhatsApp send failed %s %s", r.status_code, r.text)
        r.raise_for_status()


def send_text(phone_number_id: str, to: str, text: str) -> None:
    _send(phone_number_id, to, {"type": "text", "text": {"body": text}})


def send_buttons(phone_number_id: str, to: str, text: str, buttons: list[tuple[str, str]]) -> None:
    """buttons: [(id, title)], max 3, title max 20 chars (Meta limits)."""
    _send(
        phone_number_id,
        to,
        {
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": i, "title": t[:20]}} for i, t in buttons[:3]
                    ]
                },
            },
        },
    )


def send_cta_url(phone_number_id: str, to: str, text: str, label: str, url: str) -> None:
    """The 'Pay Now' button: opens a hosted page in WhatsApp's in-app browser."""
    _send(
        phone_number_id,
        to,
        {
            "type": "interactive",
            "interactive": {
                "type": "cta_url",
                "body": {"text": text},
                "action": {"name": "cta_url", "parameters": {"display_text": label[:20], "url": url}},
            },
        },
    )


def parse_inbound(payload: dict):
    """Yield dicts: phone_number_id, wa_id, name, message_id, kind (text|button), value."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            pnid = value.get("metadata", {}).get("phone_number_id", "")
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                kind, val = None, ""
                if m.get("type") == "text":
                    kind, val = "text", m["text"]["body"].strip()
                elif m.get("type") == "interactive":
                    br = m["interactive"].get("button_reply")
                    if br:
                        kind, val = "button", br["id"]
                if kind:
                    yield {
                        "phone_number_id": pnid,
                        "wa_id": m["from"],
                        "name": names.get(m["from"], ""),
                        "message_id": m["id"],
                        "kind": kind,
                        "value": val,
                    }
