from ..config import settings
from .base import PaymentProvider
from .mock import MockProvider

_providers: dict[str, PaymentProvider] = {}


def get_provider(name: str | None = None) -> PaymentProvider:
    name = name or settings.payment_provider
    if name not in _providers:
        if name == "mock":
            _providers[name] = MockProvider()
        elif name == "flutterwave":
            from .flutterwave import FlutterwaveProvider

            _providers[name] = FlutterwaveProvider()
        else:
            raise ValueError(f"unknown payment provider: {name}")
    return _providers[name]
