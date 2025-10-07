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
            await set_monitored_message_ids('store', [store_id])
            print(f"✅ Store канал {store_id} настроен для мониторинга")
        
        # Настраиваем мониторинг для opt канала  
        if channel_id_opt:
            opt_id = int(channel_id_opt)
            await set_monitored_message_ids('opt', [opt_id])
            print(f"✅ Opt канал {opt_id} настроен для мониторинга")
            
        print("🎉 Мониторинг настроен успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка при настройке мониторинга: {e}")

if __name__ == "__main__":
    asyncio.run(setup_monitoring())
