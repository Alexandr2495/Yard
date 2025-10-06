# Инструкция по деплою на сервер

## Подготовка сервера

1. **Подключение к серверу:**
```bash
ssh root@46.148.238.248
# При первом подключении введите "yes" для подтверждения ключа сервера
```

2. **Обновление системы:**
```bash
apt update && apt upgrade -y
```

3. **Установка Python и pip:**
```bash
apt install python3 python3-pip python3-venv -y
```

4. **Установка PostgreSQL:**
```bash
apt install postgresql postgresql-contrib -y
systemctl start postgresql
systemctl enable postgresql
```

5. **Создание пользователя и базы данных:**
```bash
sudo -u postgres psql
CREATE USER yardbot WITH PASSWORD 'your_password';
CREATE DATABASE yardbot OWNER yardbot;
\q
```

## Клонирование и настройка проекта

1. **Клонирование репозитория:**
```bash
cd /root
git clone https://github.com/Alexandr2495/Yard.git Yard_bot
cd Yard_bot
```

2. **Создание виртуального окружения:**
```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Установка зависимостей:**
```bash
pip install -r requirements.txt
```

4. **Создание .env файла:**
```bash
nano .env
```

Содержимое .env файла:
```env
# Telegram Bot Tokens
TG_TOKEN_RETAIL=your_retail_bot_token
TG_TOKEN_OPT=your_wholesale_bot_token

# Database
DATABASE_URL=postgresql+asyncpg://yardbot:your_password@localhost/yardbot

# Channel IDs
CHANNEL_ID_RETAIL=your_retail_channel_id
CHANNEL_ID_OPT=your_wholesale_channel_id

# Manager Group
MANAGER_GROUP_ID=your_manager_group_id

# Sink Chat (for monitoring)
SINK_CHAT_ID=your_sink_chat_id

# Tesseract (for OCR) - пока не настраиваем
# TESSERACT_CMD=/usr/bin/tesseract
```

5. **Tesseract (пропускаем - не настроен в проекте):**
```bash
# apt install tesseract-ocr tesseract-ocr-rus -y
# Пока не настраиваем OCR функциональность
```

## Запуск ботов

1. **Запуск в screen сессиях:**
```bash
# Retail бот
screen -S retail_bot
source venv/bin/activate
cd /root/Yard_bot
python bot_retail2.py
# Ctrl+A, D для выхода из screen

# Wholesale бот
screen -S wholesale_bot
source venv/bin/activate
cd /root/Yard_bot
python bot_wholesale.py
# Ctrl+A, D для выхода из screen

# Мониторинг
screen -S monitoring
source venv/bin/activate
cd /root/Yard_bot
python scripts/run_opt_with_monitor.py
# Ctrl+A, D для выхода из screen
```

2. **Проверка работы:**
```bash
screen -ls                    # Список сессий
screen -r retail_bot          # Подключение к сессии
```

## Автозапуск (опционально)

Создать systemd сервисы для автозапуска:

```bash
# /etc/systemd/system/yard-retail.service
[Unit]
Description=Yard Retail Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/Yard_bot
Environment=PATH=/root/Yard_bot/venv/bin
ExecStart=/root/Yard_bot/venv/bin/python bot_retail2.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable yard-retail
systemctl start yard-retail
```

## Мониторинг

- **Логи:** `journalctl -u yard-retail -f`
- **Статус:** `systemctl status yard-retail`
- **Перезапуск:** `systemctl restart yard-retail`
