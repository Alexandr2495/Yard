# -*- coding: utf-8 -*-
"""
Розничный бот-каталог:
- Меню категорий по monitored_posts (только розничный канал).
- Список товаров: адаптивная сетка, пагинация, цена справа " · 12 345 ₽".
- Карточка товара -> "В корзину"/"Оформить сейчас" -> выбор qty -> заявки.
- Корзина с суммой в реальном времени; оформление создает несколько заявок (по товару).
- Упрощенные уведомления менеджерам без кнопок одобрения.
- Настройки и шаблоны (bot_settings): контакты и тексты с плейсхолдерами + inline-UI настроек.
"""

import os
import re
import math
import time
import asyncio
import logging
from datetime import datetime, timezone, UTC
from typing import List, Tuple, Dict, Any, Optional

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
    ContentType,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter, TelegramBadRequest, TelegramMigrateToChat

from sqlalchemy import select, func, text, and_, or_, update, not_

# БД
from app_store.db.core import Session, MonitoredPost, BotSetting, Order, BotAdmin, Cart
from app_store.db.repo import Product
from app_store.db.repo import create_order

# Парсинг
from app_store.parsing.price_parser import parse_price_post

# -----------------------------------------------------------------------------
# Инициализация
# -----------------------------------------------------------------------------
load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("retail_bot")

TG_TOKEN_RETAIL = os.getenv("TG_TOKEN_RETAIL")
if not TG_TOKEN_RETAIL:
    raise SystemExit("Set TG_TOKEN_RETAIL in .env")

