#!/bin/bash

# Скрипт для деплоя только нужных файлов на сервер
# Использование: ./deploy_to_server.sh [IP_СЕРВЕРА]

SERVER_IP=${1:-"46.148.238.248"}
SERVER_USER="root"
LOCAL_PATH="/Users/macbook/Desktop/Yard_bot"
REMOTE_PATH="/root/Yard_bot"

echo "🚀 Деплой на сервер $SERVER_IP"

# Создаем директорию на сервере
ssh $SERVER_USER@$SERVER_IP "mkdir -p $REMOTE_PATH"

# Копируем основные файлы ботов
echo "📁 Копируем основные боты..."
scp $LOCAL_PATH/bot_retail2.py $SERVER_USER@$SERVER_IP:$REMOTE_PATH/
scp $LOCAL_PATH/bot_wholesale.py $SERVER_USER@$SERVER_IP:$REMOTE_PATH/

# Копируем модуль app_store
echo "📁 Копируем модуль app_store..."
scp -r $LOCAL_PATH/app_store $SERVER_USER@$SERVER_IP:$REMOTE_PATH/

# Копируем скрипты
echo "📁 Копируем скрипты..."
ssh $SERVER_USER@$SERVER_IP "mkdir -p $REMOTE_PATH/scripts"
scp $LOCAL_PATH/scripts/run_opt_with_monitor.py $SERVER_USER@$SERVER_IP:$REMOTE_PATH/scripts/

# Копируем requirements.txt
echo "📁 Копируем requirements.txt..."
scp $LOCAL_PATH/requirements.txt $SERVER_USER@$SERVER_IP:$REMOTE_PATH/

# Копируем .env (если существует)
if [ -f "$LOCAL_PATH/.env" ]; then
    echo "📁 Копируем .env..."
    scp $LOCAL_PATH/.env $SERVER_USER@$SERVER_IP:$REMOTE_PATH/
else
    echo "⚠️  Файл .env не найден! Создайте его на сервере вручную."
fi

echo "✅ Деплой завершен!"
echo "📋 Следующие шаги на сервере:"
echo "1. cd $REMOTE_PATH"
echo "2. pip install -r requirements.txt"
echo "3. Настройте .env файл с токенами и настройками БД"
echo "4. Запустите ботов:"
echo "   - python bot_retail2.py"
echo "   - python bot_wholesale.py"
echo "   - python scripts/run_opt_with_monitor.py"
