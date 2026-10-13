import os


class Settings:
    """Read from environment on every access so tests can override."""

    @property
    def database_url(self) -> str:
        return os.getenv("DATABASE_URL", "sqlite:///./orderdesk.db")

    @property
    def base_url(self) -> str:
        return os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

    # Meta WhatsApp Cloud API
    @property
    def wa_access_token(self) -> str:
        return os.getenv("WA_ACCESS_TOKEN", "")

    @property
    def wa_verify_token(self) -> str:
        return os.getenv("WA_VERIFY_TOKEN", "change-me")

    @property
    def wa_app_secret(self) -> str:
        return os.getenv("WA_APP_SECRET", "")

    @property
    def wa_graph_version(self) -> str:
        return os.getenv("WA_GRAPH_VERSION", "v21.0")

    # Payments
    @property
    def payment_provider(self) -> str:
        return os.getenv("PAYMENT_PROVIDER", "mock")

    @property
    def quote_ttl_hours(self) -> int:
        return int(os.getenv("QUOTE_TTL_HOURS", "24"))

    @property
    def timezone(self) -> str:
        return os.getenv("TIMEZONE", "Africa/Kampala")

    @property
    def dev_mode(self) -> bool:
        return os.getenv("DEV_MODE", "1") == "1"

    @property
    def demo_mode(self) -> bool:
        """Turns on the /demo chat simulator. Off unless DEMO_MODE=1."""
        return os.getenv("DEMO_MODE", "0") == "1"


settings = Settings()
