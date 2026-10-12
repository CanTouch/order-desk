"""Flutterwave Uganda mobile-money push adapter: NOT IMPLEMENTED YET.

Before writing this, confirm in Flutterwave's docs / with their support:
  1. Does an unregistered (individual) Ugandan account get mobile money collections?
  2. Does the charge pop the MTN/Airtel prompt directly, or redirect to an auth page?
  3. How is the webhook authenticated (secret-hash header) and which verify endpoint to call?
Fill in request_payment / verify / parse_webhook per PaymentProvider once those are answered.
Same checklist applies to a Relworx adapter (fees, KYC, webhook auth).
"""
from .base import PaymentProvider


class FlutterwaveProvider(PaymentProvider):
    name = "flutterwave"

    def request_payment(self, amount, msisdn, reference):
        raise NotImplementedError

    def verify(self, provider_ref):
        raise NotImplementedError

    def parse_webhook(self, headers, body):
        raise NotImplementedError
