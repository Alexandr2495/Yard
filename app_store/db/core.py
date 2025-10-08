# -*- coding: utf-8 -*-
import os
from datetime import datetime, UTC

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import (
    String, Integer, BigInteger, Boolean, DateTime, Text, JSON,
    UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import JSONB

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("Set DATABASE_URL in .env (e.g. postgresql+asyncpg://user:pass@host/db)")

# --- SQLAlchemy base / session ---
class Base(AsyncAttrs, DeclarativeBase):
    pass

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)

# --- Models ---
class ChannelMessage(Base):
    __tablename__ = "channel_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(400), default=None)
    text_len: Mapped[int | None] = mapped_column(Integer, default=None)
    edited_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("channel_id", "message_id", name="uq_channel_msg"),
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(400), nullable=False)
    key: Mapped[str]  = mapped_column(String(400), nullable=False)

    available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    price_retail: Mapped[int | None] = mapped_column(BigInteger, default=None)
    price_wholesale: Mapped[int | None] = mapped_column(BigInteger, default=None)

    category: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    requires_serial: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- новые поля для Б/У и характеристик ---
    is_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    extra_attrs: Mapped[dict | None] = mapped_column(JSON, default=None)
    condition_note: Mapped[str | None] = mapped_column(Text, default=None)

    __table_args__ = (
        # уникальность теперь включает is_used
        UniqueConstraint("channel_id", "group_message_id", "key", "is_used", name="uq_prod_key_in_group"),
        Index("ix_products_lookup", "key", "available"),
        Index("ix_products_name", "name"),
        Index("ix_products_is_used", "is_used", "available"),
        Index("ix_products_key_used", "key", "is_used"),
    )


async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class MonitoredPost(Base):
    __tablename__ = "monitored_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    is_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    category: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("channel_id", "message_id", name="uq_monitored_post"),
        Index("ix_monitored_posts_channel", "channel_id", "is_active"),
    )


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)  # Описание для пользователя
    category: Mapped[str | None] = mapped_column(String(50), default=None)  # Категория настройки
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))

class BotAdmin(Base):
    __tablename__ = "bot_admins"
    
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(100), default=None)
    full_name: Mapped[str | None] = mapped_column(String(200), default=None)
    added_by: Mapped[int] = mapped_column(BigInteger, nullable=False)  # Кто добавил
    added_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False, default='wholesale')  # wholesale или retail


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), default=None)

    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(400), nullable=False)

    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price_each: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_price: Mapped[int] = mapped_column(BigInteger, nullable=False)

    order_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'retail' | 'wholesale'
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    serial_number: Mapped[str | None] = mapped_column(String(100), default=None)
    
    # Дополнительные поля для менеджерского флоу
    photo_file_id: Mapped[str | None] = mapped_column(String(255), default=None)
    serial_text: Mapped[str | None] = mapped_column(Text, default=None)
    decision_message_id: Mapped[int | None] = mapped_column(Integer, default=None)
    manager_id: Mapped[int | None] = mapped_column(BigInteger, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class Cart(Base):
    __tablename__ = "carts"
    
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    items_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    
    def __repr__(self):
        return f"<Cart(user_id={self.user_id}, items_count={len(self.items_json)})>"
    
    @property
    def items(self) -> list[dict]:
        """Get cart items as a list of dictionaries"""
        return self.items_json.get('items', [])
    
    @items.setter
    def items(self, value: list[dict]):
        """Set cart items from a list of dictionaries"""
        self.items_json = {'items': value}


class UserConsent(Base):
    """Таблица для хранения согласий пользователей на обработку ПД"""
    __tablename__ = "user_consents"
    
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(100), default=None)
    
    # Основное согласие на обработку ПД
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_date: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    consent_version: Mapped[str] = mapped_column(String(10), default="1.0")  # Версия политики
    
    # Согласие на маркетинговые рассылки
    marketing_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    marketing_consent_date: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    
    # Отзыв согласия
    consent_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revocation_date: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    revocation_reason: Mapped[str | None] = mapped_column(Text, default=None)
    
    # IP адрес и User-Agent для доказательства
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None)
    user_agent: Mapped[str | None] = mapped_column(Text, default=None)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class PrivacyPolicy(Base):
    """Версии политики конфиденциальности"""
    __tablename__ = "privacy_policies"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

