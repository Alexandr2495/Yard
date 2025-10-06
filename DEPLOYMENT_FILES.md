# Файлы для деплоя на сервер

## Основные файлы (обязательно нужны):

### Основные боты:
- `bot_retail2.py` - основной retail бот
- `bot_wholesale.py` - основной wholesale бот

### Модуль app_store (полностью):
- `app_store/__init__.py`
- `app_store/db/__init__.py`
- `app_store/db/core.py` - модели БД
- `app_store/db/repo.py` - репозиторий для работы с БД
- `app_store/parsing/__init__.py`
- `app_store/parsing/price_parser.py` - парсер цен
- `app_store/privacy/__init__.py`
- `app_store/privacy/consent_manager.py` - менеджер согласий
- `app_store/privacy/handlers.py` - обработчики конфиденциальности
- `app_store/utils/__init__.py`
- `app_store/utils/sampling.py` - утилиты

### Скрипты мониторинга:
- `scripts/run_opt_with_monitor.py` - мониторинг оптового канала

### Конфигурация:
- `.env` - переменные окружения (создать на сервере)
- `requirements.txt` - зависимости Python

## Дополнительные файлы (могут понадобиться):
- `__pycache__/` - кэш Python (создается автоматически)

## Файлы в папке "Потенциально мусор":
Все остальные файлы перемещены в папку "Потенциально мусор" и не нужны для работы основных ботов.

## Команды для деплоя:

1. Скопировать основные файлы на сервер
2. Установить зависимости: `pip install -r requirements.txt`
3. Настроить .env файл с токенами и настройками БД
4. Запустить ботов

## Структура на сервере должна быть:
```
/root/Yard_bot/
├── bot_retail2.py
├── bot_wholesale.py
├── app_store/
│   ├── __init__.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── core.py
│   │   └── repo.py
│   ├── parsing/
│   │   ├── __init__.py
│   │   └── price_parser.py
│   ├── privacy/
│   │   ├── __init__.py
│   │   ├── consent_manager.py
│   │   └── handlers.py
│   └── utils/
│       ├── __init__.py
│       └── sampling.py
├── scripts/
│   └── run_opt_with_monitor.py
├── requirements.txt
└── .env
```
