# Совместимость со старым импортом: from app_store.repo import ...
# Реэкспортируем из нового расположения.
try:
    from .db.repo import (
        Product,
        ChannelMessage,           # если модель в .db.repo
        create_order,
        # добавь при необходимости:
        update_order_status, 
        get_pending_orders,
    )
except ImportError:
    # На случай, если ChannelMessage объявлен в другом модуле (напр., .db.core)
    from .db.repo import Product, create_order  # обязательное
    try:
        from .db.repo import ChannelMessage
    except Exception:
        try:
            from .db.core import ChannelMessage
        except Exception:
            ChannelMessage = None  # если нигде нет — пусть упадёт там, где реально нужен
    # try/except для дополнительных функций
    try:
        from .db.repo import update_order_status, get_pending_orders
    except Exception:
        pass
