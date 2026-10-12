import json
import uuid

from .base import PaymentProvider, ProviderResult


class MockProvider(PaymentProvider):
    """Simulates a mobile-money push. Dev/test only.

    request_payment -> pending. A test (or the /dev/mock/approve endpoint) calls `approve`
    or `reject`, as if the customer entered their PIN or declined on their phone.
    """

    name = "mock"
    _txns: dict[str, dict] = {}

    def request_payment(self, amount: int, msisdn: str, reference: str) -> ProviderResult:
        ref = f"mock_{uuid.uuid4().hex[:12]}"
        self._txns[ref] = {"status": "pending", "amount": amount, "msisdn": msisdn}
        return ProviderResult(ref, "pending")

    def verify(self, provider_ref: str) -> ProviderResult:
        t = self._txns.get(provider_ref)
        return ProviderResult(provider_ref, t["status"] if t else "failed")

    def parse_webhook(self, headers: dict, body: bytes) -> str | None:
        try:
            ref = json.loads(body).get("provider_ref")
        except Exception:
            return None
        return ref if ref in self._txns else None

    # simulation helpers
    def approve(self, ref: str):
        self._txns[ref]["status"] = "succeeded"

    def reject(self, ref: str):
        self._txns[ref]["status"] = "failed"