bot = Bot(TG_TOKEN_RETAIL, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

CHANNEL_ID_STORE = int(os.getenv("CHANNEL_ID_STORE", "0") or "0")
CHANNEL_ID_OPT = int(os.getenv("CHANNEL_ID_OPT", "0") or "0")

# Менеджеры
MANAGER_GROUP_ID = int(os.getenv("MANAGER_STORE_GROUP_ID", "0") or "0")
try:
    MANAGER_USER_IDS = [int(x.strip()) for x in os.getenv("MANAGER_STORE_USER_IDS", "").split(",") if x.strip()]
except (ValueError, TypeError):
    MANAGER_USER_IDS = []

# Sink чат для перескана
SINK_CHAT_ID = int(os.getenv("SINK_CHAT_ID", "0") or "0")

# -----------------------------------------------------------------------------
# Хранилище настроек (bot_settings) и шаблоны
# -----------------------------------------------------------------------------
DEFAULT_CONTACTS = (
    "🏢 <b>Наши контакты</b>\n\n"
    "📍 <b>Адрес:</b> ул. Примерная, д. 123, оф. 45\n"
    "📞 <b>Телефон:</b> +7 (999) 123-45-67\n"
    "✉️ <b>Telegram:</b> @your_manager_username\n"
    "🕒 <b>Время работы:</b> Пн-Пт: 9:00-18:00, Сб: 10:00-16:00"
)

DEFAULT_TEMPLATES = {  # type: Dict[str, str]
    "order_received": (
        "🎉 <b>Заявка успешно принята!</b>\n\n"
        "📦 <b>Товар:</b> {product_name}\n"
        "🔢 <b>Количество:</b> {quantity} шт.\n"
        "💰 <b>Цена за штуку:</b> {price_each} ₽\n"
        "💵 <b>Общая сумма:</b> {total} ₽\n\n"
        "⏳ <i>Ваша заявка передана менеджеру для обработки. "
        "Мы свяжемся с вами в ближайшее время!</i>\n\n"
        "{contacts}"
    ),
    "order_placed_single": (
        "✅ <b>Заказ оформлен (1 товар)</b>\n\n"
        "📦 <b>Товар:</b> {product_name}\n"
        "🔢 <b>Количество:</b> {quantity} шт.\n"
        "💰 <b>Цена за штуку:</b> {price_each} ₽\n"
        "💵 <b>Общая сумма:</b> {total} ₽\n\n"
        "📍 Оплатить и забрать свой заказ Вы сможете по адресу: <b>{address}</b>\n\n"
        "{contacts}"
    ),
    "order_placed_multiple": (
        "✅ <b>Заказ оформлен (несколько товаров)</b>\n\n"
        "📦 <b>Товары в заказе:</b>\n"
        "{cart_items}\n\n"
        "📊 <b>Итоги:</b>\n"
        "• Позиций в заказе: <b>{items_count}</b>\n"
        "• Итоговая сумма: <b>{total} ₽</b>\n\n"
        "📍 Оплатить и забрать свой заказ Вы сможете по адресу: <b>{address}</b>\n\n"
        "{contacts}"
    ),
    "cart_checkout_summary": (
        "🛒 <b>Корзина успешно оформлена!</b>\n\n"
        "🎊 <b>Поздравляем!</b> Ваш заказ из корзины принят к обработке.\n\n"
        "📦 <b>Товары в заказе:</b>\n"
        "{cart_items}\n\n"
        "📊 <b>Итоги:</b>\n"
        "• Позиций в заказе: <b>{items_count}</b>\n"
        "• Итоговая сумма: <b>{total} ₽</b>\n\n"
        "⏳ <i>Все товары из корзины переданы менеджеру. "
        "Мы свяжемся с вами для подтверждения деталей заказа!</i>\n\n"
        "{contacts}"
    ),
    "admin_order_notification_personal": (
        "🛒 <b>Новый розничный заказ #{order_id}</b>\n\n"
        "👤 <b>Покупатель:</b> <code>{user_id}</code>{username_info}\n"
        "📦 <b>Товар:</b> {product_name}\n"
        "📊 <b>Количество:</b> {quantity} шт.\n"
        "💰 <b>Цена за штуку:</b> {price_each} ₽\n"
        "💵 <b>Общая сумма:</b> {total_price} ₽\n\n"
        "📞 <b>Свяжитесь с покупателем для подтверждения заказа</b>"
    ),
    "admin_order_notification_group": (
        "🛒 <b>Новый розничный заказ #{order_id}</b>\n\n"
        "👤 <b>Покупатель:</b> <code>{user_id}</code>{username_info}\n"
        "📦 <b>Товар:</b> {product_name}\n"
        "📊 <b>Количество:</b> {quantity} шт.\n"
        "💰 <b>Цена за штуку:</b> {price_each} ₽\n"
        "💵 <b>Общая сумма:</b> {total_price} ₽\n\n"
        "📞 <b>Свяжитесь с покупателем для подтверждения заказа</b>"
    )
}

async def get_setting(key, default=""):
    async with Session() as s:
        setting = (await s.execute(select(BotSetting).where(BotSetting.key == key))).scalar_one_or_none()
        return setting.value if setting else default

async def set_setting(key, value, description=None, category=None):
    async with Session() as s:
        setting = (await s.execute(select(BotSetting).where(BotSetting.key == key))).scalar_one_or_none()
        if setting:
            setting.value = value
            setting.updated_at = datetime.now(UTC).replace(tzinfo=None)
            if description:
                setting.description = description
            if category:
                setting.category = category
        else:
            s.add(BotSetting(key=key, value=value, description=description, category=category))
        await s.commit()

async def get_setting_with_meta(key, default=""):
    """Получить настройку с метаданными"""
    async with Session() as s:
        setting = (await s.execute(select(BotSetting).where(BotSetting.key == key))).scalar_one_or_none()
        if setting:
            return setting.value, setting.description, setting.category
        return default, None, None

async def get_contacts_text():
    try:
        return await get_setting("contacts", DEFAULT_CONTACTS)
    except Exception as e:
        log.error(f"Error getting contacts: {e}")
        return DEFAULT_CONTACTS

async def get_template(name):
    default = DEFAULT_TEMPLATES.get(name, "")
    return await get_setting(f"tpl:retail:{name}", default)

def render_template(tpl, **kwargs):
    try:
        return tpl.format(**kwargs)
    except Exception:
        return tpl

def extract_address_and_contacts(contacts_text):
    """Выделить адрес из блока контактов и вернуть (address, contacts_without_address)."""
    try:
        lines = [(line or "").strip() for line in (contacts_text or "").splitlines()]
        address_value: str = ""
        filtered = []  # type: list[str]
        for line in lines:
            low = line.lower()
            if not address_value and ("адрес:" in low or "address:" in low):
                # Извлекаем часть после двоеточия
                parts = line.split(":", 1)
                address_value = (parts[1] if len(parts) > 1 else "").strip()
                continue
            filtered.append(line)
        # Сборка контактов без адреса (удаляем возможные лишние пустые строки)
        filtered_text = "\n".join([l for l in filtered if l])
        return (address_value or "", filtered_text)
    except Exception as e:
        log.error(f"Error in extract_address_and_contacts: {e}")
        return ("", "")

# Функции для работы с мониторингом постов (напрямую с БД)
async def get_monitored_message_ids(channel_type):
    """Получить ID мониторимых сообщений из БД"""
    try:
        channel_id = CHANNEL_ID_OPT if channel_type == "opt" else CHANNEL_ID_STORE
        if not channel_id:
            return set()
        
        async with Session() as s:
            posts = (await s.execute(
                select(MonitoredPost)
                .where(MonitoredPost.channel_id == channel_id)
                .where(MonitoredPost.is_active == True)
            )).scalars().all()
            
            return {post.message_id for post in posts}
    except Exception as e:
        log.error(f"Error in get_monitored_message_ids: {e}")
        return set()

async def set_monitored_message_ids(channel_type, message_ids):
    """Установить ID мониторимых сообщений в БД - создать/обновить записи MonitoredPost"""
    try:
        channel_id = CHANNEL_ID_OPT if channel_type == "opt" else CHANNEL_ID_STORE
        if not channel_id:
            return
        
        async with Session() as s:
            # Получаем существующие записи
            existing_posts = (await s.execute(
                select(MonitoredPost)
                .where(MonitoredPost.channel_id == channel_id)
            )).scalars().all()
            
            existing_ids = {post.message_id for post in existing_posts}
            
            # Добавляем новые посты и реактивируем существующие
            for message_id in message_ids:
                if message_id not in existing_ids:
                    # Создаем новый пост
                    post = MonitoredPost(
                        channel_id=channel_id,
                        message_id=message_id,
                        category="Без категории",
                        is_active=True
                    )
                    s.add(post)
                else:
                    # Реактивируем существующий пост если он неактивен
                    existing_post = next(p for p in existing_posts if p.message_id == message_id)
                    if not existing_post.is_active:
                        existing_post.is_active = True
                        # Сбрасываем категорию на "Без категории" при реактивации
                        existing_post.category = "Без категории"
            
            # Деактивируем посты, которых нет в новых настройках
            for post in existing_posts:
                if post.message_id not in message_ids:
                    post.is_active = False
            
            await s.commit()
    except Exception as e:
        log.error(f"Error in set_monitored_message_ids: {e}")
        raise

async def get_master_message_id(channel_type):
    """Получить ID главного сообщения из БД"""
    key = f"master_message_id_{channel_type}"
    value = await get_setting(key, "0")
    return int(value) if value.isdigit() else 0

async def set_master_message_id(channel_type: str, message_id: int) -> None:
    """Установить ID главного сообщения в БД"""
    key = f"master_message_id_{channel_type}"
    description = f"ID главного сообщения для {channel_type} канала"
    await set_setting(key, str(message_id), description, "monitoring")

# Функции для работы с админами
async def get_all_admins() -> List[BotAdmin]:
    """Получить всех активных админов"""
    async with Session() as s:
        admins = (await s.execute(
            select(BotAdmin)
            .where(BotAdmin.is_active == True)
            .order_by(BotAdmin.added_at)
        )).scalars().all()
        return list(admins)

async def add_admin_by_username(username: str, full_name: str = None, added_by: int = None, channel_type: str = 'retail') -> tuple[bool, str]:
    """Добавить админа по username. Возвращает (success, message)"""
    # Очищаем username от @
    clean_username = username.lstrip('@').lower()
    
    async with Session() as s:
        # Проверяем, не является ли уже админом по username
        existing = (await s.execute(
            select(BotAdmin)
            .where(BotAdmin.username == clean_username)
            .where(BotAdmin.channel_type == channel_type)
        )).scalar_one_or_none()
        
        if existing:
            if existing.is_active:
                return False, f"Пользователь @{clean_username} уже является админом"
            else:
                # Активируем существующего
                existing.is_active = True
                existing.added_by = added_by or 0
                existing.added_at = datetime.now(UTC).replace(tzinfo=None)
                await s.commit()
                return True, f"Пользователь @{clean_username} восстановлен как админ"
        else:
            # Создаем нового админа с уникальным временным user_id
            temp_user_id = -(hash(clean_username) % 1000000)  # Уникальный отрицательный ID
            admin = BotAdmin(
                user_id=temp_user_id,  # Временный уникальный ID
                username=clean_username,
                full_name=full_name,
                added_by=added_by or 0,
                added_at=datetime.now(UTC).replace(tzinfo=None),
                is_active=True,
                channel_type=channel_type
            )
            s.add(admin)
            await s.commit()
            return True, f"Пользователь @{clean_username} добавлен как админ"

async def update_admin_user_id(username: str, user_id: int, full_name: str = None, channel_type: str = 'retail') -> bool:
    """Обновить user_id для админа при первом взаимодействии. Если есть запись с другим user_id, обновляем её."""
    clean_username = username.lstrip('@').lower()
    
    async with Session() as s:
        admin = (await s.execute(
            select(BotAdmin)
            .where(BotAdmin.username == clean_username)
            .where(BotAdmin.channel_type == channel_type)
        )).scalar_one_or_none()
        
        if admin:
            admin.user_id = user_id
            if full_name:
                admin.full_name = full_name
            await s.commit()
            return True
        return False

async def remove_admin_by_username(username: str) -> tuple[bool, str]:
    """Удалить админа по username. Возвращает (success, message)"""
    clean_username = username.lstrip('@').lower()
    
    async with Session() as s:
        admin = (await s.execute(
            select(BotAdmin).where(BotAdmin.username == clean_username)
        )).scalar_one_or_none()
        
        if not admin:
            return False, f"Пользователь @{clean_username} не найден среди админов"
        
        if not admin.is_active:
            return False, f"Пользователь @{clean_username} уже не является админом"
        
        admin.is_active = False
        await s.commit()
        return True, f"Пользователь @{clean_username} удален из админов"

async def remove_admin(user_id: int) -> bool:
    """Удалить админа по user_id (для обратной совместимости)"""
    async with Session() as s:
        admin = (await s.execute(
            select(BotAdmin).where(BotAdmin.user_id == user_id)
        )).scalar_one_or_none()
        
        if not admin:
            return False
        
        admin.is_active = False
        await s.commit()
        return True

async def is_admin(user_id: int, username: str = None, channel_type: str = 'retail') -> bool:
    """Проверить, является ли пользователь админом для конкретного канала. Обновляет user_id при первом взаимодействии."""
    async with Session() as s:
        # Сначала проверяем по user_id
        admin = (await s.execute(
            select(BotAdmin)
            .where(BotAdmin.user_id == user_id)
            .where(BotAdmin.is_active == True)
            .where(BotAdmin.channel_type == channel_type)
        )).scalar_one_or_none()
        
        if admin:
            return True
        
        # Если не найден по user_id, проверяем по username
        if username:
            clean_username = username.lstrip('@').lower()
            admin = (await s.execute(
                select(BotAdmin)
                .where(BotAdmin.username == clean_username)
                .where(BotAdmin.is_active == True)
                .where(BotAdmin.channel_type == channel_type)
            )).scalar_one_or_none()
            
            if admin:
                # если user_id не совпадает или временный — обновим
                if admin.user_id != user_id:
                    admin.user_id = user_id
                    await s.commit()
                return True
        
        return False

# -----------------------------------------------------------------------------
# Корзина (база данных)
# -----------------------------------------------------------------------------
async def get_cart_items(uid: int) -> List[Dict[str, Any]]:
    """Получить товары из корзины пользователя"""
    async with Session() as s:
        cart = (await s.execute(select(Cart).where(Cart.user_id == uid))).scalar_one_or_none()
        if cart:
            return cart.items
        return []

async def update_cart_items(uid: int, items: List[Dict[str, Any]]):
    """Обновить товары в корзине пользователя"""
    async with Session() as s:
        cart = (await s.execute(select(Cart).where(Cart.user_id == uid))).scalar_one_or_none()
        if cart:
            cart.items = items
        else:
            cart = Cart(user_id=uid, items=items)
            s.add(cart)
        await s.commit()

async def clear_cart_db(uid: int):
    """Очистить корзину пользователя"""
    async with Session() as s:
        cart = (await s.execute(select(Cart).where(Cart.user_id == uid))).scalar_one_or_none()
        if cart:
            await s.delete(cart)
            await s.commit()

async def cart_total_db(uid: int) -> int:
    """Подсчитать общую сумму корзины"""
    items = await get_cart_items(uid)
    return sum(int(i["qty"]) * int(i["price_each"]) for i in items)

async def cart_count_db(uid: int) -> int:
    """Подсчитать общее количество товаров в корзине"""
    items = await get_cart_items(uid)
    return sum(int(i["qty"]) for i in items)

# -----------------------------------------------------------------------------
# Клавиатуры
# -----------------------------------------------------------------------------
def adaptive_kb(
    buttons,  # type: List[tuple[str, str]]
    *,
    max_per_row: int = 2,
    max_row_chars: int = 40
) -> InlineKeyboardMarkup:
    """
    Под мобильный экран: 2 в ряд, ~40 символов (текст), чтобы название влезало целиком.
    """
    rows = []  # type: list[list[InlineKeyboardButton]]
    cur = []  # type: list[InlineKeyboardButton]
    cur_len = 0
    for text_label, data in buttons:
        tlen = len(text_label or "")
        if cur and (len(cur) >= max_per_row or cur_len + tlen > max_row_chars):
            rows.append(cur)
            cur, cur_len = [], 0
        cur.append(InlineKeyboardButton(text=text_label, callback_data=data))
        cur_len += tlen
    if cur:
        rows.append(cur)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def merge_kb(top: InlineKeyboardMarkup, bottom_rows):  # type: (InlineKeyboardMarkup, list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup
    rows = list(top.inline_keyboard or [])
    rows.extend(bottom_rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def paginate_bar(page: int, pages: int, prev_cb: str, info_cb: str, next_cb: str) -> list[list[InlineKeyboardButton]]:
    left  = ('⬅️', prev_cb) if page > 1 else ('·', info_cb)
    mid   = (f'Стр. {page}/{pages}', info_cb)
    right = ('➡️', next_cb) if page < pages else ('·', info_cb)
    row = [InlineKeyboardButton(text=left[0],  callback_data=left[1]),
           InlineKeyboardButton(text=mid[0],   callback_data=mid[1]),
           InlineKeyboardButton(text=right[0], callback_data=right[1])]
    return [row]

# -----------------------------------------------------------------------------
# Форматирование
# -----------------------------------------------------------------------------
def fmt_price(p: int) -> str:
    return f"{p:,}".replace(",", " ")


def get_adaptive_button_length(user_id: int = None, user_agent: str = None) -> int:
    """
    Определяет оптимальную длину кнопки в зависимости от устройства пользователя.
    Возвращает максимальное количество символов для кнопки.
    """
    # Лимиты для разных типов устройств
    mobile_limit = 40   # для мобильных устройств (включая цену) - увеличиваем для комфорта
    desktop_limit = 60  # для десктопов (больше места на экране)
    tablet_limit = 50   # для планшетов (средний размер)
    
    # Анализируем User-Agent если доступен
    if user_agent:
        user_agent_lower = user_agent.lower()
        
        # Определяем тип устройства по User-Agent
        if any(keyword in user_agent_lower for keyword in ['mobile', 'android', 'iphone', 'ipad']):
            if 'ipad' in user_agent_lower or 'tablet' in user_agent_lower:
                return tablet_limit
            return mobile_limit
        elif any(keyword in user_agent_lower for keyword in ['desktop', 'windows', 'mac', 'linux']):
            return desktop_limit
    
    # По умолчанию используем мобильные лимиты для безопасности
    # Это обеспечивает корректное отображение на всех устройствах
    return mobile_limit

# -----------------------------------------------------------------------------
# Каталог: категории и товары
# -----------------------------------------------------------------------------
async def fetch_categories() -> list[tuple[str, str]]:
    """
    Читает monitored_posts для розничного канала и возвращает [(caption, cbdata)].
    Группирует посты по категориям - если у категории несколько постов, 
    объединяет их в одну кнопку, которая будет искать товары во всех постах.
    """
    if not CHANNEL_ID_STORE:
        return []
    async with Session() as s:
        posts = (await s.execute(
            select(MonitoredPost)
            .where(MonitoredPost.channel_id == CHANNEL_ID_STORE)
            .where(MonitoredPost.is_active == True)
            .order_by(MonitoredPost.message_id)
        )).scalars().all()
    
    # Группируем посты по категориям и типу Б/У
    categories = {}
    for post in posts:
        label = post.category or "Без категории"
        # Исключаем категорию "Контакты" из каталога товаров
        if "контакт" in label.lower() or "contact" in label.lower():
            continue
        
        key = (label, post.is_used)
        if key not in categories:
            categories[key] = []
        categories[key].append(post.message_id)
    
    buttons = []
    for (label, is_used), message_ids in categories.items():
        if is_used:
            label += " (Б/У)"
        
        if len(message_ids) == 1:
            # Один пост - обычная кнопка
            buttons.append((label, f"c|{message_ids[0]}|{1 if is_used else 0}|1"))
        else:
            # Несколько постов - используем первый как основной, 
            # но в fetch_products_page будем искать во всех
            buttons.append((label, f"c|{message_ids[0]}|{1 if is_used else 0}|1|multi|{','.join(map(str, message_ids))}"))
    
    
    return buttons

async def get_category_name(message_id: int) -> str:
    """Получить название категории по message_id"""
    async with Session() as s:
        post = (await s.execute(
            select(MonitoredPost)
            .where(MonitoredPost.message_id == message_id)
            .where(MonitoredPost.channel_id == CHANNEL_ID_STORE)
        )).scalar_one_or_none()
        
        if post:
            return post.category or "Без категории"
        return "Неизвестная категория"

async def fetch_products_page(group_message_id: int, is_used: bool, page: int, per_page: int = 24, multi_message_ids = None):  # type: (int, bool, int, int, List[int]) -> tuple[List[Product], int, int, int]
    """
    Возвращает (items, total, pages, page). 
    Если multi_message_ids задан, ищет товары во всех указанных постах.
    Иначе фильтрация по конкретному посту (group_message_id) и флагу Б/У.
    """
    if not CHANNEL_ID_STORE:
        return [], 0, 1, 1
    async with Session() as s:
        if multi_message_ids:
            # Поиск в нескольких постах
            where_clause = and_(
                Product.channel_id == CHANNEL_ID_STORE,
                Product.group_message_id.in_(multi_message_ids),
                Product.is_used == is_used,
                Product.available == True,
                Product.price_retail != None,
                Product.price_retail > 0,
            )
        else:
            # Поиск в одном посте
            where_clause = and_(
                Product.channel_id == CHANNEL_ID_STORE,
                Product.group_message_id == group_message_id,
                Product.is_used == is_used,
                Product.available == True,
                Product.price_retail != None,
                Product.price_retail > 0,
            )
        
        total = (await s.execute(select(func.count()).select_from(Product).where(where_clause))).scalar_one()
        pages = max(1, math.ceil(total / per_page))
        page = min(max(1, page), pages)
        offset = (page - 1) * per_page
        q = select(Product).where(where_clause).order_by(Product.order_index.nulls_last(), Product.name).limit(per_page).offset(offset)
        items = list((await s.execute(q)).scalars())
    return items, total, pages, page


@dp.callback_query(F.data.startswith("c|"))
async def cb_category(c: CallbackQuery):
    try:
        parts = c.data.split("|")
        mid_str, used_flag, page_str = parts[1], parts[2], parts[3]
        mid = int(mid_str); is_used = (used_flag == "1"); page = int(page_str)
        
        # Проверяем, есть ли информация о множественных постах
        multi_message_ids = None
        if len(parts) > 5 and parts[4] == "multi":
            multi_message_ids = [int(x) for x in parts[5].split(",")]
    except Exception:
        await c.answer("Некорректные данные", show_alert=True)
        return

    items, total, pages, page = await fetch_products_page(mid, is_used, page, multi_message_ids=multi_message_ids)
    if not items:
        cats = await fetch_categories()
        max_row_chars = 34 if any(len(t) > 16 for t, _ in cats) else 40
        kb = adaptive_kb(cats, max_per_row=2, max_row_chars=max_row_chars)
        # Безопасно отвечаем без попытки редактировать исходное сообщение
        try:
            await c.message.answer(
                "В этой категории сейчас нет товаров.",
                reply_markup=kb
            )
        except Exception:
            pass
        try:
            await c.answer("Категория пуста")
        except Exception:
            pass
        return

    # Товары в виде адаптивной сетки
    buttons = []
    # Адаптивные лимиты в зависимости от устройства пользователя
    MAX_LENGTH = get_adaptive_button_length(c.from_user.id if c.from_user else None)
    log.info(f"User {c.from_user.id if c.from_user else 'unknown'} - MAX_LENGTH: {MAX_LENGTH}")
    
    for p in items:
        price = int(p.price_retail or 0)
        flag = ""
        try:
            ea = dict(p.extra_attrs or {})
            flag = (ea.get("flag") or "").strip()
        except Exception:
            flag = ""
        
        name = (p.name or "").strip()
        
        # Создаем полное название без флага в начале
        full_name = name
        
        # Добавляем цену с флагом вместо точки
        if price > 0:
            flag_separator = f" {flag} " if flag else " · "
            suffix = f"{flag_separator}{fmt_price(price)} ₽"
        else:
            suffix = ""
        full_text_with_suffix = f"{full_name}{suffix}"
        
        # Если общий текст слишком длинный, обрезаем название умно
        if len(full_text_with_suffix) > MAX_LENGTH:
            # Определяем, сколько места занимает суффикс
            suffix_len = len(suffix)
            # Доступное место для названия (с запасом для "...")
            available_name_length = MAX_LENGTH - suffix_len - 3 # -3 для "..."
            
            if available_name_length < 3: # Если суффикс занимает почти все место
                # В крайнем случае показываем только цену
                if suffix_len <= MAX_LENGTH - 3:
                    title = "..." + suffix
                else:
                    # Если даже цена не помещается, обрезаем ее принудительно
                    title = suffix[:MAX_LENGTH-3] + "..."
            else:
                # Умная обрезка: используем максимум доступного места для названия
                # Если название короче доступного места, берем его целиком
                if len(full_name) <= available_name_length:
                    short_name = full_name
                else:
                    # Обрезаем название до доступной длины
                    short_name = full_name[:available_name_length] + "..."
                
                title = f"{short_name}{suffix}"
        else:
            title = full_text_with_suffix
            
        buttons.append((title, f"p|{p.id}|{mid}|{1 if is_used else 0}|{page}"))

    grid = adaptive_kb(buttons, max_per_row=2, max_row_chars=MAX_LENGTH)
    
    # Формируем callback data для пагинации с учетом множественных постов
    base_cb = f"c|{mid}|{1 if is_used else 0}"
    if multi_message_ids:
        multi_part = f"|multi|{','.join(map(str, multi_message_ids))}"
    else:
        multi_part = ""
    
    bar = paginate_bar(
        page, pages,
        prev_cb=f"{base_cb}|{page-1}{multi_part}",
        info_cb=f"{base_cb}|{page}{multi_part}",
        next_cb=f"{base_cb}|{page+1}{multi_part}",
    )
    back_row = [InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="back")]
    kb = merge_kb(grid, [bar[0], back_row])

    # Получаем название категории
    category_name = await get_category_name(mid)
    if is_used:
        category_name = f"🔧 {category_name}"
    
    caption = f"📱 <b>{category_name}</b>\n\nТоваров: {total}"
    try:
        await c.message.edit_text(caption, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await c.answer()
            return
        try:
            await c.message.edit_reply_markup(reply_markup=kb)
        except TelegramBadRequest as e2:
            if "message is not modified" in str(e2):
                await c.answer()
                return
            raise
    await c.answer()

@dp.callback_query(F.data == "back")
async def cb_back(c: CallbackQuery):
    uid = c.from_user.id
    log.info(f"Back button pressed by user {uid}")
    
    cats = await fetch_categories()
    max_row_chars = 34 if any(len(t) > 16 for t, _ in cats) else 40
    kb = adaptive_kb(cats, max_per_row=2, max_row_chars=max_row_chars) if cats else adaptive_kb([("Категории не настроены", "noop")])
    try:
        await c.message.edit_text("Выберите категорию:", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()


@dp.callback_query(F.data.startswith("p|"))
async def cb_product(c: CallbackQuery):
    try:
        parts = c.data.split("|")
        _, pid_str, mid_str, used_flag, page_str = parts[:5]
        pid = int(pid_str); mid = int(mid_str); is_used = (used_flag == "1"); page = int(page_str)
        
        # Проверяем, есть ли информация о множественных постах
        multi_message_ids = None
        if len(parts) > 6 and parts[5] == "multi":
            multi_message_ids = [int(x) for x in parts[6].split(",")]
    except Exception:
        await c.answer("Некорректные данные", show_alert=True)
        return

    async with Session() as s:
        prod = (await s.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if not prod:
        await c.answer("Товар не найден", show_alert=True)
        return

    price = int(prod.price_retail or 0)
    # добавляем флаг к названию товара
    try:
        ea = dict(prod.extra_attrs or {})
        flag = (ea.get("flag") or "").strip()
    except Exception:
        flag = ""
    lines = [f"<b>{prod.name}{flag}</b>"]
    if price > 0:
        lines.append(f"Цена РОЗНИЦА: <b>{fmt_price(price)} ₽</b>")
    else:
        lines.append("Цена РОЗНИЦА: <b>Не указана</b>")
    if prod.category:
        lines.append(f"Категория: {prod.category}")
    if prod.is_used:
        lines.append("Состояние: Б/У")
    text_msg = "\n".join(lines)

    # Формируем callback data для возврата с учетом множественных постов
    base_cb = f"c|{mid}|{1 if is_used else 0}|{page}"
    if multi_message_ids:
        base_cb += f"|multi|{','.join(map(str, multi_message_ids))}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 В корзину", callback_data=f"cart:start:{prod.id}")],
        [InlineKeyboardButton(text="🧾 Оформить сейчас", callback_data=f"order:start:{prod.id}")],
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data=base_cb)],
    ])
    try:
        await c.message.edit_text(text_msg, reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

def _qty_kb(prefix: str, pid: int, qty: int, price_each: int) -> InlineKeyboardMarkup:
    if qty < 1:
        qty = 1
    total = qty * max(0, int(price_each or 0))
    buttons = [
        [
            InlineKeyboardButton(text="➖", callback_data=f"{prefix}:qty:{pid}:{qty-1}"),
            InlineKeyboardButton(text=f"{qty}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"{prefix}:qty:{pid}:{qty+1}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back"),
            InlineKeyboardButton(text=f"✅ Подтвердить (Итого: {fmt_price(total)} ₽)", callback_data=f"{prefix}:make:{pid}:{qty}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# === Оформление напрямую (без корзины) ===
@dp.callback_query(F.data.regexp(r"^(order:start):(\d+)$"))
async def cb_order_start(call: CallbackQuery):
    try:
        pid = int(call.data.split(":")[2])
    except Exception:
        await call.answer("Ошибка данных", show_alert=True)
        return

    async with Session() as s:
        prod = (await s.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
        if not prod:
            await call.answer("Товар не найден", show_alert=True)
            return
        price_each = int(prod.price_retail or prod.price_retail or 0)
        if price_each <= 0:
            await call.answer("Нет цены", show_alert=True)
            return

        # флаг товара
        try:
            ea = dict(prod.extra_attrs or {})
            flag = (ea.get("flag") or "").strip()
        except Exception:
            flag = ""
        text = (
            f"<b>{prod.name}{flag}</b>\n"
            f"Цена: <b>{fmt_price(price_each)} ₽</b>\n"
            f"Выберите количество и подтвердите заказ."
        )
        await call.message.edit_text(text, reply_markup=_qty_kb("order", prod.id, 1, price_each), parse_mode="HTML")

@dp.callback_query(F.data.regexp(r"^order:qty:(\d+):(\d+)$"))
async def cb_order_qty(call: CallbackQuery):
    _, _, pid_str, qty_str = call.data.split(":")
    try:
        pid = int(pid_str)
        qty = max(1, int(qty_str))
    except Exception:
        await call.answer("Некорректное количество", show_alert=True)
        return

    async with Session() as s:
        prod = (await s.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
        if not prod:
            await call.answer("Товар не найден", show_alert=True)
            return
        price_each = int(prod.price_retail or prod.price_retail or 0)
        if price_each <= 0:
            await call.answer("Нет цены", show_alert=True)
            return

        # флаг товара
        try:
            ea = dict(prod.extra_attrs or {})
            flag = (ea.get("flag") or "").strip()
        except Exception:
            flag = ""
        text = (
            f"<b>{prod.name}{flag}</b>\n"
            f"Цена: <b>{fmt_price(price_each)} ₽</b>\n"
            f"Количество: <b>{qty}</b>"
        )
        await call.message.edit_text(text, reply_markup=_qty_kb("order", prod.id, qty, price_each), parse_mode="HTML")

@dp.callback_query(F.data.regexp(r"^order:make:(\d+):(\d+)$"))
async def cb_order_make(call: CallbackQuery):
    _, _, pid_str, qty_str = call.data.split(":")
    try:
        pid = int(pid_str)
        qty = max(1, int(qty_str))
    except Exception:
        await call.answer("Некорректные данные", show_alert=True)
        return

    user = call.from_user
    uid = user.id if user else 0
    uname = user.username if user and user.username else None

    async with Session() as s:
        prod = (await s.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
        if not prod:
            await call.answer("Товар не найден", show_alert=True)
            return
        price_each = int(prod.price_retail or prod.price_retail or 0)
        if price_each <= 0:
            await call.answer("Нет цены", show_alert=True)
            return

        order = await create_order(
            s,
            user_id=uid,
            username=uname,
            product_id=prod.id,
            product_name=prod.name,
            quantity=qty,
            price_each=price_each,
            order_type="wholesale",
        )
        await s.commit()

        total = price_each * qty
        # сообщение покупателю из шаблона (используем order_placed_single для розничного бота)
        tpl = await get_template("order_placed_single")
        contacts = await get_contacts_text()
        try:
            await bot.send_message(
                uid,
                render_template(
                    tpl,
                    product_name=f"{prod.name}{(dict(prod.extra_attrs or {}).get('flag') or '')}",
                    quantity=qty,
                    price_each=fmt_price(price_each),
                    total=fmt_price(total),
                    user_id=uid,
                    username=uname or "",
                    contacts=contacts
                ),
                disable_notification=True
            )
        except Exception:
            pass

    # уведомление менеджеров (сначала только 2 кнопки)
    await _notify_managers_new_order(order, prod.name, price_each)
    await call.answer("Заявка отправлена менеджеру")

# === Корзина ===
@dp.callback_query(F.data.regexp(r"^(cart:start):(\d+)$"))
async def cb_cart_start(call: CallbackQuery):
    try:
        pid = int(call.data.split(":")[2])
    except Exception:
        await call.answer("Ошибка данных", show_alert=True)
        return
    async with Session() as s:
        prod = (await s.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if not prod:
        await call.answer("Товар не найден", show_alert=True)
        return
    price_each = int(prod.price_retail or prod.price_retail or 0)
    if price_each <= 0:
        await call.answer("Нет цены", show_alert=True)
        return
    # флаг товара
    try:
        ea = dict(prod.extra_attrs or {})
        flag = (ea.get("flag") or "").strip()
    except Exception:
        flag = ""
    text = (
        f"<b>{prod.name}{flag}</b>\n"
        f"Цена: <b>{fmt_price(price_each)} ₽</b>\n"
        f"Выберите количество и добавьте в корзину."
    )
    await call.message.edit_text(text, reply_markup=_qty_kb("cart", prod.id, 1, price_each), parse_mode="HTML")

@dp.callback_query(F.data.regexp(r"^cart:qty:(\d+):(\d+)$"))
async def cb_cart_qty(call: CallbackQuery):
    _, _, pid_str, qty_str = call.data.split(":")
    try:
        pid = int(pid_str)
        qty = max(1, int(qty_str))
    except Exception:
        await call.answer("Некорректное количество", show_alert=True)
        return
    async with Session() as s:
        prod = (await s.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if not prod:
        await call.answer("Товар не найден", show_alert=True)
        return
    price_each = int(prod.price_retail or prod.price_retail or 0)
    if price_each <= 0:
        await call.answer("Нет цены", show_alert=True)
        return
    # флаг товара
    try:
        ea = dict(prod.extra_attrs or {})
        flag = (ea.get("flag") or "").strip()
    except Exception:
        flag = ""
    text = (
            f"<b>{prod.name}{flag}</b>\n"
            f"Цена: <b>{fmt_price(price_each)} ₽</b>\n"
            f"Количество: <b>{qty}</b>"
        )
    await call.message.edit_text(text, reply_markup=_qty_kb("cart", prod.id, qty, price_each), parse_mode="HTML")

@dp.callback_query(F.data.regexp(r"^cart:make:(\d+):(\d+)$"))
async def cb_cart_make(call: CallbackQuery):
    _, _, pid_str, qty_str = call.data.split(":")
    try:
        pid = int(pid_str)
        qty = max(1, int(qty_str))
    except Exception:
        await call.answer("Некорректные данные", show_alert=True)
        return

    uid = call.from_user.id
    async with Session() as s:
        prod = (await s.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if not prod:
        await call.answer("Товар не найден", show_alert=True)
        return
    price_each = int(prod.price_retail or prod.price_retail or 0)
    if price_each <= 0:
        await call.answer("Нет цены", show_alert=True)
        return

    # Получаем текущие товары из корзины
    current_items = await get_cart_items(uid)
    
    # Проверяем, есть ли уже такой товар в корзине
    existing_item = None
    for item in current_items:
        if item["pid"] == pid:
            existing_item = item
            break
    
    if existing_item:
        # Увеличиваем количество существующего товара
        existing_item["qty"] += qty
    else:
        # Добавляем новый товар
        current_items.append({
            "pid": pid,
            "name": prod.name,
            "qty": qty,
            "price_each": price_each
        })
    
    # Сохраняем обновленную корзину в базу данных
    await update_cart_items(uid, current_items)
    
    total = await cart_total_db(uid)
    count = await cart_count_db(uid)
    
    log.info(f"Cart updated for user {uid}: {count} items, total {total}")
    log.info(f"Cart contents: {current_items}")
    
    try:
        await call.message.edit_text(
            f"✅ <b>Товар добавлен в корзину!</b>\n\n"
            f"📦 <b>Товар:</b> {prod.name}{(dict(prod.extra_attrs or {}).get('flag') or '')}\n"
            f"🔢 <b>Количество:</b> {qty} шт.\n\n"
            f"🧺 <b>В корзине:</b> {count} позиций\n"
            f"💵 <b>Общая сумма:</b> {fmt_price(total)} ₽",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧺 Открыть корзину", callback_data="cart:open")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
            ]),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await call.answer("Добавлено")

@dp.callback_query(F.data == "cart:open")
async def cb_cart_open(call: CallbackQuery):
    uid = call.from_user.id
    items = await get_cart_items(uid)
    
    log.info(f"Opening cart for user {uid}: {len(items)} items")
    log.info(f"Cart contents: {items}")
    
    if not items:
        await call.message.edit_text("🛒 <b>Ваша корзина пуста</b>\n\n💡 <i>Добавьте товары из каталога, чтобы оформить заказ.</i>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
        ]), parse_mode="HTML")
        await call.answer()
        return
    lines = ["🧺 <b>Корзина</b>"]
    for it in items[:12]:
        # Добавляем флаг страны к названию, если есть
        name_with_flag = it['name']
        try:
            async with Session() as s:
                prod = (await s.execute(select(Product).where(Product.id == it["pid"]))).scalar_one_or_none()
                if prod:
                    ea = dict(prod.extra_attrs or {})
                    flag = (ea.get("flag") or "").strip()
                    if flag:
                        name_with_flag = f"{name_with_flag}{flag}"
        except Exception:
            pass
        lines.append(f"• {html.quote(name_with_flag)} × {it['qty']} = {fmt_price(it['qty']*it['price_each'])} ₽")
    if len(items) > 12:
        lines.append(f"… и ещё {len(items)-12} позиций")
    total = await cart_total_db(uid)
    lines.append(f"\nИтого: <b>{fmt_price(total)} ₽</b>")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 Оформить", callback_data="cart:checkout")],
        [InlineKeyboardButton(text="🗑 Очистить", callback_data="cart:clear")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ])
    await call.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "cart:clear")
async def cb_cart_clear(call: CallbackQuery):
    uid = call.from_user.id
    await clear_cart_db(uid)
    await call.message.edit_text("🗑️ <b>Корзина очищена</b>\n\n💡 <i>Все товары удалены из корзины.</i>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ]), parse_mode="HTML")
    await call.answer("Очищено")

@dp.callback_query(F.data == "cart:checkout")
async def cb_cart_checkout(call: CallbackQuery):
    uid = call.from_user.id
    uname = call.from_user.username or ""
    items = await get_cart_items(uid)
    if not items:
        await call.answer("Корзина пуста", show_alert=True)
        return
    created_orders = []
    async with Session() as s:
        for it in items:
            prod = (await s.execute(select(Product).where(Product.id == it["pid"]))).scalar_one_or_none()
            if not prod:
                continue
            price_each = int(prod.price_retail or prod.price_retail or 0)
            if price_each <= 0:
                continue
            order = await create_order(
                s,
                user_id=uid,
                username=uname,
                product_id=prod.id,
                product_name=prod.name,
                quantity=int(it["qty"]),
                price_each=price_each,
                order_type="wholesale",
            )
            created_orders.append((order, prod.name, price_each, int(it["qty"])))
        await s.commit()

    if not created_orders:
        await call.answer("Не удалось оформить корзину (товары недоступны).", show_alert=True)
        return

    total_sum = sum(pe*qty for _, _, pe, qty in created_orders)
    contacts = await get_contacts_text()
    
    # Формируем список товаров для шаблона с флагами
    cart_items_text = ""
    for order, prod_name, price_each, qty in created_orders:
        # Получаем флаг товара из БД
        flag = ""
        is_used_flag = False
        try:
            async with Session() as s:
                prod = (await s.execute(select(Product).where(Product.id == order.product_id))).scalar_one_or_none()
                if prod:
                    is_used_flag = bool(prod.is_used)
                    ea = dict(prod.extra_attrs or {})
                    flag = (ea.get("flag") or "").strip()
        except Exception:
            flag = ""
        
        # Формируем полное название товара с флагом
        prod_label = f"{prod_name}{flag}{' (Б/У)' if is_used_flag else ''}"
        cart_items_text += f"• {prod_label} × {qty} шт. = {fmt_price(price_each * qty)} ₽\n"
    
    # Подсчитываем общее количество товаров (не уникальных позиций)
    total_items_count = sum(int(it["qty"]) for it in items)
    
    tpl_cart = await get_template("cart_checkout_summary")
    try:
        await bot.send_message(
            uid,
            render_template(tpl_cart, 
                          items_count=total_items_count, 
                          total=fmt_price(total_sum), 
                          contacts=contacts,
                          cart_items=cart_items_text.strip()),
            disable_notification=True
        )
    except Exception:
        pass

    for order, prod_name, price_each, qty in created_orders:
        await _notify_managers_new_order(order, prod_name, price_each)

    await clear_cart_db(uid)  # очистим корзину в базе данных
    try:
        await call.message.edit_text("🎉 <b>Заявки успешно отправлены!</b>\n\n✅ <i>Все товары из корзины переданы менеджеру для обработки.</i>\n\n📞 <i>Мы свяжемся с вами в ближайшее время!</i>", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]]
        ), parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await call.answer("Оформлено")

# -----------------------------------------------------------------------------
# Перескан наблюдаемых постов (опт)
# -----------------------------------------------------------------------------
# ВАЖНО: «только /1000» — это не требование кратности, а мягкая нормализация, если цена подозрительно велика.
# Разрешаем юникодные дефисы (– — ‑) и запятую в цене
# Делаем имя жадным (.+), чтобы разделитель выбирался ближе к цене, а не в модели типа "WF-1000XM5"
PRICE_RE = re.compile(r"^\s*(?P<name>.+?)\s*[-:–—‑]\s*(?P<price>[\d\s.,]{2,})(?P<rest>.*)$")

def _extract_flag(text: str) -> str:
    """Попробовать извлечь флаг (emoji-флаг страны) из строки."""
    try:
        flag_match = re.search(r"[\U0001F1E6-\U0001F1FF]{2}", text)
        return flag_match.group(0) if flag_match else ""
    except Exception:
        return ""

def parse_lines(text: str) -> List[Tuple[str, int, str]]:
    items = []  # type: list[tuple[str, int, str]]
    for raw in (text or "").splitlines():
        m = PRICE_RE.match(raw)
        if not m:
            continue
        name = m.group("name").strip()
        price_str = m.group("price") or ""
        rest = m.group("rest") or ""
        
        # Нормализация цены: убираем все кроме цифр и точек
        # Обрабатываем случаи типа "5.990р" -> "5990"
        price_clean = re.sub(r"[^\d.]", "", price_str)
        
        # Если есть точка, проверяем - это разделитель тысяч или копейки
        if "." in price_clean:
            parts = price_clean.split(".")
            if len(parts) == 2:
                # Если после точки 3 цифры - это разделитель тысяч (5.990)
                if len(parts[1]) == 3:
                    price_clean = parts[0] + parts[1]
                # Если после точки 1-2 цифры - это копейки, игнорируем их
                elif len(parts[1]) <= 2:
                    price_clean = parts[0]
                # Если после точки больше 3 цифр - это тоже разделитель тысяч (10.500)
                else:
                    price_clean = parts[0] + parts[1]
            elif len(parts) > 2:
                # Несколько точек - это разделители тысяч (1.234.567)
                price_clean = "".join(parts)
        
        if not price_clean:
            continue
        try:
            price = int(price_clean)
        except Exception:
            continue
        if price <= 0:
            continue
        # защита от лишних нулей: только делим на 1000, НИКОГДА не делим на 100
        # пример: "50000000" -> "50000", если выглядит как три лишних нуля
        if price > 2_000_000 and price % 1000 == 0 and (price // 1000) <= 5_000_000:
            price //= 1000
        if price > 5_000_000:
            continue
        
        # Ищем флаги в строке - может быть несколько
        flags = []
        # Ищем флаги в хвосте строки (после цены)
        flag_matches = re.findall(r"[\U0001F1E6-\U0001F1FF]{2}", rest)
        flags.extend(flag_matches)
        # Ищем флаги в названии
        flag_matches = re.findall(r"[\U0001F1E6-\U0001F1FF]{2}", name)
        flags.extend(flag_matches)
        
        # Убираем флаги из названия для чистоты
        clean_name = re.sub(r"[\U0001F1E6-\U0001F1FF]{2}\s*", "", name).strip()
        
        if flags:
            # Создаем отдельную запись для каждого флага
            for flag in flags:
                items.append((clean_name, price, flag))
        else:
            # Если флагов нет, добавляем без флага
            items.append((clean_name, price, ""))
    return items

def parse_used_attrs(name: str) -> dict:
    s = (name or "").lower()
    attrs: dict = {}
    m = re.search(r"(\d+)\s*(?:год|года|лет|месяц|месяца|недел)", s)
    if m:
        attrs["usage_hint"] = m.group(0)
    if "полный комплект" in s:
        attrs["kit"] = "full"
    if "без короб" in s:
        attrs["kit"] = "no_box"
    return attrs

def norm_key(name: str, flag: str = "") -> str:
    s = (name or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    # Добавляем флаг в ключ для уникальности
    if flag:
        s = f"{s}|{flag}"
    return s

def _now_ms() -> int:
    return int(time.time() * 1000)

async def _safe_copy_and_read_text(bot: Bot, sink_id: int, from_chat_id: int, message_id: int, *, max_retries: int = 3) -> str:
    """
    Получаем текст сообщения напрямую из канала без копирования.
    """
    delay = 0.5
    for attempt in range(1, max_retries + 1):
        try:
            # Получаем сообщение напрямую из канала
            try:
                # Используем get_chat для получения информации о чате
                chat = await bot.get_chat(from_chat_id)
                log.info(f"Got chat: {chat.title}")
                
                # Пробуем получить сообщение через forward_message
                forwarded = await bot.forward_message(
                    chat_id=SINK_CHAT_ID,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                    disable_notification=True
                )
                
                # Получаем текст из пересланного сообщения
                text = ""
                if hasattr(forwarded, 'text') and forwarded.text:
                    text = forwarded.text
                elif hasattr(forwarded, 'caption') and forwarded.caption:
                    text = forwarded.caption
                
                # Удаляем пересланное сообщение
                try:
                    await bot.delete_message(chat_id=sink_id, message_id=forwarded.message_id)
                except TelegramBadRequest:
                    pass
                
                log.info(f"Got text from message {message_id}: {text[:100]}...")
                return text
                
            except Exception as e:
                log.error(f"Error getting message {message_id}: {e}")
                return ""
            
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(getattr(e, "retry_after", 1.0)) + 0.5)
        except TelegramAPIError as e:
            log.error(f"Error accessing message {message_id}: {e}")
            if attempt == max_retries:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, 4.0)
    return ""

# Функция /rescan для розничного бота
async def cmd_rescan(message: Message):
    """Перескан товаров из розничного канала"""
    if not message.from_user or not await _is_manager(message.from_user.id, message.from_user.username, 'retail'):
        await message.answer("⛔ Недостаточно прав.")
        return
    
    if not CHANNEL_ID_STORE:
        await message.answer("❌ CHANNEL_ID_STORE не настроен.")
        return
    
    await message.answer("🔄 <b>Начинаем перескан товаров...</b>")
    
    try:
        # Получаем активные посты для розничного канала
        async with Session() as s:
            posts = (await s.execute(
                select(MonitoredPost)
                .where(MonitoredPost.channel_id == CHANNEL_ID_STORE)
                .where(MonitoredPost.is_active == True)
            )).scalars().all()
        
        if not posts:
            await message.answer("❌ Нет активных постов для сканирования.")
            return
        
        success_count = 0
        error_count = 0
        
        for post in posts:
            try:
                # Получаем текст поста
                text = await _safe_copy_and_read_text(bot, SINK_CHAT_ID, CHANNEL_ID_STORE, post.message_id)
                if not text:
                    error_count += 1
                    continue
                
                # Обновляем товары
                await upsert_for_message_rescan(
                    CHANNEL_ID_STORE, 
                    post.message_id, 
                    post.category or "Без категории", 
                    text, 
                    post.is_used
                )
                success_count += 1
                
            except Exception as e:
                log.error(f"Error scanning post {post.message_id}: {e}")
                error_count += 1
        
        await message.answer(
            f"✅ <b>Перескан завершен!</b>\n\n"
            f"📊 <b>Результаты:</b>\n"
            f"• Успешно: {success_count}\n"
            f"• Ошибок: {error_count}\n\n"
            f"💡 Товары обновлены в каталоге."
        )
        
    except Exception as e:
        log.error(f"Error in rescan: {e}")
        await message.answer(f"❌ Ошибка при перескане: {e}")


def norm_key(name: str, flag: str = "") -> str:
    """Нормализация ключа товара"""
    key = name.lower().strip()
    if flag:
        key += f"_{flag}"
    return key

async def upsert_for_message_rescan(channel_id: int, message_id: int, category: str, text: str, is_used: bool):
    """
    Полная переиндексация товаров поста при перескане.
    Сначала деактивирует все товары поста, затем создает/активирует с новыми индексами.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = parse_lines(text)

    async with Session() as s:
        # 1. Сначала деактивируем ВСЕ товары этого поста
        await s.execute(
            update(Product)
            .where(
                and_(
                    Product.channel_id == channel_id,
                    Product.group_message_id == message_id,
                    Product.is_used == is_used
                )
            )
            .values(
                available=False,
                order_index=None,
                updated_at=now
            )
        )
        
        # 2. Затем создаем/активируем товары с новыми индексами
        for order_index, (name, price, flag) in enumerate(rows, 1):
            key = norm_key(name, flag)
            
            # Ищем существующий товар
            prod = (await s.execute(
                select(Product).where(
                    and_(
                        Product.channel_id == channel_id,
                        Product.group_message_id == message_id,
                        Product.key == key,
                        Product.is_used == is_used
                    )
                )
            )).scalar_one_or_none()
            
            if prod:
                # Обновляем существующий товар
                prod.name = name[:400]
                prod.available = True
                prod.order_index = order_index
                prod.price_retail = price
                prod.category = category
                prod.is_used = is_used
                prod.updated_at = now
                
                # Обновляем extra_attrs
                try:
                    cur = dict(prod.extra_attrs or {})
                except Exception:
                    cur = {}
                if is_used:
                    cur.update(parse_used_attrs(name))
                if flag:
                    cur["flag"] = flag
                prod.extra_attrs = cur or None
            else:
                # Создаем новый товар
                prod = Product(
                    channel_id=channel_id,
                    group_message_id=message_id,
                    name=name[:400],
                    key=key,
                    category=category,
                    available=True,
                    is_used=is_used,
                    order_index=order_index,
                    price_retail=price,
                    extra_attrs=(
                        {
                            **(parse_used_attrs(name) if is_used else {}),
                            **({"flag": flag} if flag else {})
                        } or None
                    ),
                    updated_at=now
                )
                s.add(prod)

        await s.commit()

# --- Reply-меню и обработчики текстовых кнопок ----------------

# Тексты кнопок (основное меню):
BTN_CATALOG = "📱 Каталог товаров"
BTN_CONTACTS = "📍 Наши контакты"
BTN_CART = "🧺 Корзина"
BTN_RESCAN = "🔄 Перескан"
BTN_DIAG = "📊 Диагностика"
BTN_SETTINGS = "⚙️ Настройки"

# Админские функции с визуальными индикаторами
BTN_RESCAN_ADMIN = "🔄 Перескан (админ)"
BTN_DIAG_ADMIN = "📊 Диагностика (админ)"
BTN_SETTINGS_ADMIN = "⚙️ Настройки (админ)"


async def main_menu_kb(user_id: Optional[int], chat_type: str = "private") -> ReplyKeyboardMarkup:
    # Формируем текст кнопки корзины с количеством товаров
    cart_text = BTN_CART
    if user_id:
        try:
            cart_count = await cart_count_db(user_id)
            if cart_count > 0:
                cart_text = f"{BTN_CART} ({cart_count})"
        except Exception:
            pass  # Если ошибка, используем стандартный текст
    
    rows = [  # type: list[list[KeyboardButton]]
        [KeyboardButton(text=BTN_CATALOG)],
        [KeyboardButton(text=BTN_CONTACTS), KeyboardButton(text=cart_text)],
    ]
    
    # Проверяем права админа (БД приоритетна, .env для обратной совместимости)
    # Админские кнопки показываем ТОЛЬКО в личных чатах
    is_manager = False
    if user_id and chat_type == "private":
        # Сначала проверяем БД (основной способ)
        is_manager = await _is_manager(user_id, channel_type='retail')
        
        # Если не найден в БД, проверяем .env (для обратной совместимости)
        if not is_manager and MANAGER_USER_IDS and user_id in MANAGER_USER_IDS:
            is_manager = True
    
    if is_manager:
        # Админские функции с визуальными индикаторами (админ)
        rows.append([KeyboardButton(text=BTN_RESCAN_ADMIN), KeyboardButton(text=BTN_DIAG_ADMIN)])
        rows.append([KeyboardButton(text=BTN_SETTINGS_ADMIN)])
    
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие…"
    )

@dp.message(Command("menu"))
@dp.message(Command("start"))
async def on_menu(m: Message):
    try:
        # Принудительно отправляем основное меню
        await m.answer("🏠 <b>Главное меню</b>\n\nВыберите действие:", 
                       parse_mode="HTML", 
                       reply_markup=await main_menu_kb(m.from_user.id if m.from_user else 0, m.chat.type))
    except Exception as e:
        log.error(f"Error sending main menu: {e}")
        await m.answer("Выберите действие:")

@dp.message(F.text.casefold() == BTN_CATALOG.casefold())
async def on_catalog_button(m: Message):
    cats = await fetch_categories()
    if not cats:
        await m.answer("Категории не настроены или пусто.", reply_markup=await main_menu_kb(m.from_user.id if m.from_user else 0, m.chat.type))
        return
    max_row_chars = 34 if any(len(t) > 16 for t, _ in cats) else 40
    kb = adaptive_kb(cats, max_per_row=2, max_row_chars=max_row_chars)
    await m.answer("Выберите категорию:", reply_markup=kb)

@dp.message(F.text.casefold() == BTN_CONTACTS.casefold())
async def on_contacts(m: Message):
    contacts = await get_contacts_text()
    await m.answer(contacts, reply_markup=await main_menu_kb(m.from_user.id if m.from_user else 0, m.chat.type))

@dp.message(F.text.casefold().startswith(BTN_CART.casefold()))
async def on_cart_btn(m: Message):
    uid = m.from_user.id if m.from_user else 0
    items = await get_cart_items(uid)
    
    log.info(f"Cart button pressed by user {uid}")
    log.info(f"Cart contents: {items}")
    log.info(f"Total items in cart: {len(items)}")
    
    if not items:
        await m.answer("🛒 <b>Ваша корзина пуста</b>\n\n💡 <i>Добавьте товары из каталога, чтобы оформить заказ.</i>", reply_markup=await main_menu_kb(uid, m.chat.type), parse_mode="HTML")
        return
    lines = ["🧺 <b>Корзина</b>"]
    for it in items[:12]:
        lines.append(f"• {html.quote(it['name'])} × {it['qty']} = {fmt_price(it['qty']*it['price_each'])} ₽")
    if len(items) > 12:
        lines.append(f"… и ещё {len(items)-12} позиций")
    total = await cart_total_db(uid)
    lines.append(f"\nИтого: <b>{fmt_price(total)} ₽</b>")
    await m.answer("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 Оформить", callback_data="cart:checkout")],
        [InlineKeyboardButton(text="🗑 Очистить", callback_data="cart:clear")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ]))

# Обработчики для возврата к основному меню
@dp.message(F.text == "⬅️ Назад в меню")
async def on_back_to_menu(m: Message):
    await m.answer("🏠 <b>Главное меню</b>\nВыберите действие:", parse_mode="HTML", reply_markup=await main_menu_kb(m.from_user.id if m.from_user else 0, m.chat.type))

@dp.message(Command("rescan"))
async def on_rescan_command(m: Message):
    """Команда /rescan для перескана товаров"""
    await cmd_rescan(m)

@dp.message(F.text.in_([BTN_RESCAN, BTN_RESCAN_ADMIN]))
async def on_rescan_button(m: Message):
    """Кнопка перескана товаров"""
    await cmd_rescan(m)

@dp.message(F.text.in_([BTN_DIAG, BTN_DIAG_ADMIN]))
@dp.message(Command("diag"))
async def on_diag(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    
    async with Session() as s:
        # Общая статистика по розничному каналу
        total_products = (await s.execute(
            select(func.count()).select_from(Product).where(Product.channel_id == CHANNEL_ID_STORE)
        )).scalar_one()
        
        available_products = (await s.execute(
            select(func.count()).select_from(Product).where(
                and_(
                    Product.channel_id == CHANNEL_ID_STORE,
                    Product.available == True,
                    Product.price_retail != None
                )
            )
        )).scalar_one()
        
        # Статистика по заказам
        total_orders = (await s.execute(
            select(func.count()).select_from(Order).where(Order.order_type == "retail")
        )).scalar_one()
        
        today_orders = (await s.execute(
            select(func.count()).select_from(Order).where(
                and_(
                    Order.order_type == "retail",
                    Order.created_at >= datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
                )
            )
        )).scalar_one()
        
        # Статистика по корзинам
        active_carts = (await s.execute(
            select(func.count()).select_from(Cart).where(Cart.items != None)
        )).scalar_one()
        
        # Топ категории
        top_categories = (await s.execute(
            select(
                MonitoredPost.category,
                func.count(Product.id).label('cnt')
            )
            .join(Product, 
                  and_(
                      Product.channel_id == MonitoredPost.channel_id,
                      Product.group_message_id == MonitoredPost.message_id
                  ))
            .where(
                and_(
                    MonitoredPost.channel_id == CHANNEL_ID_STORE,
                    Product.available == True,
                    Product.price_retail != None
                )
            )
            .group_by(MonitoredPost.category)
            .order_by(func.count(Product.id).desc())
            .limit(5)
        )).all()
        
        # Статистика по настройкам
        settings_count = (await s.execute(
            select(func.count()).select_from(BotSetting)
        )).scalar_one()
        
        # Статистика по админам
        admins_count = (await s.execute(
            select(func.count()).select_from(BotAdmin).where(BotAdmin.channel_type == "retail")
        )).scalar_one()
        
        # Мониторинг каналов
        monitored_posts = (await s.execute(
            select(func.count()).select_from(MonitoredPost).where(MonitoredPost.channel_id == CHANNEL_ID_STORE)
        )).scalar_one()
    
    # Формируем отчет
    lines = [
        "🔍 <b>ДИАГНОСТИКА РОЗНИЧНОГО БОТА</b>",
        "",
        "📊 <b>Товары:</b>",
        f"• Всего товаров: <b>{total_products}</b>",
        f"• Доступно сейчас: <b>{available_products}</b>",
        f"• Процент доступности: <b>{(available_products/total_products*100) if total_products > 0 else 0:.1f}%</b>",
        "",
        "📝 <b>Заказы:</b>",
        f"• Всего заказов: <b>{total_orders}</b>",
        f"• Заказов сегодня: <b>{today_orders}</b>",
        "",
        "🛒 <b>Корзины:</b>",
        f"• Активных корзин: <b>{active_carts}</b>",
        "",
        "⚙️ <b>Система:</b>",
        f"• Настроек в БД: <b>{settings_count}</b>",
        f"• Админов: <b>{admins_count}</b>",
        f"• Мониторинг постов: <b>{monitored_posts}</b>",
    ]
    
    if top_categories:
        lines.extend([
            "",
            "🏆 <b>Топ категории:</b>"
        ])
        for cat, cnt in top_categories:
            cat_name = cat or "Без категории"
            lines.append(f"• {cat_name}: <b>{cnt}</b> товаров")
    
    # Проверка конфигурации
    lines.extend([
        "",
        "🔧 <b>Конфигурация:</b>",
        f"• Розничный канал: <b>{CHANNEL_ID_STORE}</b>",
        f"• Оптовый канал: <b>{CHANNEL_ID_OPT}</b>",
        f"• Группа менеджеров: <b>{MANAGER_GROUP_ID}</b>",
        f"• Менеджеров: <b>{len(MANAGER_USER_IDS)}</b>",
    ])
    
    # Проверка состояния системы
    status_lines = []
    if total_products == 0:
        status_lines.append("⚠️ Нет товаров в каталоге")
    if available_products == 0:
        status_lines.append("⚠️ Нет доступных товаров")
    if monitored_posts == 0:
        status_lines.append("⚠️ Не настроен мониторинг каналов")
    if admins_count == 0:
        status_lines.append("⚠️ Нет админов в системе")
    
    if status_lines:
        lines.extend([
            "",
            "⚠️ <b>Проблемы:</b>"
        ])
        lines.extend([f"• {status}" for status in status_lines])
    else:
        lines.extend([
            "",
            "✅ <b>Система работает нормально</b>"
        ])
    
    await m.answer("\n".join(lines), parse_mode="HTML", reply_markup=await main_menu_kb(m.from_user.id if m.from_user else 0, m.chat.type))

@dp.message(Command("fix_categories"))
async def cmd_fix_categories(m: Message):
    """Админ-команда: пересинхронизировать категории товаров из monitored_posts по message_id."""
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    if not CHANNEL_ID_OPT:
        await m.answer("❗ Не задан CHANNEL_ID_OPT")
        return
    await m.answer("🔧 Пересинхронизация категорий товаров…")
    
    # Инициализируем переменные
    opt_updated = 0
    retail_updated = 0
    result_text = ""  # Инициализируем переменную для результата
    
    try:
        # Обновляем для оптового канала
        if CHANNEL_ID_OPT:
            async with Session() as s:
                # Обновляем категории продуктов из monitored_posts по group_message_id
                await s.execute(text(
                """
                UPDATE products AS p
                SET category = mp.category
                FROM monitored_posts AS mp
                WHERE p.channel_id = :cid
                  AND mp.channel_id = :cid
                  AND p.group_message_id = mp.message_id
                  AND COALESCE(p.category, '') IS DISTINCT FROM COALESCE(mp.category, '')
                """
            ), {"cid": CHANNEL_ID_OPT})
                await s.commit()
                
                # Считаем обновленные записи
                opt_updated = (await s.execute(text(
                """
                SELECT COUNT(*) FROM products p
                JOIN monitored_posts mp
                  ON mp.channel_id = p.channel_id AND mp.message_id = p.group_message_id
                WHERE p.channel_id = :cid
                  AND COALESCE(p.category, '') = COALESCE(mp.category, '')
                """
            ), {"cid": CHANNEL_ID_OPT})).scalar() or 0
        
        # Обновляем для розничного канала
        if CHANNEL_ID_STORE:
            async with Session() as s:
                await s.execute(text(
                    """
                    UPDATE products AS p
                    SET category = mp.category
                    FROM monitored_posts AS mp
                    WHERE p.channel_id = :cid
                      AND mp.channel_id = :cid
                      AND p.group_message_id = mp.message_id
                      AND COALESCE(p.category, '') IS DISTINCT FROM COALESCE(mp.category, '')
                    """
                ), {"cid": CHANNEL_ID_STORE})
                await s.commit()
                
                retail_updated = (await s.execute(text(
                    """
                    SELECT COUNT(*) FROM products p
                    JOIN monitored_posts mp
                      ON mp.channel_id = p.channel_id AND mp.message_id = p.group_message_id
                    WHERE p.channel_id = :cid
                      AND COALESCE(p.category, '') = COALESCE(mp.category, '')
                    """
                ), {"cid": CHANNEL_ID_STORE})).scalar() or 0
        
        # Показываем результат
        result_text = "✅ <b>Категории пересинхронизированы!</b>\n\n"
        result_text += f"📊 <b>Результат:</b>\n"
        result_text += f"• 🏢 Оптовый канал: {opt_updated} товаров с правильными категориями\n"
        result_text += f"• 🏪 Розничный канал: {retail_updated} товаров с правильными категориями\n"
        result_text += f"• 📈 Всего: {opt_updated + retail_updated} товаров\n\n"
        result_text += "💡 <i>Теперь все товары имеют актуальные категории из monitored_posts</i>"
        
        await m.answer(result_text, parse_mode="HTML")
        
    except Exception as e:
        log.error(f"Error in fix_categories: {e}")
        await m.answer(f"❌ Ошибка при обновлении категорий: {e}")
        return

@dp.message(Command("set_post_category"))
async def cmd_set_post_category(m: Message):
    """Админ-команда: вручную установить категорию для поста.
    Использование: /set_post_category <message_id> <category> [opt|store]
    """
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    
    parts = (m.text or "").split(None, 3)
    if len(parts) < 3:
        await m.answer("Формат: /set_post_category <message_id> <category> [opt|store]")
        return
    
    try:
        mid = int(parts[1])
    except Exception:
        await m.answer("message_id должен быть числом")
        return
    
    new_cat = parts[2].strip()
    
    # Определяем канал (по умолчанию opt для обратной совместимости)
    channel_type = parts[3] if len(parts) > 3 else "opt"
    channel_id = CHANNEL_ID_OPT if channel_type == "opt" else CHANNEL_ID_STORE
    channel_name = "оптовом" if channel_type == "opt" else "розничном"
    
    if not channel_id:
        await m.answer(f"❌ Канал {channel_type} не настроен")
        return
    
    try:
        async with Session() as s:
            # Проверяем, существует ли пост
            existing = (await s.execute(
                select(MonitoredPost)
                .where(MonitoredPost.channel_id == channel_id)
                .where(MonitoredPost.message_id == mid)
            )).scalar_one_or_none()
            
            if existing:
                # Обновляем существующий пост
                existing.category = new_cat
                await s.commit()
                await m.answer(f"✅ Категория поста {mid} в {channel_name} канале обновлена на: {new_cat}\n💡 Выполните /rescan для обновления товаров.")
            else:
                # Создаем новый пост
                new_post = MonitoredPost(
                    channel_id=channel_id,
                    message_id=mid,
                    category=new_cat,
                    is_active=True
                )
                s.add(new_post)
                await s.commit()
                await m.answer(f"✅ Создан новый пост {mid} в {channel_name} канале с категорией: {new_cat}\n💡 Выполните /rescan для обновления товаров.")
                
    except Exception as e:
        log.error(f"Error setting post category: {e}")
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("set_category_posts"))
async def cmd_set_category_posts(m: Message):
    """
    Установить несколько постов для одной категории
    Формат: /set_category_posts "🍏 iPad" 9,10 [opt|store]
    """
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    
    parts = (m.text or "").split(None, 3)
    if len(parts) < 3:
        await m.answer("Формат: /set_category_posts \"Категория\" 9,10,11 [opt|store]")
        return
    
    category = parts[1].strip('"')
    try:
        message_ids = [int(x.strip()) for x in parts[2].split(",")]
    except Exception:
        await m.answer("Некорректные ID постов")
        return
    
    # Определяем канал (по умолчанию opt для обратной совместимости)
    channel_type = parts[3] if len(parts) > 3 else "opt"
    channel_id = CHANNEL_ID_OPT if channel_type == "opt" else CHANNEL_ID_STORE
    channel_name = "оптовом" if channel_type == "opt" else "розничном"
    
    if not channel_id:
        await m.answer(f"❌ Канал {channel_type} не настроен")
        return
    
    try:
        async with Session() as s:
            updated_count = 0
            created_count = 0
            
            for mid in message_ids:
                # Проверяем, существует ли пост
                existing = (await s.execute(
                    select(MonitoredPost)
                    .where(MonitoredPost.channel_id == channel_id)
                    .where(MonitoredPost.message_id == mid)
                )).scalar_one_or_none()
                
                if existing:
                    # Обновляем существующий пост
                    existing.category = category
                    updated_count += 1
                else:
                    # Создаем новый пост
                    new_post = MonitoredPost(
                        channel_id=channel_id,
                        message_id=mid,
                        category=category,
                        is_active=True
                    )
                    s.add(new_post)
                    created_count += 1
            
            await s.commit()
            
            result_msg = f"✅ Категория '{category}' установлена для постов в {channel_name} канале:\n"
            if updated_count > 0:
                result_msg += f"• Обновлено: {updated_count} постов\n"
            if created_count > 0:
                result_msg += f"• Создано: {created_count} постов\n"
            result_msg += f"• ID постов: {message_ids}\n\n"
            result_msg += "💡 Выполните /rescan для обновления товаров"
            
            await m.answer(result_msg)
            
    except Exception as e:
        log.error(f"Error setting category posts: {e}")
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("create_monitored_post"))
async def cmd_create_monitored_post(m: Message):
    """
    Создать новый пост для мониторинга
    Формат: /create_monitored_post 123 "Категория" [opt|store]
    """
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    
    parts = (m.text or "").split(None, 3)
    if len(parts) < 3:
        await m.answer("Формат: /create_monitored_post <message_id> \"Категория\" [opt|store]")
        return
    
    try:
        mid = int(parts[1])
    except Exception:
        await m.answer("message_id должен быть числом")
        return
    
    category = parts[2].strip('"')
    
    # Определяем канал (по умолчанию opt для обратной совместимости)
    channel_type = parts[3] if len(parts) > 3 else "opt"
    channel_id = CHANNEL_ID_OPT if channel_type == "opt" else CHANNEL_ID_STORE
    channel_name = "оптовом" if channel_type == "opt" else "розничном"
    
    if not channel_id:
        await m.answer(f"❌ Канал {channel_type} не настроен")
        return
    
    try:
        async with Session() as s:
            # Проверяем, существует ли уже такой пост
            existing = (await s.execute(
                select(MonitoredPost)
                .where(MonitoredPost.channel_id == channel_id)
                .where(MonitoredPost.message_id == mid)
            )).scalar_one_or_none()
            
            if existing:
                await m.answer(f"⚠️ Пост {mid} уже существует в {channel_name} канале с категорией: {existing.category}")
                return
            
            # Создаем новый пост
            new_post = MonitoredPost(
                channel_id=channel_id,
                message_id=mid,
                category=category,
                is_active=True
            )
            s.add(new_post)
            await s.commit()
            
            await m.answer(f"✅ Создан новый пост {mid} в {channel_name} канале:\n"
                          f"• Категория: {category}\n"
                          f"• Статус: Активен\n\n"
                          f"💡 Выполните /rescan для обновления товаров")
            
    except Exception as e:
        log.error(f"Error creating monitored post: {e}")
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("list_monitored_posts"))
async def cmd_list_monitored_posts(m: Message):
    """
    Показать все посты мониторинга
    Формат: /list_monitored_posts [opt|store]
    """
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    
    parts = (m.text or "").split(None, 1)
    channel_type = parts[1] if len(parts) > 1 else "all"
    
    try:
        async with Session() as s:
            query = select(MonitoredPost).where(MonitoredPost.is_active == True)
            
            if channel_type == "opt":
                query = query.where(MonitoredPost.channel_id == CHANNEL_ID_OPT)
                channel_name = "Оптовый"
            elif channel_type == "store":
                query = query.where(MonitoredPost.channel_id == CHANNEL_ID_STORE)
                channel_name = "Розничный"
            else:
                channel_name = "Все"
            
            posts = (await s.execute(query.order_by(MonitoredPost.channel_id, MonitoredPost.message_id))).scalars().all()
            
            if not posts:
                await m.answer(f"📝 Нет активных постов мониторинга для {channel_name.lower()} канала")
                return
            
            text = f"📝 <b>Посты мониторинга ({channel_name} канал)</b>\n\n"
            
            current_channel = None
            for post in posts:
                if current_channel != post.channel_id:
                    current_channel = post.channel_id
                    channel_display = "🏢 Оптовый" if post.channel_id == CHANNEL_ID_OPT else "🏪 Розничный"
                    text += f"\n<b>{channel_display} канал:</b>\n"
                
                category = post.category or "Без категории"
                text += f"• Пост {post.message_id}: {category}\n"
            
            text += f"\n📊 <b>Всего постов:</b> {len(posts)}"
            
            await m.answer(text, parse_mode="HTML")
            
    except Exception as e:
        log.error(f"Error listing monitored posts: {e}")
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("sync_monitoring"))
async def cmd_sync_monitoring(m: Message):
    """
    Показать текущее состояние мониторинга
    Формат: /sync_monitoring [opt|store]
    """
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    
    parts = (m.text or "").split(None, 1)
    channel_type = parts[1] if len(parts) > 1 else "all"
    
    try:
        await m.answer("📊 Анализирую состояние мониторинга...")
        
        text = "📊 <b>Состояние мониторинга</b>\n\n"
        
        if channel_type in ["opt", "all"]:
            opt_ids = await get_monitored_message_ids("opt")
            text += f"<b>🏢 Оптовый канал ({len(opt_ids)} постов):</b>\n"
            text += f"• Посты: {', '.join(map(str, sorted(opt_ids))) if opt_ids else 'Не настроено'}\n\n"
        
        if channel_type in ["store", "all"]:
            store_ids = await get_monitored_message_ids("store")
            text += f"<b>🏪 Розничный канал ({len(store_ids)} постов):</b>\n"
            text += f"• Посты: {', '.join(map(str, sorted(store_ids))) if store_ids else 'Не настроено'}\n\n"
        
        text += "💡 <i>Настройки мониторинга работают напрямую с БД</i>"
        
        await m.answer(text, parse_mode="HTML")
        
    except Exception as e:
        log.error(f"Error checking monitoring: {e}")
        await m.answer(f"❌ Ошибка при проверке: {e}")

@dp.message(Command("compare_monitoring"))
async def cmd_compare_monitoring(m: Message):
    """
    Сравнить настройки мониторинга с реальными данными в БД
    Формат: /compare_monitoring [opt|store]
    """
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    
    parts = (m.text or "").split(None, 1)
    channel_type = parts[1] if len(parts) > 1 else "all"
    
    try:
        async with Session() as s:
            text = "📊 <b>Сравнение настроек мониторинга с БД</b>\n\n"
            
            if channel_type in ["opt", "all"]:
                # Сравниваем оптовый канал
                if CHANNEL_ID_OPT:
                    # Настройки из bot_settings
                    settings_ids = await get_monitored_message_ids("opt")
                    
                    # Реальные данные из БД
                    db_posts = (await s.execute(
                        select(MonitoredPost)
                        .where(MonitoredPost.channel_id == CHANNEL_ID_OPT)
                        .where(MonitoredPost.is_active == True)
                    )).scalars().all()
                    db_ids = {post.message_id for post in db_posts}
                    
                    text += f"🏢 <b>Оптовый канал:</b>\n"
                    text += f"• Настройки: {sorted(settings_ids) if settings_ids else 'Пусто'}\n"
                    text += f"• База данных: {sorted(db_ids) if db_ids else 'Пусто'}\n"
                    
                    # Анализ различий
                    only_in_settings = settings_ids - db_ids
                    only_in_db = db_ids - settings_ids
                    common = settings_ids & db_ids
                    
                    text += f"• Общие: {len(common)} постов\n"
                    if only_in_settings:
                        text += f"• Только в настройках: {sorted(only_in_settings)}\n"
                    if only_in_db:
                        text += f"• Только в БД: {sorted(only_in_db)}\n"
                    text += "\n"
            
            if channel_type in ["store", "all"]:
                # Сравниваем розничный канал
                if CHANNEL_ID_STORE:
                    # Настройки из bot_settings
                    settings_ids = await get_monitored_message_ids("store")
                    
                    # Реальные данные из БД
                    db_posts = (await s.execute(
                        select(MonitoredPost)
                        .where(MonitoredPost.channel_id == CHANNEL_ID_STORE)
                        .where(MonitoredPost.is_active == True)
                    )).scalars().all()
                    db_ids = {post.message_id for post in db_posts}
                    
                    text += f"🏪 <b>Розничный канал:</b>\n"
                    text += f"• Настройки: {sorted(settings_ids) if settings_ids else 'Пусто'}\n"
                    text += f"• База данных: {sorted(db_ids) if db_ids else 'Пусто'}\n"
                    
                    # Анализ различий
                    only_in_settings = settings_ids - db_ids
                    only_in_db = db_ids - settings_ids
                    common = settings_ids & db_ids
                    
                    text += f"• Общие: {len(common)} постов\n"
                    if only_in_settings:
                        text += f"• Только в настройках: {sorted(only_in_settings)}\n"
                    if only_in_db:
                        text += f"• Только в БД: {sorted(only_in_db)}\n"
                    text += "\n"
            
            text += "💡 <i>Используйте /sync_monitoring для синхронизации</i>"
            
            await m.answer(text, parse_mode="HTML")
            
    except Exception as e:
        log.error(f"Error comparing monitoring: {e}")
        await m.answer(f"❌ Ошибка при сравнении: {e}")

@dp.message(Command("sync_monitoring_to_db"))
async def cmd_sync_monitoring_to_db(m: Message):
    """
    Синхронизировать настройки мониторинга с БД - создать записи MonitoredPost для всех постов из настроек
    Формат: /sync_monitoring_to_db [opt|store]
    """
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    
    parts = (m.text or "").split(None, 1)
    channel_type = parts[1] if len(parts) > 1 else "all"
    
    try:
        await m.answer("🔄 Синхронизирую настройки мониторинга с БД...")
        
        created_count = 0
        
        async with Session() as s:
            if channel_type in ["opt", "all"]:
                # Оптовый канал
                opt_ids = await get_monitored_message_ids("opt")
                if opt_ids:
                    for message_id in opt_ids:
                        # Проверяем, есть ли уже запись
                        existing = (await s.execute(
                            select(MonitoredPost)
                            .where(MonitoredPost.channel_id == CHANNEL_ID_OPT)
                            .where(MonitoredPost.message_id == message_id)
                        )).scalar_one_or_none()
                        
                        if not existing:
                            # Создаем новую запись
                            new_post = MonitoredPost(
                                channel_id=CHANNEL_ID_OPT,
                                message_id=message_id,
                                category="Без категории",
                                is_active=True
                            )
                            s.add(new_post)
                            created_count += 1
            
            if channel_type in ["store", "all"]:
                # Розничный канал
                store_ids = await get_monitored_message_ids("store")
                if store_ids:
                    for message_id in store_ids:
                        # Проверяем, есть ли уже запись
                        existing = (await s.execute(
                            select(MonitoredPost)
                            .where(MonitoredPost.channel_id == CHANNEL_ID_STORE)
                            .where(MonitoredPost.message_id == message_id)
                        )).scalar_one_or_none()
                        
                        if not existing:
                            # Создаем новую запись
                            new_post = MonitoredPost(
                                channel_id=CHANNEL_ID_STORE,
                                message_id=message_id,
                                category="Без категории",
                                is_active=True
                            )
                            s.add(new_post)
                            created_count += 1
            
            await s.commit()
        
        await m.answer(f"✅ Синхронизация завершена!\n\n"
                      f"📊 Создано записей: {created_count}\n"
                      f"💡 Теперь все посты из настроек мониторинга доступны для редактирования категорий")
        
    except Exception as e:
        log.error(f"Error syncing monitoring to DB: {e}")
        await m.answer(f"❌ Ошибка: {e}")

# --- Настройки (админ): inline-UI + команды ---
BTN_SETTINGS_CONTACTS = "✏️ Контакты"
BTN_SETTINGS_TEMPLATES = "🧩 Шаблоны"
BTN_SETTINGS_BACK = "⬅️ Назад"

def settings_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_SETTINGS_CONTACTS, callback_data="settings:contacts")],
        [InlineKeyboardButton(text=BTN_SETTINGS_TEMPLATES, callback_data="settings:tpls")],
        [InlineKeyboardButton(text="📡 Мониторинг постов", callback_data="settings:monitoring")],
        [InlineKeyboardButton(text="🏷️ Управление категориями", callback_data="settings:categories")],
        [InlineKeyboardButton(text="👥 Управление админами", callback_data="settings:admins")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="settings:back_to_menu")],
    ])

def templates_list_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Заказ оформлен (1 товар)", callback_data="settings:tpl:order_placed_single")],
        [InlineKeyboardButton(text="✅ Заказ оформлен (несколько)", callback_data="settings:tpl:order_placed_multiple")],
        [InlineKeyboardButton(text="📢 Уведомление админам (личное)", callback_data="settings:tpl:admin_order_notification_personal")],
        [InlineKeyboardButton(text="📢 Уведомление админам (группа)", callback_data="settings:tpl:admin_order_notification_group")],
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data="settings:back")],
    ])

@dp.message(F.text.in_([BTN_SETTINGS, BTN_SETTINGS_ADMIN]))
@dp.message(Command("settings"))
async def on_settings(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    await m.answer("⚙️ <b>Настройки</b>\nВыберите раздел:", parse_mode="HTML", reply_markup=settings_root_kb())

@dp.callback_query(F.data == "settings:back")
async def settings_back(c: CallbackQuery):
    try:
        await c.message.edit_text("⚙️ <b>Настройки</b>\nВыберите раздел:", parse_mode="HTML", reply_markup=settings_root_kb())
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=settings_root_kb())
    await c.answer()

@dp.callback_query(F.data == "settings:back_to_menu")
async def settings_back_to_menu(c: CallbackQuery):
    try:
        # Отправляем новое сообщение с главным меню
        await c.message.answer("🏠 <b>Главное меню</b>\nВыберите действие:", parse_mode="HTML", reply_markup=await main_menu_kb(c.from_user.id if c.from_user else 0, c.message.chat.type))
    except Exception as e:
        log.error(f"Error sending main menu: {e}")
    await c.answer()

@dp.callback_query(F.data == "settings:contacts")
async def settings_contacts(c: CallbackQuery):
    text = await get_contacts_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить контакты", callback_data="settings:contacts:edit")],
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data="settings:back")],
    ])
    try:
        await c.message.edit_text(f"Текущие контакты:\n\n{text}", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

PENDING_TEMPLATE_EDIT = {}  # type: Dict[int, str]  # admin_id -> template_name
PENDING_CONTACTS_EDIT = {}  # type: Dict[int, bool]  # admin_id -> waiting flag
PENDING_ADMIN_ADD = {}  # type: Dict[int, bool]
PENDING_ADMIN_REMOVE = {}  # type: Dict[int, bool]
PENDING_CATEGORY_EDIT = {}  # type: Dict[int, dict]

@dp.callback_query(F.data == "settings:contacts:edit")
async def settings_contacts_edit(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    PENDING_CONTACTS_EDIT[c.from_user.id] = True
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="settings:cancel_contacts")]
    ])
    await c.message.reply(
        "✏️ <b>Режим редактирования контактов</b>\n\n"
        "Пришлите <b>следующим сообщением</b> новый текст контактов.\n\n"
        "💡 <i>Вы можете использовать HTML-разметку для форматирования</i>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await c.answer("Режим редактирования включен")

@dp.callback_query(F.data == "settings:tpls")
async def settings_templates(c: CallbackQuery):
    try:
        await c.message.edit_text("Выберите шаблон для просмотра/редактирования:", reply_markup=templates_list_kb())
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=templates_list_kb())
    await c.answer()

@dp.callback_query(F.data.regexp(r"^settings:tpl:(.+)$"))
async def settings_template_open(c: CallbackQuery):
    name = c.data.split(":")[2]
    tpl = await get_template(name)
    
    # Описания шаблонов для пользователей
    descriptions = {
        "order_received": (
            "📝 <b>Подтверждение заказа (одиночный товар)</b>\n\n"
            "🎯 <b>Когда отправляется:</b> Сразу после оформления одного товара\n"
            "📋 <b>Содержит:</b> Информацию о товаре, количестве, цене и общей сумме\n"
            "💬 <b>Тон:</b> Позитивный, информативный, с обещанием связи\n"
            "🎨 <b>Особенности:</b> Красивое оформление с эмодзи, четкая структура\n"
            "🔄 <b>Отличие от корзины:</b> Для одного товара, не для нескольких"
        ),
        "order_approved": (
            "✅ <b>Заказ одобрен</b>\n\n"
            "🎯 <b>Когда отправляется:</b> После одобрения заказа менеджером\n"
            "📋 <b>Содержит:</b> Подтверждение заказа, детали товара, информацию о доставке\n"
            "💬 <b>Тон:</b> Праздничный, радостный, с благодарностью\n"
            "🎨 <b>Особенности:</b> Поздравительный стиль, мотивирующие эмодзи"
        ),
        "order_rejected": (
            "❌ <b>Заказ отклонен</b>\n\n"
            "🎯 <b>Когда отправляется:</b> При отклонении заказа менеджером\n"
            "📋 <b>Содержит:</b> Вежливое уведомление об отказе и возможные причины\n"
            "💬 <b>Тон:</b> Вежливый, сочувствующий, с предложением альтернатив\n"
            "🎨 <b>Особенности:</b> Тактичное объяснение, мотивация к повторному заказу"
        ),
        "cart_checkout_summary": (
            "🧺 <b>Итоги корзины (несколько товаров)</b>\n\n"
            "🎯 <b>Когда отправляется:</b> После оформления корзины с несколькими товарами\n"
            "📋 <b>Содержит:</b> Список всех товаров, количество позиций, итоговую сумму\n"
            "💬 <b>Тон:</b> Поздравительный, обнадеживающий, с ожиданием связи\n"
            "🎨 <b>Особенности:</b> Показывает все товары из корзины, сводная информация\n"
            "🔄 <b>Отличие от одиночного заказа:</b> Для нескольких товаров одновременно"
        )
    }
    
    description = descriptions.get(name, f"<b>{name}</b>")
    
    # Показываем только первые 500 символов шаблона
    tpl_preview = tpl[:500] + "..." if len(tpl) > 500 else tpl
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить шаблон", callback_data=f"settings:tpl_edit:{name}")],
        [InlineKeyboardButton(text="📋 Показать полностью", callback_data=f"settings:tpl_full:{name}")],
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data="settings:tpls")],
    ])
    
    text = f"{description}\n\n<b>Текущий шаблон:</b>\n<code>{html.quote(tpl_preview)}</code>"
    
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data.regexp(r"^settings:tpl_full:(.+)$"))
async def settings_template_full(c: CallbackQuery):
    name = c.data.split(":")[2]
    tpl = await get_template(name)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить шаблон", callback_data=f"settings:tpl_edit:{name}")],
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data=f"settings:tpl:{name}")],
    ])
    
    text = f"<b>Полный шаблон {name}:</b>\n\n<code>{html.quote(tpl)}</code>"
    
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data.regexp(r"^settings:tpl_edit:(.+)$"))
async def settings_template_edit(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    name = c.data.split(":")[2]
    if name not in DEFAULT_TEMPLATES:
        await c.answer("Неверное имя шаблона.", show_alert=True)
        return
    PENDING_TEMPLATE_EDIT[c.from_user.id] = name
    # Определяем плейсхолдеры для каждого шаблона
    placeholders_by_tpl = {
        "order_placed_single": "{product_name}, {quantity}, {price_each}, {total}, {address}, {contacts}",
        "order_placed_multiple": "{cart_items}, {items_count}, {total}, {address}, {contacts}",
        "admin_order_notification_personal": "{order_id}, {user_id}, {username_info}, {product_name}, {quantity}, {price_each}, {total_price}",
        "admin_order_notification_group": "{order_id}, {user_id}, {username_info}, {product_name}, {quantity}, {price_each}, {total_price}"
    }
    
    ph = placeholders_by_tpl.get(name, "{contacts}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="settings:cancel_template")]
    ])
    await c.message.reply(
        f"Пришлите <b>следующим сообщением</b> новый текст шаблона <code>{name}</code>.\n\n"
        f"📝 <b>Доступные плейсхолдеры:</b> {ph}\n\n"
        f"🎨 <b>Стилизация текста:</b>\n"
        f"• <b>жирный текст</b> → <code>&lt;b&gt;текст&lt;/b&gt;</code>\n"
        f"• <i>курсив</i> → <code>&lt;i&gt;текст&lt;/i&gt;</code>\n"
        f"• <u>подчеркнутый</u> → <code>&lt;u&gt;текст&lt;/u&gt;</code>\n"
        f"• <s>зачеркнутый</s> → <code>&lt;s&gt;текст&lt;/s&gt;</code>\n"
        f"• <code>моноширинный</code> → <code>&lt;code&gt;текст&lt;/code&gt;</code>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await c.answer()

@dp.callback_query(F.data == "settings:monitoring")
async def settings_monitoring(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    
    # Получаем текущие настройки
    store_ids = await get_monitored_message_ids("store")
    opt_ids = await get_monitored_message_ids("opt")
    store_master = await get_master_message_id("store")
    opt_master = await get_master_message_id("opt")
    
    text = (
        "📡 <b>Настройки мониторинга постов</b>\n\n"
        f"<b>Розничный канал:</b>\n"
        f"• Мониторимые посты: {', '.join(map(str, sorted(store_ids))) if store_ids else 'Не настроено'}\n"
        f"• Главное сообщение: {store_master or 'Не настроено'}\n\n"
        f"<b>Оптовый канал:</b>\n"
        f"• Мониторимые посты: {', '.join(map(str, sorted(opt_ids))) if opt_ids else 'Не настроено'}\n"
        f"• Главное сообщение: {opt_master or 'Не настроено'}\n\n"
        "Выберите что настроить:"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏪 Розничный канал", callback_data="settings:monitoring:store")],
        [InlineKeyboardButton(text="🏢 Оптовый канал", callback_data="settings:monitoring:opt")],
        [InlineKeyboardButton(text="🔄 Синхронизировать", callback_data="settings:monitoring:sync")],
        [InlineKeyboardButton(text="📊 Сравнить", callback_data="settings:monitoring:compare")],
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data="settings:back")],
    ])
    
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data.regexp(r"^settings:monitoring:(store|opt)$"))
async def settings_monitoring_channel(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    
    channel_type = c.data.split(":")[2]
    channel_name = "розничном" if channel_type == "store" else "оптовом"
    
    # Получаем текущие настройки
    message_ids = await get_monitored_message_ids(channel_type)
    master_id = await get_master_message_id(channel_type)
    
    text = (
        f"📡 <b>Настройки {channel_name} канала</b>\n\n"
        f"<b>Текущие настройки:</b>\n"
        f"• Мониторимые посты: {', '.join(map(str, sorted(message_ids))) if message_ids else 'Не настроено'}\n"
        f"• Главное сообщение: {master_id or 'Не настроено'}\n\n"
        "Выберите что изменить:"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Мониторимые посты", callback_data=f"settings:monitoring:{channel_type}:posts")],
        [InlineKeyboardButton(text="📌 Главное сообщение", callback_data=f"settings:monitoring:{channel_type}:master")],
        [InlineKeyboardButton(text="🔗 Объединить посты", callback_data=f"settings:monitoring:{channel_type}:merge")],
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data="settings:monitoring")],
    ])
    
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data.regexp(r"^settings:monitoring:(store|opt):posts$"))
async def settings_monitoring_posts(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    
    channel_type = c.data.split(":")[2]
    channel_name = "розничном" if channel_type == "store" else "оптовом"
    
    # Получаем текущие настройки
    message_ids = await get_monitored_message_ids(channel_type)
    
    text = (
        f"📝 <b>Настройка мониторимых постов ({channel_name} канал)</b>\n\n"
        f"<b>Текущие ID постов:</b>\n"
        f"{', '.join(map(str, sorted(message_ids))) if message_ids else 'Не настроено'}\n\n"
        f"<b>🔧 Доступные команды:</b>\n"
        f"• <code>/set_monitored_{channel_type} 1,2,3</code> - заменить весь список\n"
        f"• <code>/add_monitored_{channel_type} 4,5</code> - добавить к существующим\n"
        f"• <code>/remove_monitored_{channel_type} 1,2</code> - удалить из списка\n\n"
        f"💡 <i>ID постов можно найти в ссылках на сообщения канала</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data=f"settings:monitoring:{channel_type}")],
    ])
    
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data.regexp(r"^settings:monitoring:(store|opt):master$"))
async def settings_monitoring_master(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    
    channel_type = c.data.split(":")[2]
    channel_name = "розничном" if channel_type == "store" else "оптовом"
    
    # Получаем текущие настройки
    master_id = await get_master_message_id(channel_type)
    
    text = (
        f"📌 <b>Настройка главного сообщения ({channel_name} канал)</b>\n\n"
        f"<b>Текущий ID:</b> {master_id or 'Не настроено'}\n\n"
        f"<b>Как изменить:</b>\n"
        f"1. Скопируйте команду ниже\n"
        f"2. Замените число на нужный ID\n"
        f"3. Отправьте команду боту\n\n"
        f"<b>Команда для копирования:</b>\n"
        f"<code>/set_master_{channel_type} 123</code>\n\n"
        f"💡 <i>ID сообщения можно найти в ссылке на него</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data=f"settings:monitoring:{channel_type}")],
    ])
    
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data.regexp(r"^settings:monitoring:(store|opt):merge$"))
async def settings_monitoring_merge(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    
    channel_type = c.data.split(":")[2]
    channel_name = "розничном" if channel_type == "store" else "оптовом"
    
    text = (
        f"🔗 <b>Объединение постов ({channel_name} канал)</b>\n\n"
        f"<b>Что это:</b> Объединяет несколько постов под одной категорией товаров.\n"
        f"Полезно, когда товары одной категории разбиты на несколько постов.\n\n"
        f"<b>Как использовать:</b>\n"
        f"1. Скопируйте команду ниже\n"
        f"2. Замените категорию и ID постов\n"
        f"3. Отправьте команду боту\n\n"
        f"<b>Команда для копирования:</b>\n"
        f"<code>/set_category_posts \"🍏 iPad\" 9,10</code>\n\n"
        f"<b>Примеры:</b>\n"
        f"• <code>/set_category_posts \"🔌 Аксы Apple\" 12,13,14</code>\n"
        f"• <code>/set_category_posts \"📱 Samsung\" 6,7</code>\n\n"
        f"💡 <i>После изменения выполните /rescan для обновления товаров</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data=f"settings:monitoring:{channel_type}")],
    ])
    
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data == "settings:monitoring:sync")
async def settings_monitoring_sync(c: CallbackQuery):
    """Синхронизация настроек мониторинга с БД"""
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    
    try:
        await c.message.edit_text("🔄 Синхронизирую настройки мониторинга с БД...")
        
        # Теперь синхронизация не нужна - настройки работают напрямую с БД
        # Просто показываем текущее состояние
        opt_ids = await get_monitored_message_ids("opt")
        store_ids = await get_monitored_message_ids("store")
        
        text = (
            "✅ <b>Настройки мониторинга</b>\n\n"
            f"<b>Розничный канал:</b> {len(store_ids)} постов\n"
            f"• Посты: {', '.join(map(str, sorted(store_ids))) if store_ids else 'Не настроено'}\n\n"
            f"<b>Оптовый канал:</b> {len(opt_ids)} постов\n"
            f"• Посты: {', '.join(map(str, sorted(opt_ids))) if opt_ids else 'Не настроено'}\n\n"
            "💡 <i>Настройки мониторинга работают напрямую с БД</i>"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Сравнить", callback_data="settings:monitoring:compare")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:monitoring")],
        ])
        
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        
    except Exception as e:
        log.error(f"Error syncing monitoring: {e}")
        await c.answer(f"❌ Ошибка при синхронизации: {e}", show_alert=True)
    await c.answer()

@dp.callback_query(F.data == "settings:monitoring:compare")
async def settings_monitoring_compare(c: CallbackQuery):
    """Показать текущее состояние мониторинга"""
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    
    try:
        await c.message.edit_text("📊 Анализирую состояние мониторинга...")
        
        # Получаем данные напрямую из БД
        store_ids = await get_monitored_message_ids("store")
        opt_ids = await get_monitored_message_ids("opt")
        
        # Получаем дополнительную информацию о постах
        store_posts_info = []
        opt_posts_info = []
        
        async with Session() as s:
            if store_ids:
                store_posts = (await s.execute(
                    select(MonitoredPost)
                    .where(MonitoredPost.channel_id == CHANNEL_ID_STORE)
                    .where(MonitoredPost.message_id.in_(store_ids))
                )).scalars().all()
                store_posts_info = [(post.message_id, post.category or "Без категории") for post in store_posts]
            
            if opt_ids:
                opt_posts = (await s.execute(
                    select(MonitoredPost)
                    .where(MonitoredPost.channel_id == CHANNEL_ID_OPT)
                    .where(MonitoredPost.message_id.in_(opt_ids))
                )).scalars().all()
                opt_posts_info = [(post.message_id, post.category or "Без категории") for post in opt_posts]
        
        text = "📊 <b>Текущее состояние мониторинга</b>\n\n"
        
        text += f"<b>🏪 Розничный канал ({len(store_ids)} постов):</b>\n"
        for message_id, category in sorted(store_posts_info):
            text += f"• Пост {message_id}: {category}\n"
        text += "\n"
        
        text += f"<b>🏢 Оптовый канал ({len(opt_ids)} постов):</b>\n"
        for message_id, category in sorted(opt_posts_info):
            text += f"• Пост {message_id}: {category}\n"
        text += "\n"
        
        text += "💡 <i>Настройки мониторинга работают напрямую с БД</i>"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="settings:monitoring:compare")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:monitoring")],
        ])
        
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        
    except Exception as e:
        log.error(f"Error comparing monitoring: {e}")
        await c.answer(f"❌ Ошибка при анализе: {e}", show_alert=True)
    await c.answer()

# --- Командные настройки (совместимость) ---
@dp.message(Command("get_contacts"))
async def on_get_contacts(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    await m.answer(await get_contacts_text())

@dp.message(Command("set_contacts"))
async def on_set_contacts(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    txt = (m.text or "").split(None, 1)
    if len(txt) < 2:
        await m.answer("Укажите текст: /set_contacts ТЕКСТ")
        return
    await set_setting("contacts", txt[1].strip())
    await m.answer("Контакты обновлены.")

@dp.message(Command("get_template"))
async def on_get_tpl(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        await m.answer("Укажите имя: /get_template order_received|order_approved|order_rejected|cart_checkout_summary")
        return
    name = parts[1].strip()
    tpl = await get_template(name)
    await m.answer(f"<b>{name}</b>\n\n<code>{html.quote(tpl)}</code>", parse_mode="HTML")

@dp.message(Command("set_template"))
async def on_set_tpl(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        await m.answer("Укажите имя: /set_template order_placed_single|order_placed_multiple|admin_order_notification_personal|admin_order_notification_group")
        return
    name = parts[1].strip()
    if name not in DEFAULT_TEMPLATES:
        await m.answer("Неверное имя шаблона.")
        return
    PENDING_TEMPLATE_EDIT[m.from_user.id] = name
    # Определяем плейсхолдеры для каждого шаблона
    placeholders_by_tpl = {
        "order_placed_single": "{product_name}, {quantity}, {price_each}, {total}, {address}, {contacts}",
        "order_placed_multiple": "{cart_items}, {items_count}, {total}, {address}, {contacts}",
        "admin_order_notification_personal": "{order_id}, {user_id}, {username_info}, {product_name}, {quantity}, {price_each}, {total_price}",
        "admin_order_notification_group": "{order_id}, {user_id}, {username_info}, {product_name}, {quantity}, {price_each}, {total_price}"
    }
    
    ph = placeholders_by_tpl.get(name, "{contacts}")
    await m.answer(
        f"Ок. Пришлите <b>следующим сообщением</b> новый текст шаблона <code>{name}</code>.\n\n"
        f"📝 <b>Доступные плейсхолдеры:</b> {ph}\n\n"
        f"🎨 <b>Стилизация текста:</b>\n"
        f"• <b>жирный текст</b> → <code>&lt;b&gt;текст&lt;/b&gt;</code>\n"
        f"• <i>курсив</i> → <code>&lt;i&gt;текст&lt;/i&gt;</code>\n"
        f"• <u>подчеркнутый</u> → <code>&lt;u&gt;текст&lt;/u&gt;</code>\n"
        f"• <s>зачеркнутый</s> → <code>&lt;s&gt;текст&lt;/s&gt;</code>\n"
        f"• <code>моноширинный</code> → <code>&lt;code&gt;текст&lt;/code&gt;</code>",
        parse_mode="HTML"
    )

# Универсальный обработчик перемещен в конец файла
    uid = m.from_user.id if m.from_user else 0
    # Не перехватываем команды — пусть обрабатываются целевыми хендлерами
    if (m.text or "").startswith("/"):
        return
    
    # Проверяем, является ли пользователь админом (БД приоритетна)
    is_admin_user = False
    try:
        is_admin_user = await is_admin(uid, m.from_user.username if m.from_user else None)
    except Exception:
        pass
    
    # Если не найден в БД, проверяем .env (для обратной совместимости)
    if not is_admin_user and MANAGER_USER_IDS and uid in MANAGER_USER_IDS:
        is_admin_user = True
    
    if is_admin_user:
        # Обрабатываем только если админ в режиме редактирования
        if uid in PENDING_CONTACTS_EDIT:
            PENDING_CONTACTS_EDIT.pop(uid, None)
            await set_setting("contacts", m.text)
            await m.answer("✅ <b>Контакты успешно обновлены!</b>\n\n💡 <i>Новые контакты будут использоваться во всех сообщениях бота.</i>", parse_mode="HTML")
            return
        if uid in PENDING_TEMPLATE_EDIT:
            name = PENDING_TEMPLATE_EDIT.pop(uid)
            await set_setting(f"tpl:retail:{name}", m.text)
            await m.answer(f"✅ <b>Шаблон <code>{name}</code> успешно обновлён!</b>\n\n💡 <i>Новый шаблон будет использоваться для соответствующих сообщений.</i>", parse_mode="HTML")
            return
        if uid in PENDING_ADMIN_ADD:
            PENDING_ADMIN_ADD.pop(uid, None)
            username = (m.text or '').strip()
            try:
                ok, msg = await add_admin_by_username(username=username, full_name=None, added_by=uid)
                await m.answer(("✅ " if ok else "⚠️ ") + msg)
            except Exception as e:
                await m.answer(f"❌ Ошибка добавления: {e}")
            return
        if uid in PENDING_ADMIN_REMOVE:
            PENDING_ADMIN_REMOVE.pop(uid, None)
            username = (m.text or '').strip()
            try:
                ok, msg = await remove_admin_by_username(username=username)
                await m.answer(("✅ " if ok else "⚠️ ") + msg)
            except Exception as e:
                await m.answer(f"❌ Ошибка удаления: {e}")
            return
        if uid in PENDING_CATEGORY_EDIT:
            edit_data = PENDING_CATEGORY_EDIT.pop(uid, None)
            if edit_data:
                new_category = (m.text or '').strip()
                try:
                    async with Session() as s:
                        await s.execute(text(
                            """
                            UPDATE monitored_posts
                            SET category = :cat
                            WHERE channel_id = :cid AND message_id = :mid
                            """
                        ), {"cat": new_category, "cid": edit_data["channel_id"], "mid": edit_data["message_id"]})
                        await s.commit()
                    
                    channel_name = "Оптовый" if edit_data["channel_type"] == "opt" else "Розничный"
                    await m.answer(
                        f"✅ Категория поста {edit_data['message_id']} в {channel_name} канале обновлена на: {new_category}\n\n"
                        f"💡 Выполните /fix_categories для обновления товаров"
                    )
                except Exception as e:
                    await m.answer(f"❌ Ошибка обновления категории: {e}")
            return

    # Если не админ или не в режиме редактирования, показываем каталог
    try:
        cats = await fetch_categories()
        if cats:
            max_row_chars = 34 if any(len(t) > 16 for t, _ in cats) else 40
            kb = adaptive_kb(cats, max_per_row=2, max_row_chars=max_row_chars)
            await m.answer("🛍️ <b>Каталог товаров</b>\n\nВыберите категорию:", reply_markup=kb, parse_mode="HTML")
        else:
            await m.answer("❌ Категории не настроены. Обратитесь к администратору.")
    except Exception as e:
        log.error(f"Error showing catalog: {e}")
        pass

@dp.callback_query(F.data == "settings:categories")
async def settings_categories(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    
    # Получаем настройки мониторинга из bot_settings
    store_ids = await get_monitored_message_ids("store")
    opt_ids = await get_monitored_message_ids("opt")
    
    # Получаем текущее состояние категорий из БД - только те посты, которые есть в настройках мониторинга
    async with Session() as s:
        # Розничный канал - только те посты, которые есть в настройках мониторинга
        retail_posts = []
        if store_ids:
            retail_posts = (await s.execute(
                select(MonitoredPost)
                .where(MonitoredPost.channel_id == CHANNEL_ID_STORE)
                .where(MonitoredPost.message_id.in_(store_ids))
                .where(MonitoredPost.is_active == True)
                .order_by(MonitoredPost.message_id)
            )).scalars().all()
        
        # Оптовый канал - только те посты, которые есть в настройках мониторинга
        opt_posts = []
        if opt_ids:
            opt_posts = (await s.execute(
                select(MonitoredPost)
                .where(MonitoredPost.channel_id == CHANNEL_ID_OPT)
                .where(MonitoredPost.message_id.in_(opt_ids))
                .where(MonitoredPost.is_active == True)
                .order_by(MonitoredPost.message_id)
            )).scalars().all()
    
    text = "🏷️ <b>Управление категориями</b>\n\n"
    
    # Показываем текущее состояние
    text += "<b>📊 Текущее состояние:</b>\n\n"
    
    text += f"<b>🏪 Розничный канал ({len(retail_posts)} постов):</b>\n"
    for post in retail_posts:
        category = post.category or "Без категории"
        text += f"• Пост {post.message_id}: {category}\n"
    
    text += f"\n<b>🏢 Оптовый канал ({len(opt_posts)} постов):</b>\n"
    for post in opt_posts:
        category = post.category or "Без категории"
        text += f"• Пост {post.message_id}: {category}\n"
    
    text += "\n<b>🛠️ Доступные команды:</b>\n"
    text += "• <code>/set_post_category &lt;message_id&gt; &lt;категория&gt;</code>\n"
    text += "• <code>/set_category_posts &lt;категория&gt; &lt;id1,id2,id3&gt;</code>\n"
    text += "• <code>/fix_categories</code> - пересинхронизировать\n\n"
    text += "💡 <i>После изменения категорий выполните /fix_categories для обновления товаров</i>"
    
    # Создаем кнопки для редактирования категорий постов
    buttons = []
    
    # Кнопки для оптового канала
    if opt_posts:
        buttons.append([InlineKeyboardButton(text="🏢 Редактировать оптовые посты", callback_data="settings:categories:opt")])
    
    # Кнопки для розничного канала  
    if retail_posts:
        buttons.append([InlineKeyboardButton(text="🏪 Редактировать розничные посты", callback_data="settings:categories:retail")])
    
    buttons.extend([
        [InlineKeyboardButton(text="🔄 Обновить состояние", callback_data="settings:categories")],
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data="settings:back")],
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data.regexp(r"^settings:categories:(opt|retail)$"))
async def settings_categories_edit(c: CallbackQuery):
    """Редактирование категорий для конкретного канала"""
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    
    channel_type = c.data.split(":")[-1]
    channel_id = CHANNEL_ID_OPT if channel_type == "opt" else CHANNEL_ID_STORE
    channel_name = "Оптовый" if channel_type == "opt" else "Розничный"
    
    if not channel_id:
        await c.answer("❌ Канал не настроен", show_alert=True)
        return
    
    # Получаем настройки мониторинга для этого канала
    monitored_ids = await get_monitored_message_ids(channel_type)
    
    if not monitored_ids:
        await c.answer("❌ Нет настроенных постов для мониторинга", show_alert=True)
        return
    
    # Получаем посты для редактирования - только те, которые есть в настройках мониторинга
    async with Session() as s:
        posts = (await s.execute(
            select(MonitoredPost)
            .where(MonitoredPost.channel_id == channel_id)
            .where(MonitoredPost.message_id.in_(monitored_ids))
            .where(MonitoredPost.is_active == True)
            .order_by(MonitoredPost.message_id)
        )).scalars().all()
    
    if not posts:
        await c.answer("❌ Нет активных постов для редактирования", show_alert=True)
        return
    
    text = f"🏷️ <b>Редактирование категорий - {channel_name} канал</b>\n\n"
    text += f"<b>📊 Найдено постов:</b> {len(posts)}\n\n"
    
    # Показываем посты с кнопками для редактирования
    buttons = []
    for post in posts:
        category = post.category or "Без категории"
        # Сокращаем текст кнопки если слишком длинный
        if len(category) > 35:
            category = category[:32] + "..."
        button_text = f"📝 {post.message_id}: {category}"
        callback_data = f"settings:categories:edit:{channel_type}:{post.message_id}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    # Добавляем кнопки управления
    buttons.extend([
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"settings:categories:{channel_type}")],
        [InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="settings:categories")],
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data="settings:back")],
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await c.answer()
            return
        try:
            await c.message.edit_reply_markup(reply_markup=kb)
        except TelegramBadRequest as e2:
            if "message is not modified" in str(e2):
                await c.answer()
                return
            raise
    await c.answer()

@dp.callback_query(F.data.regexp(r"^settings:categories:edit:(opt|retail):(\d+)$"))
async def settings_categories_edit_post(c: CallbackQuery):
    """Редактирование категории конкретного поста"""
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    
    # Добавляем отладочную информацию
    log.info(f"Callback data: {c.data}")
    
    parts = c.data.split(":")
    log.info(f"Split parts: {parts}")
    
    if len(parts) < 5:
        await c.answer("❌ Неверный формат данных", show_alert=True)
        return
    channel_type = parts[3]  # opt или retail
    try:
        message_id = int(parts[4])  # ID поста
        log.info(f"Parsed: channel_type={channel_type}, message_id={message_id}")
    except ValueError as e:
        log.error(f"ValueError parsing message_id: {e}")
        await c.answer("❌ Неверный ID поста", show_alert=True)
        return
    channel_id = CHANNEL_ID_OPT if channel_type == "opt" else CHANNEL_ID_STORE
    channel_name = "Оптовый" if channel_type == "opt" else "Розничный"
    
    # Получаем информацию о посте
    async with Session() as s:
        post = (await s.execute(
            select(MonitoredPost)
            .where(MonitoredPost.channel_id == channel_id)
            .where(MonitoredPost.message_id == message_id)
        )).scalar_one_or_none()
    
    if not post:
        await c.answer("❌ Пост не найден", show_alert=True)
        return
    
    current_category = post.category or "Без категории"
    
    text = f"✏️ <b>Редактирование категории</b>\n\n"
    text += f"<b>📊 Канал:</b> {channel_name}\n"
    text += f"<b>📝 Пост ID:</b> {message_id}\n"
    text += f"<b>🏷️ Текущая категория:</b> {current_category}\n\n"
    text += "💡 <i>Отправьте новую категорию в следующем сообщении</i>"
    
    # Сохраняем состояние редактирования
    PENDING_CATEGORY_EDIT[c.from_user.id] = {
        "channel_type": channel_type,
        "message_id": message_id,
        "channel_id": channel_id
    }
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"settings:categories:{channel_type}")],
    ])
    
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data == "settings:admins")
async def settings_admins(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    
    # Получаем список админов
    admins = await get_all_admins()
    
    text = "👥 <b>Управление админами</b>\n\n"
    text += f"<b>Всего админов:</b> {len(admins)}\n\n"
    
    if admins:
        text += "<b>Список админов:</b>\n"
        for admin in admins:
            username = f"@{admin.username}" if admin.username else "Без username"
            full_name = admin.full_name or "Без имени"
            text += f"• {full_name} ({username}) - ID: {admin.user_id}\n"
    else:
        text += "Админы не найдены"
    
    text += "\n<b>Доступные команды:</b>\n"
    text += "• /add_admin @username - добавить админа\n"
    text += "• /remove_admin @username - удалить админа\n"
    text += "• /list_admins - показать список админов"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="settings:admins:add"), InlineKeyboardButton(text="➖ Удалить", callback_data="settings:admins:remove")],
        [InlineKeyboardButton(text="🔄 Обновить список", callback_data="settings:admins")],
        [InlineKeyboardButton(text=BTN_SETTINGS_BACK, callback_data="settings:back")],
    ])
    
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await c.message.edit_reply_markup(reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data == "settings:admins:add")
async def settings_admins_add(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    PENDING_ADMIN_ADD[c.from_user.id] = True
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="settings:cancel_admin_add")]
    ])
    try:
        await c.message.reply("✏️ Пришлите username вида @username для добавления в админы", reply_markup=kb)
    except Exception:
        pass
    await c.answer()

@dp.callback_query(F.data == "settings:admins:remove")
async def settings_admins_remove(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    PENDING_ADMIN_REMOVE[c.from_user.id] = True
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="settings:cancel_admin_remove")]
    ])
    try:
        await c.message.reply("✏️ Пришлите username вида @username для удаления из админов", reply_markup=kb)
    except Exception:
        pass
    await c.answer()

# Команды для настройки мониторинга
@dp.message(Command("set_monitored_store"))
async def on_set_monitored_store(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        await m.answer("Укажите ID постов: /set_monitored_store 1,2,3,4,5")
        return
    try:
        ids = {int(x.strip()) for x in parts[1].split(",") if x.strip().isdigit()}
        await set_monitored_message_ids("store", ids)
        await m.answer(f"✅ Мониторимые посты розничного канала обновлены: {sorted(ids)}")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")

# Обработчик remove_monitored_store перемещен в начало файла

@dp.message(Command("set_monitored_opt"))
async def on_set_monitored_opt(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        await m.answer("Укажите ID постов: /set_monitored_opt 1,2,3,4,5")
        return
    try:
        ids = {int(x.strip()) for x in parts[1].split(",") if x.strip().isdigit()}
        await set_monitored_message_ids("opt", ids)
        await m.answer(f"✅ Мониторимые посты оптового канала обновлены: {sorted(ids)}")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("add_monitored_opt"))
async def on_add_monitored_opt(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        await m.answer("Формат: /add_monitored_opt 28,29")
        return
    try:
        inc = {int(x.strip()) for x in parts[1].split(",") if x.strip().isdigit()}
        cur = await get_monitored_message_ids("opt")
        updated = set(cur) | set(inc)
        await set_monitored_message_ids("opt", updated)
        await m.answer(f"✅ Добавлены: {sorted(inc)}\nТекущие: {sorted(updated)}")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("remove_monitored_opt"))
async def on_remove_monitored_opt(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        await m.answer("Формат: /remove_monitored_opt 28,29")
        return
    try:
        dec = {int(x.strip()) for x in parts[1].split(",") if x.strip().isdigit()}
        cur = await get_monitored_message_ids("opt")
        updated = set(cur) - set(dec)
        await set_monitored_message_ids("opt", updated)
        await m.answer(f"✅ Удалены: {sorted(dec)}\nТекущие: {sorted(updated)}")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("set_master_store"))
async def on_set_master_store(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        await m.answer("Укажите ID: /set_master_store 123")
        return
    try:
        master_id = int(parts[1].strip())
        await set_master_message_id("store", master_id)
        await m.answer(f"✅ Главное сообщение розничного канала обновлено: {master_id}")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("set_master_opt"))
async def on_set_master_opt(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        await m.answer("Укажите ID: /set_master_opt 123")
        return
    try:
        master_id = int(parts[1].strip())
        await set_master_message_id("opt", master_id)
        await m.answer(f"✅ Главное сообщение оптового канала обновлено: {master_id}")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("set_contacts"))
async def on_set_contacts(m: Message):
    """Установить контакты"""
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    
    new_contacts = (m.text or "").replace("/set_contacts", "").strip()
    if not new_contacts:
        await m.answer("❌ Укажите текст контактов")
        return
    
    try:
        await set_setting("contacts", new_contacts, "Контактная информация", "general")
        await m.answer("✅ Контакты обновлены")
    except Exception as e:
        log.error(f"Error setting contacts: {e}")
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("set_template"))
async def on_set_template(m: Message):
    """Установить шаблон"""
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    
    parts = (m.text or "").split(None, 2)
    if len(parts) < 3:
        await m.answer("Формат: /set_template order_placed_single|order_placed_multiple|admin_order_notification_personal|admin_order_notification_group <новый шаблон>")
        return
    
    template_name = parts[1]
    new_template = parts[2]
    
    try:
        await set_setting(f"tpl:retail:{template_name}", new_template, f"Шаблон {template_name}", "templates")
        await m.answer(f"✅ Шаблон {template_name} обновлен")
    except Exception as e:
        log.error(f"Error setting template: {e}")
        await m.answer(f"❌ Ошибка: {e}")

# Команды для управления админами
@dp.message(Command("add_admin"))
async def on_add_admin(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        await m.answer("Укажите username пользователя: /add_admin @username")
        return
    try:
        username = parts[1].strip()
        success, message = await add_admin_by_username(
            username=username,
            full_name=None,
            added_by=m.from_user.id
        )
        await m.answer(f"✅ {message}")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("remove_admin"))
async def on_remove_admin(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        await m.answer("Укажите username пользователя: /remove_admin @username")
        return
    try:
        username = parts[1].strip()
        success, message = await remove_admin_by_username(username)
        await m.answer(f"✅ {message}")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("list_admins"))
async def on_list_admins(m: Message):
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    try:
        admins = await get_all_admins()
        if not admins:
            await m.answer("👥 Админы не найдены")
            return
        
        text = "👥 <b>Список админов:</b>\n\n"
        for admin in admins:
            username = f"@{admin.username}" if admin.username else "Без username"
            full_name = admin.full_name or "Без имени"
            text += f"• {full_name} ({username})\n"
            text += f"  ID: <code>{admin.user_id}</code>\n"
            text += f"  Добавлен: {admin.added_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        await m.answer(text, parse_mode="HTML")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")

@dp.message(Command("test_button_length"))
async def on_test_button_length(m: Message):
    """Тестовая команда для проверки адаптивной длины кнопок"""
    if not m.from_user or not await _is_manager(m.from_user.id, m.from_user.username, 'retail'):
        await m.answer("⛔ Недостаточно прав.")
        return
    
    # Тестируем разные лимиты
    mobile_limit = get_adaptive_button_length(m.from_user.id)
    
    # Создаем тестовые кнопки с разной длиной
    test_buttons = []
    
    # Короткая кнопка
    test_buttons.append(("📱 Короткая кнопка · 1 000 ₽", "test:short"))
    
    # Средняя кнопка
    test_buttons.append(("💻 Средняя кнопка с названием · 5 000 ₽", "test:medium"))
    
    # Длинная кнопка (должна обрезаться)
    long_text = "🖥️ Очень длинная кнопка с очень длинным названием товара · 10 000 ₽"
    if len(long_text) > mobile_limit:
        cut = mobile_limit - 3
        while cut > 10 and long_text[cut-1] != ' ':
            cut -= 1
        long_text = long_text[:cut].rstrip() + "..."
    test_buttons.append((long_text, "test:long"))
    
    kb = adaptive_kb(test_buttons, max_per_row=1, max_row_chars=50)
    
    text = (
        f"🧪 <b>Тест адаптивной длины кнопок</b>\n\n"
        f"📏 <b>Текущий лимит:</b> {mobile_limit} символов\n"
        f"📱 <b>Устройство:</b> определяется автоматически\n\n"
        f"Проверьте, как отображаются кнопки разной длины:"
    )
    
    await m.answer(text, parse_mode="HTML", reply_markup=kb)


# =============================================================================
# УВЕДОМЛЕНИЯ МЕНЕДЖЕРАМ (упрощенная версия без кнопок одобрения)
# =============================================================================

async def _notify_managers_new_order(order, prod_name: str, price_each: int):
    """Уведомить менеджеров о новом заказе (упрощенная версия без кнопок)"""
    try:
        # Получаем шаблоны уведомлений (отдельно для личных и групповых сообщений)
        template_personal = await get_template("admin_order_notification_personal")
        template_group = await get_template("admin_order_notification_group")
        
        # Получаем информацию о пользователе
        user_info = f"@{order.username}" if order.username else f"ID: {order.user_id}"
        
        # Получаем флаг товара из БД и формируем полное название
        flag = ""
        is_used_flag = False
        try:
            async with Session() as s:
                prod = (await s.execute(select(Product).where(Product.id == order.product_id))).scalar_one_or_none()
                if prod:
                    is_used_flag = bool(prod.is_used)
                    ea = dict(prod.extra_attrs or {})
                    flag = (ea.get("flag") or "").strip()
        except Exception:
            flag = ""
        
        # Формируем полное название товара с флагом (как в оптовом боте)
        prod_label = f"{prod_name}{flag}{' (Б/У)' if is_used_flag else ''}"
        
        # Отправляем уведомление в группу менеджеров
        if MANAGER_GROUP_ID:
            text_group = render_template(template_group,
                order_id=order.id,
                user_id=order.user_id,
                username_info=(' @'+order.username) if order.username else '',
                product_name=prod_label,
                quantity=order.quantity,
                price_each=fmt_price(price_each),
                total_price=fmt_price(order.quantity * price_each)
            )
            await bot.send_message(
                MANAGER_GROUP_ID,
                text_group,
                parse_mode="HTML"
            )
            log.info(f"Retail order notification sent to managers group: {order.id}")
        
        # Отправляем уведомление отдельным менеджерам
        for manager_id in MANAGER_USER_IDS:
            try:
                text_personal = render_template(template_personal,
                    order_id=order.id,
                    user_id=order.user_id,
                    username_info=(' @'+order.username) if order.username else '',
                    product_name=prod_label,
                    quantity=order.quantity,
                    price_each=fmt_price(price_each),
                    total_price=fmt_price(order.quantity * price_each)
                )
                await bot.send_message(
                    manager_id,
                    text_personal,
                    parse_mode="HTML"
                )
            except Exception as e:
                log.warning(f"Failed to notify manager {manager_id}: {e}")
        
    except Exception as e:
        log.error(f"Error notifying managers about order {order.id}: {e}")

async def _is_manager(user_id: int, username: str = None, channel_type: str = 'retail') -> bool:
    """Проверить, является ли пользователь менеджером (БД приоритетна)"""
    try:
        # Проверяем БД (основной способ)
        is_admin_in_db = await is_admin(user_id, username, channel_type)
        if is_admin_in_db:
            return True
        
        # Если не найден в БД, проверяем .env (для обратной совместимости)
        if MANAGER_USER_IDS and user_id in MANAGER_USER_IDS:
            return True
        
        return False
    except Exception as e:
        log.error(f"Error checking manager status for user {user_id}: {e}")
        return False

# Функция _notify_buyer_decision удалена - не нужна для розничного бота

# Обработчики модерации заказов удалены - не нужны для розничного бота

# --- OCR настройка ---
ENABLE_OCR = (os.getenv("ENABLE_OCR", "false").lower() == "true")
TESSERACT_CMD = os.getenv("TESSERACT_CMD")

try:
    if ENABLE_OCR and not TESSERACT_CMD:
        import shutil
        TESSERACT_CMD = shutil.which("tesseract") or ""

    if ENABLE_OCR and TESSERACT_CMD:
        try:
            import pytesseract  # type: ignore
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
            OCR_READY = True
        except Exception:
            OCR_READY = False
    else:
        OCR_READY = False
except Exception:
    OCR_READY = False

def _extract_serial_text(img_path: str) -> str | None:
    if not OCR_READY:
        return None
    try:
        import pytesseract  # type: ignore
        raw = (pytesseract.image_to_string(img_path, lang="eng") or "").strip()
        if not raw:
            return None
        m = re.findall(r"[A-Z0-9\-]{8,}", raw.replace(" ", "").upper())
        if m:
            return m[0]
        return raw.splitlines()[0] if raw else None
    except Exception:
        return None

# Приём фото серийника в ответ на сообщение бота (в чате менеджеров)
# Обработчик фото серийника удален - не нужен для розничного бота

# Заглушка колбэка "noop" (ничего не делает)
@dp.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await c.answer()

# Обработчик текстовых сообщений для редактирования настроек
@dp.message(F.text, F.chat.type.in_({"private"}))
async def on_possible_settings_text(m: Message):
    uid = m.from_user.id if m.from_user else 0
    # Не перехватываем команды — пусть обрабатываются целевыми хендлерами
    if (m.text or "").startswith("/"):
        return
    
    # Не перехватываем кнопки меню - пусть обрабатываются соответствующими хендлерами
    button_texts = [
        BTN_CATALOG, BTN_CONTACTS, BTN_CART, BTN_RESCAN, BTN_DIAG, BTN_SETTINGS,
        BTN_RESCAN_ADMIN, BTN_DIAG_ADMIN, BTN_SETTINGS_ADMIN,
        "⬅️ Назад в меню"
    ]
    if m.text in button_texts:
        return
    
    # Проверяем, является ли пользователь админом (БД приоритетна)
    is_admin_user = False
    try:
        is_admin_user = await is_admin(uid, m.from_user.username if m.from_user else None)
    except Exception:
        pass
    
    # Если не найден в БД, проверяем .env (для обратной совместимости)
    if not is_admin_user and MANAGER_USER_IDS and uid in MANAGER_USER_IDS:
        is_admin_user = True
    
    # Если пользователь НЕ админ, не обрабатываем сообщение
    if not is_admin_user:
        return
    
    # Если админ НЕ находится в режиме редактирования, не обрабатываем сообщение
    if not (uid in PENDING_CONTACTS_EDIT or uid in PENDING_TEMPLATE_EDIT or 
            uid in PENDING_ADMIN_ADD or uid in PENDING_ADMIN_REMOVE or 
            uid in PENDING_CATEGORY_EDIT):
        return
    
    if is_admin_user:
        # Обрабатываем только если админ в режиме редактирования
        if uid in PENDING_CONTACTS_EDIT:
            PENDING_CONTACTS_EDIT.pop(uid, None)
            await set_setting("contacts", m.text)
            await m.answer("✅ <b>Контакты успешно обновлены!</b>\n\n💡 <i>Новые контакты будут использоваться во всех сообщениях бота.</i>", parse_mode="HTML")
            return
        if uid in PENDING_TEMPLATE_EDIT:
            name = PENDING_TEMPLATE_EDIT.pop(uid)
            await set_setting(f"tpl:retail:{name}", m.text)
            await m.answer(f"✅ <b>Шаблон <code>{name}</code> успешно обновлён!</b>\n\n💡 <i>Новый шаблон будет использоваться для соответствующих сообщений.</i>", parse_mode="HTML")
            return
        if uid in PENDING_ADMIN_ADD:
            PENDING_ADMIN_ADD.pop(uid, None)
            username = (m.text or '').strip()
            try:
                ok, msg = await add_admin_by_username(username=username, full_name=None, added_by=uid)
                await m.answer(("✅ " if ok else "⚠️ ") + msg)
            except Exception as e:
                await m.answer(f"❌ Ошибка добавления: {e}")
            return
        if uid in PENDING_ADMIN_REMOVE:
            PENDING_ADMIN_REMOVE.pop(uid, None)
            username = (m.text or '').strip()
            try:
                ok, msg = await remove_admin_by_username(username=username)
                await m.answer(("✅ " if ok else "⚠️ ") + msg)
            except Exception as e:
                await m.answer(f"❌ Ошибка удаления: {e}")
            return
        if uid in PENDING_CATEGORY_EDIT:
            edit_data = PENDING_CATEGORY_EDIT.pop(uid, None)
            if edit_data:
                new_category = (m.text or '').strip()
                try:
                    async with Session() as s:
                        await s.execute(text(
                            """
                            UPDATE monitored_posts
                            SET category = :cat
                            WHERE channel_id = :cid AND message_id = :mid
                            """
                        ), {"cat": new_category, "cid": edit_data["channel_id"], "mid": edit_data["message_id"]})
                        await s.commit()
                    
                    await m.answer(f"✅ <b>Категория успешно обновлена!</b>\n\n🏷️ <b>Новая категория:</b> {new_category}", parse_mode="HTML")
                except Exception as e:
                    await m.answer(f"❌ Ошибка обновления категории: {e}")
            return

# Глобальный обработчик ошибок
@dp.error()
async def error_handler(event, exception):
    """Обработка ошибок"""
    if isinstance(exception, TelegramMigrateToChat):
        log.warning(f"Chat migrated to supergroup: {exception.migrate_to_chat_id}")
        return True  # Игнорируем ошибку
    elif isinstance(exception, TelegramBadRequest):
        if "message is not modified" in str(exception):
            log.warning("Message not modified, ignoring")
            return True
        elif "group chat was upgraded" in str(exception):
            log.warning("Group upgraded to supergroup, ignoring")
            return True
    elif "can't subtract offset-naive and offset-aware datetimes" in str(exception):
        log.warning("Timezone error, ignoring")
        return True
    else:
        log.error(f"Unhandled error: {exception}")
    return False

# Обработчик неизвестных сообщений
@dp.message()
async def handle_unknown_message(m: Message):
    """Обработка неизвестных сообщений"""
    log.info(f"Unknown message from user {m.from_user.id if m.from_user else 'unknown'}: {m.text}")
    
    # Проверяем, что это личное сообщение (не группа)
    if m.chat.type != "private":
        log.info(f"Ignoring message from {m.chat.type} chat {m.chat.id}")
        return
    
    # Если это команда /start, но не обработалась выше
    if m.text and m.text.startswith('/start'):
        log.info("Start command not handled by main handler, using fallback")
        await on_menu(m)
        return
    
    # Если это команда /help, но не обработалась выше
    if m.text and m.text.startswith('/help'):
        await m.answer(
            "📋 <b>Доступные команды:</b>\n\n"
            "🏠 /start - Главное меню\n"
            "📱 Каталог товаров - Просмотр товаров\n"
            "📍 Наши контакты - Контактная информация\n"
            "🧺 Корзина - Управление корзиной\n"
            "⚙️ Настройки - Административные настройки",
            parse_mode="HTML",
            reply_markup=await main_menu_kb(m.from_user.id if m.from_user else 0, m.chat.type)
        )
        return
    
    await m.answer(
        "🤔 Не понимаю эту команду.\n\n"
        "Используйте /start для начала работы или /help для справки.",
        reply_markup=await main_menu_kb(m.from_user.id if m.from_user else 0)
    )

# Обработчики кнопок отмены для режимов редактирования
@dp.callback_query(F.data == "settings:cancel_contacts")
async def cancel_contacts_edit(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    PENDING_CONTACTS_EDIT.pop(c.from_user.id, None)
    await c.message.edit_text("❌ Редактирование контактов отменено")
    await c.answer()

@dp.callback_query(F.data == "settings:cancel_admin_add")
async def cancel_admin_add(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    PENDING_ADMIN_ADD.pop(c.from_user.id, None)
    await c.message.edit_text("❌ Добавление админа отменено")
    await c.answer()

@dp.callback_query(F.data == "settings:cancel_admin_remove")
async def cancel_admin_remove(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    PENDING_ADMIN_REMOVE.pop(c.from_user.id, None)
    await c.message.edit_text("❌ Удаление админа отменено")
    await c.answer()

@dp.callback_query(F.data == "settings:cancel_template")
async def cancel_template_edit(c: CallbackQuery):
    if not c.from_user or not await _is_manager(c.from_user.id, c.from_user.username, 'retail'):
        await c.answer("⛔ Недостаточно прав.", show_alert=True)
        return
    PENDING_TEMPLATE_EDIT.pop(c.from_user.id, None)
    await c.message.edit_text("❌ Редактирование шаблона отменено")
    await c.answer()

# -----------------------------------------------------------------------------
# Точка входа для запуска бота
# -----------------------------------------------------------------------------
async def main():
    """Основная функция запуска бота"""
    log.info("🚀 Запуск розничного бота...")
    try:
        # Проверяем подключение
        log.info("🔍 Проверяем подключение к Telegram API...")
        me = await bot.get_me()
        log.info(f"✅ Бот подключен: @{me.username}")
        
        # Проверяем, что обработчики зарегистрированы
        log.info("📝 Обработчики зарегистрированы")
        
        # Запускаем polling
        log.info("🔄 Запускаем polling...")
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "channel_post", "edited_channel_post", "my_chat_member"]
        )
    except Exception as e:
        log.error(f"❌ Ошибка при запуске бота: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Закрываем сессию корректно
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
