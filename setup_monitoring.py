#!/usr/bin/env python3
"""
Скрипт для настройки мониторинга каналов
"""
import os
import asyncio
from dotenv import load_dotenv
from app_store.db.core import init_models
# Импортируем функцию из bot_retail2.py
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from bot_retail2 import set_monitored_message_ids

load_dotenv()

async def setup_monitoring():
    """Настройка мониторинга каналов"""
    print("🔧 Настройка мониторинга каналов...")
    
    # Инициализируем БД
    await init_models()
    
    # Получаем ID каналов из .env
    channel_id_store = os.getenv("CHANNEL_ID_STORE")
    channel_id_opt = os.getenv("CHANNEL_ID_OPT")
    
    print(f"📱 Store канал: {channel_id_store}")
    print(f"🏢 Opt канал: {channel_id_opt}")
    
    if not channel_id_store or not channel_id_opt:
        print("❌ Не настроены ID каналов в .env файле!")
        return
    
    try:
        # Настраиваем мониторинг для store канала
        if channel_id_store:
            store_id = int(channel_id_store)
            # Используем ID канала как message_id (временное решение)
            # В реальности нужно указать ID конкретных сообщений для мониторинга
            await set_monitored_message_ids('store', [1])  # Используем message_id = 1
            print(f"✅ Store канал {store_id} настроен для мониторинга (message_id=1)")
        
        # Настраиваем мониторинг для opt канала  
        if channel_id_opt:
            opt_id = int(channel_id_opt)
            # Используем ID канала как message_id (временное решение)
            await set_monitored_message_ids('opt', [1])  # Используем message_id = 1
            print(f"✅ Opt канал {opt_id} настроен для мониторинга (message_id=1)")
            
        print("🎉 Мониторинг настроен успешно!")
        print("💡 Примечание: Используются message_id=1 для обоих каналов.")
        print("   Для точной настройки укажите конкретные ID сообщений.")
        
    except Exception as e:
        print(f"❌ Ошибка при настройке мониторинга: {e}")

if __name__ == "__main__":
    asyncio.run(setup_monitoring())
