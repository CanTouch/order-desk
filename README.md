# Order Desk (core)

WhatsApp deal engine for businesses that close sales inside WhatsApp.
Level 2 Order Taker + hosted Pay Now checkout + pluggable payment providers.

## Flow
chat (menu, pick, confirm) -> quote message with **Pay Now** button -> `/pay/<token>` page
-> mobile-money push to the customer's phone -> page polls `/pay/<token>/status`
-> provider verified server-side -> WhatsApp confirmation (sent once).

## Run locally (no Meta account, no gateway keys)
```
cd api
pip install -r requirements.txt
python -m pytest -q                      # 8 tests, full loop included
python -m app.seed TEST_PNID             # demo shop + menu
uvicorn app.main:app --reload
```
Messages go to a dry-run outbox until `WA_ACCESS_TOKEN` is set.

## Payment providers
`app/payments/base.py` defines `PaymentProvider` (request_payment, verify, parse_webhook).
- `mock.py`: simulates the push (dev/test)
- `flutterwave.py`: stub, see its docstring for the checks to do before implementing
Planned: Relworx, Pesapal (card, registered businesses), manual Code Pay / bank transfer.

## Money rules (enforced in `service.py`)
- Paid only after the provider's own verify call says succeeded; redirects/webhook bodies are never trusted
- Amount must equal the deal total; marking paid is idempotent; one live push per deal
- No LLM in this path

## Meta setup (when ready)
Webhook URL `https://<BASE_URL>/webhook`, verify token = `WA_VERIFY_TOKEN`, subscribe to `messages`.
Set `WA_ACCESS_TOKEN`, `WA_APP_SECRET`, `DEV_MODE=0`.

## Env notes
No inline comments in `.env` (Docker keeps them as part of the value).
- `DEV_MODE=0` on any public server (unsigned webhooks and /dev/mock only work with DEV_MODE=1)
- `PAYMENT_PROVIDER=mock` until a real provider adapter exists
- `WA_APP_SECRET` is required for webhooks to be accepted when DEV_MODE=0
