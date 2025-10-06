import re
import logging
from typing import Iterable, Tuple

logger = logging.getLogger(__name__)

PRICE_LINE = re.compile(
    r"""
    ^\s*
    (?P<name>.+?)              # всё до разделителя — имя
    \s+[-—:]\s+               # разделитель: дефис/тире/двоеточие ОБЯЗАТЕЛЬНО с пробелами
    (?P<price>[\d\s\.,]+)    # цена: цифры, пробелы, точки, запятые
    (?:\s*[₽рR]\.?)?          # необязательная валюта: ₽/р/R, с точкой или без
    (?:\D.*)?                  # дальше могут быть эмодзи/флаги/комментарии
    $
    """,
    re.VERBOSE | re.IGNORECASE | re.UNICODE
)

# Дополнительный паттерн для случаев без пробела перед дефисом
PRICE_LINE_NO_SPACE = re.compile(
    r"""
    ^\s*
    (?P<name>.+?)              # всё до дефиса — имя
    [-—:](?P<price>[\d\s\.,]+)    # дефис/тире/двоеточие сразу за именем, затем цена
    (?:\s*[₽рR]\.?)?          # необязательная валюта: ₽/р/R, с точкой или без
    (?:\D.*)?                  # дальше могут быть эмодзи/флаги/комментарии
    $
    """,
    re.VERBOSE | re.IGNORECASE | re.UNICODE
)

def parse_price_post(text: str) -> Iterable[Tuple[str, int]]:
    """
    Возвращает (name, price) по строкам вида: "iPhone 15 128 black - 49900"
    Игнорирует заголовки, пустые строки и блоки без цены.
    """
    results = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        
        # Пробуем основной паттерн (с пробелами)
        m = PRICE_LINE.match(line)
        if not m:
            # Пробуем дополнительный паттерн (без пробела перед дефисом)
            m = PRICE_LINE_NO_SPACE.match(line)
        
        if not m:
            continue
            
        name = m.group("name").strip("•.-–—: ")
        price_raw = m.group("price")
        # вытащим только цифры (удаляем пробелы/разделители тысяч)
        digits = "".join(ch for ch in price_raw if ch.isdigit())
        if not digits:
            continue
        try:
            price = int(digits)
            # Проверяем разумность цены (максимум 1 миллион рублей)
            if price > 1_000_000:
                logger.warning(f"⚠️ Слишком большая цена для товара '{name}': {price:,} руб. Пропускаем.")
                continue
        except ValueError:
            continue
        # Отсеем слишком короткие "имена", это обычно шум
        if len(name) < 2:
            continue
        results.append((name, price))
    return results
