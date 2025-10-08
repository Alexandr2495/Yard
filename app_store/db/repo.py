from datetime import datetime, UTC
from typing import Iterable
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from .core import ChannelMessage, Product, Order

async def save_channel_message(
    s: AsyncSession,
    *,
    channel_id: int,
    message_id: int,
    title: str | None,
    text_len: int,
) -> None:
    # upsert по (channel_id, message_id)
    row = (await s.execute(
        select(ChannelMessage).where(
            ChannelMessage.channel_id == channel_id,
            ChannelMessage.message_id == message_id
        )
    )).scalar_one_or_none()

    now = datetime.now(UTC).replace(tzinfo=None)
    if row is None:
        s.add(ChannelMessage(
            channel_id=channel_id,
            message_id=message_id,
            title=title,
            text_len=text_len,
            edited_at=now
        ))
    else:
        row.title = title
        row.text_len = text_len
        row.edited_at = now

async def upsert_products_from_group(
    s: AsyncSession,
    *,
    channel_id: int,
    group_message_id: int,
    items: Iterable[tuple[str, int]],
    price_type: str = "retail",  # "retail" or "wholesale"
    category: str | None = None,
) -> None:
    """
    items: итератор кортежей (name, price).
    Объединяем товары по всему каналу по ключу, обновляем соответствующие цены.
    price_type: "retail" или "wholesale" - какой тип цены обновляем
    """
    # Соберём входные ключи
    normalized = []
    keys_new = set()
    for name, price in items:
        key = normalize_key(name)
        normalized.append((name.strip(), key, int(price)))
        keys_new.add(key)

    # Прочитаем ВСЕ товары в канале (не только в группе)
    existing = (await s.execute(
        select(Product).where(
            Product.channel_id == channel_id
        )
    )).scalars().all()

    existing_by_key = {p.key: p for p in existing}

    # upsert / reactivate
    now = datetime.now(UTC).replace(tzinfo=None)
    for name, key, price in normalized:
        if key in existing_by_key:
            # Товар уже существует - обновляем только нужную цену
            p = existing_by_key[key]
            p.name = name  # Обновляем название на случай изменений
            if price_type == "retail":
                p.price_retail = price
            else:  # wholesale
                p.price_wholesale = price
            if category:
                p.category = category
            p.available = True
            p.updated_at = now
        else:
            # Создаем новый товар
            product_data = {
                "group_message_id": group_message_id,
                "channel_id": channel_id,
                "name": name,
                "key": key,
                "available": True,
                "updated_at": now
            }
            if price_type == "retail":
                product_data["price_retail"] = price
                product_data["price_wholesale"] = None
            else:  # wholesale
                product_data["price_wholesale"] = price
                product_data["price_retail"] = None
            if category:
                product_data["category"] = category
            s.add(Product(**product_data))

    # НЕ деактивируем товары, так как они могут быть в других сообщениях

async def get_categories(s: AsyncSession, channel_id: int, price_type: str = "retail") -> list[str]:
    """Получить список всех категорий товаров для канала + типа цены"""
    price_field = Product.price_retail if price_type == "retail" else Product.price_wholesale
    result = await s.execute(
        select(Product.category).where(
            Product.channel_id == channel_id,
            Product.available == True,
            price_field != None,
            Product.category != None
        ).distinct()
    )
    return [cat for cat in result.scalars() if cat]
async def get_products_by_category(s: AsyncSession, channel_id: int, category: str, price_type: str = "retail") -> list[Product]:
    """Получить товары по категории для канала + типа цены"""
    price_field = Product.price_retail if price_type == "retail" else Product.price_wholesale
    result = await s.execute(
        select(Product).where(
            Product.channel_id == channel_id,
            Product.category == category,
            Product.available == True,
            price_field != None
        ).order_by(Product.name)
    )
    return list(result.scalars())
async def get_product_by_id(s: AsyncSession, product_id: int) -> Product | None:
    """Получить товар по ID"""
    result = await s.execute(
        select(Product).where(Product.id == product_id)
    )
    return result.scalar_one_or_none()

async def create_order(
    s: AsyncSession,
    *,
    user_id: int,
    username: str | None,
    product_id: int,
    product_name: str,
    quantity: int,
    price_each: int,
    order_type: str,
) -> Order:
    """Создать новый заказ"""
    total_price = price_each * quantity
    order = Order(
        user_id=user_id,
        username=username,
        product_id=product_id,
        product_name=product_name,
        quantity=quantity,
        price_each=price_each,
        total_price=total_price,
        order_type=order_type,
        status='pending'
    )
    s.add(order)
    return order

async def update_order_status(
    s: AsyncSession,
    order_id: int,
    status: str,
    reason: str | None = None,
    serial_number: str | None = None,
) -> bool:
    """Обновить статус заказа"""
    result = await s.execute(
        update(Order)
        .where(Order.id == order_id)
        .values(
            status=status,
            reason=reason,
            serial_number=serial_number,
            updated_at=datetime.now(UTC).replace(tzinfo=None)
        )
    )
    return result.rowcount > 0

async def get_pending_orders(s: AsyncSession) -> list[Order]:
    """Получить все ожидающие заказы"""
    result = await s.execute(
        select(Order).where(Order.status == 'pending').order_by(Order.created_at)
    )
    return list(result.scalars())

def normalize_key(name: str) -> str:
    import re
    s = (name or "").lower()
    s = re.sub(r"\s+", " ", s)
    # убираем всё, кроме букв/цифр/пробела и базовых разделителей
    s = re.sub(r"[^\w\s/\-\+\.]", "", s, flags=re.UNICODE)
    return s.strip()


# === NEW: выборка категорий строго из monitored_posts (по порядку message_id) ===
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

async def get_categories(s: AsyncSession, *, channel_id: int, price_type: str='wholesale') -> list[str]:
    """
    Возвращает список категорий для конкретного канала из monitored_posts
    строго в порядке возрастания message_id. Никаких розничных категорий в оптовом и наоборот.
    """
    from app_store.db.core import Base
    # мониторим напрямую таблицу monitored_posts
    result = await s.execute(
        select(
            getattr(__import__('app_store.db.core', fromlist=['monitored_posts']), 'monitored_posts', None) # will fail -> fallback below
        )
    )
    # Если ORM-таблицы monitored_posts нет в core (используем «сырой» select к таблице)
    # Используем текстовый запрос, чтобы не зависеть от объявления модели:
    q = """
    SELECT category
    FROM monitored_posts
    WHERE channel_id = :cid
    ORDER BY message_id
    """
    res = await s.execute(__import__('sqlalchemy').text(q), {"cid": channel_id})
    cats = [row[0] for row in res.fetchall() if row[0]]
    # Уникализуем, сохраняя порядок (на случай дублей)
    seen=set(); out=[]
    for c in cats:
        if c not in seen:
            out.append(c); seen.add(c)
    return out

async def get_products_by_category(
    s: AsyncSession,
    category: str,
    *,
    channel_id: int,
    price_type: str='wholesale'
):
    """
    Возвращает доступные товары по категории конкретного канала.
    Для wholesale — фильтруем по price_wholesale IS NOT NULL.
    Для retail   — по price_retail IS NOT NULL.
    """
    from .core import Product
    price_field = Product.price_wholesale if price_type=='wholesale' else Product.price_retail

    result = await s.execute(
        select(Product)
        .where(
            and_(
                Product.channel_id == channel_id,
                Product.category == category,
                Product.available == True,
                price_field != None
            )
        )
        .order_by(Product.name)
    )
    return list(result.scalars())
