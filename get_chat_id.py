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
        
        # Получаем обновления с более длительным ожиданием
        print("⏳ Ожидание сообщений в чате...")
        print("💡 Отправьте любое сообщение в чат, где добавлен бот")
        
        # Ждем обновления до 60 секунд
        updates = await bot.get_updates(limit=10, timeout=60)
        
        if updates:
            print(f"\n📨 Получено {len(updates)} обновлений")
            for i, update in enumerate(updates):
                print(f"\n--- Обновление {i+1} ---")
                if update.message:
                    chat = update.message.chat
                    print(f"✅ Чат найден!")
                    print(f"   ID: {chat.id}")
                    print(f"   Название: {chat.title}")
                    print(f"   Тип: {chat.type}")
                    if chat.username:
                        print(f"   Username: @{chat.username}")
                    if chat.id < 0:  # Это группа/канал
                        print(f"   🎯 Это группа/канал! ID для .env: {chat.id}")
                elif update.my_chat_member:
                    chat = update.my_chat_member.chat
                    print(f"✅ Бот добавлен в чат!")
                    print(f"   ID: {chat.id}")
                    print(f"   Название: {chat.title}")
                    print(f"   Тип: {chat.type}")
                    if chat.id < 0:  # Это группа/канал
                        print(f"   🎯 Это группа/канал! ID для .env: {chat.id}")
                else:
                    print(f"   Тип обновления: {update.update_type}")
        else:
            print("❌ Обновления не получены")
            print("💡 Убедитесь, что:")
            print("   1. Бот добавлен в чат")
            print("   2. В чате отправлено сообщение")
            print("   3. Бот имеет права на чтение сообщений")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(get_chat_id())
