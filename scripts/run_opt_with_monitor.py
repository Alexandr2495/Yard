# -*- coding: utf-8 -*-
import os, re, asyncio, logging, json, json, sys
from datetime import datetime, timezone, UTC
from typing import List, Tuple

# Добавляем родительскую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from aiogram.enums import ChatType
from aiogram.types import Message

from sqlalchemy import select, update, and_, not_

# берём готовый оптовый бот (dp, bot) и его маршруты
from bot_wholesale import dp as dp_opt, bot as bot_opt, get_monitored_message_ids, get_master_message_id

from app_store.db.core import Session, MonitoredPost
from app_store.db.core import Product, ChannelMessage

log = logging.getLogger("opt+monitor")
logging.basicConfig(level=logging.INFO)
load_dotenv()

# ------------- helpers / env -------------
def _csv_to_ids(val):
    if not val:
        return set()
    out = set()
    for part in re.split(r"[,\s]+", val.strip()):
        if not part:
            continue
        try:
            out.add(int(part))
        except Exception:
            pass
    return out

CHANNEL_ID_STORE = int(os.getenv("CHANNEL_ID_STORE", "0") or "0")
CHANNEL_ID_OPT   = int(os.getenv("CHANNEL_ID_OPT",   "0") or "0")

# Списки постов Б/У (пока оставляем из .env)
USED_STORE = _csv_to_ids(os.getenv("USED_MESSAGE_IDS_STORE", ""))
USED_OPT   = _csv_to_ids(os.getenv("USED_MESSAGE_IDS_OPT",   ""))

WATCH = {}

# --- category mapping from JSON buttons (both store & wholesale) ---
def _walk_buttons_to_map(obj, stack, acc):
    if isinstance(obj, dict):
        text = (obj.get("text") or obj.get("title") or "").strip()
        link = obj.get("link") or obj.get("url") or ""
        if text:
            stack.append(text)
        m = re.search(r'/c/-?\d+/(\d+)$', link) or re.search(r'/(\d+)$', link)
        if m:
            mid = int(m.group(1))
            # category path: "Parent / Child / Leaf"
            cat = " / ".join([s for s in stack if s])
            acc[mid] = cat
        for v in obj.values():
            _walk_buttons_to_map(v, stack, acc)
        if text:
            stack.pop()
    elif isinstance(obj, list):
        for v in obj:
            _walk_buttons_to_map(v, stack, acc)

def _build_msgid_to_category(json_path):
    acc = {}
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _walk_buttons_to_map(data, [], acc)
    except Exception:
        pass
    return acc

CATMAP_STORE = _build_msgid_to_category("menu_buttons.json")               # retail
CATMAP_OPT   = _build_msgid_to_category("wholesale_menu_buttons.json")     # wholesale

def _category_for(channel_id, message_id):
    # Fallback to JSON maps if DB lookup fails; DB is source of truth
    if channel_id == CHANNEL_ID_STORE:
        return CATMAP_STORE.get(message_id)
    if channel_id == CHANNEL_ID_OPT:
        return CATMAP_OPT.get(message_id)
    return None
# Инициализация WATCH будет в main() после загрузки настроек из БД

# ------------- parsing -------------
PRICE_RE = re.compile(r"^\s*(?P<name>.+?)\s*[-:]\s*(?P<price>[\d\s]{2,})(?P<rest>.*)$")

def _extract_flag(text):
    """Попробовать извлечь флаг (emoji-флаг страны) из строки."""
    try:
        flag_match = re.search(r"[\U0001F1E6-\U0001F1FF]{2}", text)
        return flag_match.group(0) if flag_match else ""
    except Exception:
        return ""

