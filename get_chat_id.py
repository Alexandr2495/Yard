#!/usr/bin/env python3
"""
Скрипт для получения ID чата
"""
import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot

load_dotenv()

async def get_chat_id():
    """Получить ID чата, в который добавлен бот"""
    token = os.getenv("TG_TOKEN_RETAIL")  # или TG_TOKEN_OPT
    if not token:
        print("❌ Токен бота не найден в .env")
        return
    
    bot = Bot(token)
    try:
        me = await bot.get_me()
        print(f"🤖 Бот: @{me.username} (ID: {me.id})")
        print("\n📋 Инструкция:")
        print("1. Добавьте этого бота в ваш чат")
        print("2. Отправьте любое сообщение в чат")
        print("3. Нажмите Ctrl+C для выхода")
        print("\n⏳ Ожидание сообщений...")
        
        # Получаем обновления
        updates = await bot.get_updates(limit=1, timeout=30)
        if updates:
            update = updates[0]
            if update.message:
                chat = update.message.chat
                print(f"\n✅ Чат найден!")
                print(f"   ID: {chat.id}")
                print(f"   Название: {chat.title}")
                print(f"   Тип: {chat.type}")
                if chat.username:
                    print(f"   Username: @{chat.username}")
            else:
                print("❌ Сообщение не найдено")
        else:
            print("❌ Обновления не получены")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(get_chat_id())
