# Yard Bot - Telegram Bot для торговли

Telegram бот для продажи товаров с поддержкой retail и wholesale каналов.

## Структура проекта

```
Yard_bot/
├── bot_retail2.py          # Retail бот
├── bot_wholesale.py         # Wholesale бот
├── app_store/               # Основной модуль
│   ├── db/                  # Модели и репозиторий БД
│   ├── parsing/             # Парсер цен
│   ├── privacy/             # Система конфиденциальности
│   └── utils/                # Утилиты
├── scripts/                 # Скрипты мониторинга
│   └── run_opt_with_monitor.py
├── requirements.txt         # Зависимости Python
├── .env                     # Переменные окружения
├── deploy_to_server.sh     # Скрипт деплоя
└── DEPLOYMENT_FILES.md      # Описание файлов для деплоя
```

## Установка и запуск

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Настройте `.env` файл с токенами и настройками БД

3. Запустите ботов:
```bash
# Retail бот
python bot_retail2.py

# Wholesale бот  
python bot_wholesale.py

# Мониторинг оптового канала
python scripts/run_opt_with_monitor.py
```

## Деплой на сервер

Используйте скрипт для автоматического деплоя:
```bash
./deploy_to_server.sh [IP_СЕРВЕРА]
```

## Основные функции

- **Retail бот**: Продажа товаров в розницу
- **Wholesale бот**: Продажа товаров оптом с фильтрацией
- **Мониторинг каналов**: Автоматическое обновление товаров
- **Система корзин**: Добавление товаров в корзину
- **Система заказов**: Оформление и обработка заказов
- **Конфиденциальность**: GDPR-совместимая система согласий

## Технологии

- Python 3.8+
- aiogram 3.x
- SQLAlchemy 2.x
- PostgreSQL
- asyncio