def parse_lines(text):
    items = []
    for raw in (text or "").splitlines():
        m = PRICE_RE.match(raw)
        if not m:
            continue
        name = m.group("name").strip()
        digits = re.sub(r"\D", "", m.group("price") or "")
        rest = m.group("rest") or ""
        
        if not digits:
            continue
        try:
            price = int(digits)
        except Exception:
            continue
        if price <= 0:
            continue
        # защита от лишних нулей
        if price > 2000000:
            if price % 1000 == 0 and (price // 1000) <= 500000:
                price //= 1000
            elif price % 100 == 0 and (price // 100) <= 500000:
                price //= 100
        if price > 5000000:
            log.warning("Skip unrealistic price %s for line: %r", price, raw)
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

def parse_used_attrs(name):
    s = (name or "").lower()
    attrs = {}
    m = re.search(r"(\d+)\s*(?:год|года|лет|месяц|месяца|недел)", s)
    if m:
        attrs["usage_hint"] = m.group(0)
    if "полный комплект" in s:
        attrs["kit"] = "full"
    if "без короб" in s:
        attrs["kit"] = "no_box"
    return attrs

def norm_key(name, flag=""):
    s = (name or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    # Добавляем флаг в ключ для уникальности
    if flag:
        s = f"{s}|{flag}"
    return s

# ------------- upsert -------------
async def upsert_for_message(channel_id, message_id, title, text):
    now = datetime.now(UTC)
    price_field = "price_retail" if channel_id == CHANNEL_ID_STORE else ("price_wholesale" if channel_id == CHANNEL_ID_OPT else None)
    if price_field is None:
        return

    # Б/У определяется списками USED_* из .env для каждого канала
    is_used = (message_id in (USED_STORE if channel_id == CHANNEL_ID_STORE else USED_OPT))

    # Получаем категорию из БД monitored_posts; если нет — пробуем из JSON карт
    db_category = None
    try:
        async with Session() as s:
            mp = (await s.execute(
                select(MonitoredPost).where(
                    and_(
                        MonitoredPost.channel_id == channel_id,
                        MonitoredPost.message_id == message_id
                    )
                )
            )).scalar_one_or_none()
            if mp:
                db_category = mp.category
    except Exception:
        db_category = None

    category = db_category if db_category is not None else _category_for(channel_id, message_id)

    rows = parse_lines(text)
    keys_in_post = set()

    async with Session() as s:
        # upsert ChannelMessage
        cm = (await s.execute(
            select(ChannelMessage).where(
                and_(
                    ChannelMessage.channel_id == channel_id,
                    ChannelMessage.message_id == message_id
                )
            )
        )).scalar_one_or_none()
        if not cm:
            cm = ChannelMessage(
                channel_id=channel_id,
                message_id=message_id,
                title=title or "",
                text_len=len(text or ""),
                edited_at=now
            )
            s.add(cm)
        else:
            cm.title = title or ""
            cm.text_len = len(text or "")
            cm.edited_at = now

        # upsert products
        for name, price, flag in rows:
            key = norm_key(name, flag)
            keys_in_post.add(key)

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

            if not prod:
                prod = Product(
                    channel_id=channel_id,
                    group_message_id=message_id,
                    name=name[:400],
                    key=key,
                    category=category,
                    requires_serial=False,
                    available=True,
                    is_used=is_used,
                    extra_attrs=(
                        {
                            **(parse_used_attrs(name) if is_used else {}),
                            **({"flag": flag} if flag else {})
                        } or None
                    ),
                    updated_at=now
                )
                setattr(prod, price_field, price)
                s.add(prod)
            else:
                setattr(prod, price_field, price)
                prod.name = name[:400]
                prod.available = True
                if category:
                    prod.category = category
                prod.is_used = is_used
                # Обновляем/дополняем extra_attrs
                try:
                    cur = dict(prod.extra_attrs or {})
                except Exception:
                    cur = {}
                if is_used:
                    cur.update(parse_used_attrs(name))
                if flag:
                    cur["flag"] = flag
                prod.extra_attrs = cur or None
                prod.updated_at = now

        # кого нет в посте — снимаем с наличия и чистим цену этого типа и этого is_used
        if keys_in_post:
            await s.execute(
                update(Product)
                .where(
                    and_(
                        Product.channel_id == channel_id,
                        Product.group_message_id == message_id,
                        Product.is_used == is_used,
                        not_(Product.key.in_(keys_in_post))
                    )
                )
                .values(
                    available=False,
                    **{price_field: None},
                    updated_at=now
                )
            )

        await s.commit()

# ------------- handlers -------------
@dp_opt.channel_post()
async def _on_channel_post(msg: Message):
    if msg.chat.type != ChatType.CHANNEL:
        return
    if msg.chat.id not in WATCH:
        return
    if msg.message_id not in WATCH[msg.chat.id]:
        return
    text = (msg.text or msg.caption or "").strip()
    log.info("NEW  [%s] mid=%s bytes=%s", msg.chat.title, msg.message_id, len(text))
    await upsert_for_message(msg.chat.id, msg.message_id, msg.chat.title or "", text)

@dp_opt.edited_channel_post()
async def _on_edited_channel_post(msg: Message):
    if msg.chat.type != ChatType.CHANNEL:
        return
    if msg.chat.id not in WATCH:
        return
    if msg.message_id not in WATCH[msg.chat.id]:
        return
    text = (msg.text or msg.caption or "").strip()
    log.info("EDIT [%s] mid=%s bytes=%s", msg.chat.title, msg.message_id, len(text))
    await upsert_for_message(msg.chat.id, msg.message_id, msg.chat.title or "", text)

# ------------- entrypoint -------------
async def main():
    # Загружаем настройки мониторинга из БД
    global WATCH
    
    MON_STORE = await get_monitored_message_ids("store")
    MON_OPT = await get_monitored_message_ids("opt")
    
    if CHANNEL_ID_STORE and MON_STORE: 
        WATCH[CHANNEL_ID_STORE] = MON_STORE
    if CHANNEL_ID_OPT and MON_OPT:     
        WATCH[CHANNEL_ID_OPT] = MON_OPT
    
    if not WATCH:
        log.error("❌ Нет настроенных каналов для мониторинга. Проверьте настройки в БД.")
        return
    
    log.info("📡 Мониторинг каналов: %s", WATCH)
    
    # bot_opt уже создан в bot_wholesale.py с TG_TOKEN_OPT
    await dp_opt.start_polling(
        bot_opt,
        allowed_updates=["message","callback_query","channel_post","edited_channel_post","my_chat_member"]
    )

if __name__ == "__main__":
    asyncio.run(main())
