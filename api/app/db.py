from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    wa_phone_number_id: Mapped[str] = mapped_column(String(64), unique=True)
    currency: Mapped[str] = mapped_column(String(3), default="UGX")
    # per-business behaviour: greeting, payment_mode (push|code|manual), handoff rules...
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class Offering(Base):
    """Product, service, room, seat... anything a business sells inside WhatsApp."""

    __tablename__ = "offerings"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(String(160))
    price: Mapped[int] = mapped_column(Integer)  # whole UGX, never floats for money
    active: Mapped[bool] = mapped_column(default=True)


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("business_id", "wa_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    wa_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120), default="")
    state: Mapped[str] = mapped_column(String(32), default="idle")
    draft: Mapped[dict] = mapped_column(JSON, default=dict)


class Deal(Base):
    """One conversion: an order, booking, quote... `type` keeps the core vertical-agnostic."""

    __tablename__ = "deals"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    type: Mapped[str] = mapped_column(String(24), default="order")
    stage: Mapped[str] = mapped_column(String(24), default="awaiting_payment")
    items: Mapped[list] = mapped_column(JSON, default=list)
    total: Mapped[int] = mapped_column(Integer)
    quote_ref: Mapped[str] = mapped_column(String(32), unique=True)
    pay_token: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    contact: Mapped[Contact] = relationship()
    business: Mapped[Business] = relationship()


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("provider", "provider_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"))
    provider: Mapped[str] = mapped_column(String(24))
    provider_ref: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|succeeded|failed
    amount: Mapped[int] = mapped_column(Integer)
    msisdn: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deal: Mapped[Deal] = relationship()


class Message(Base):
    """Every inbound WhatsApp message id is stored once: Meta retries webhooks."""

    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    wa_message_id: Mapped[str] = mapped_column(String(128), unique=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    body: Mapped[str] = mapped_column(String(4000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


_engine = None
_Session = None


def init_db(url: str | None = None):
    global _engine, _Session
    url = url or settings.database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    _engine = create_engine(url, **kwargs)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session():
    if _Session is None:
        init_db()
    return _Session()
