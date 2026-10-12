from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProviderResult:
    provider_ref: str
    status: str  # pending | succeeded | failed


class PaymentProvider(ABC):
    """Every gateway (push, card, manual) implements these three methods.

    Rules the core enforces regardless of provider:
      * money is only marked paid after `verify()` says succeeded (never from a redirect)
      * the verified amount must equal the deal total
      * marking paid is idempotent
    """

    name: str

    @abstractmethod
    def request_payment(self, amount: int, msisdn: str, reference: str) -> ProviderResult:
        """Trigger the prompt on the customer's phone. Returns a pending result."""

    @abstractmethod
    def verify(self, provider_ref: str) -> ProviderResult:
        """Ask the provider directly for the transaction's true status."""

    @abstractmethod
    def parse_webhook(self, headers: dict, body: bytes) -> str | None:
        """Authenticate the webhook and return the provider_ref it is about, or None if invalid.
        The caller then calls verify(); the webhook body itself is never trusted for status."""
