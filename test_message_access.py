#!/usr/bin/env python3
"""
Тест доступа к сообщениям в канале
"""
import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError

load_dotenv()

async def test_message_access():
    """Тестируем доступ к сообщениям в канале"""
    token = os.getenv("TG_TOKEN_RETAIL")
    channel_id = int(os.getenv("CHANNEL_ID_STORE", "0") or "0")
    
    if not token or not channel_id:
        print("❌ Не настроены токен или ID канала")
        return
    
    bot = Bot(token)
    try:
        print(f"🤖 Тестируем доступ к каналу {channel_id}")
        
        # Получаем информацию о канале
        try:
            chat = await bot.get_chat(channel_id)
            print(f"✅ Канал доступен: {chat.title}")
            print(f"   Тип: {chat.type}")
        except Exception as e:
            print(f"❌ Не удалось получить информацию о канале: {e}")
            return
        
        # Тестируем доступ к разным сообщениям
        test_message_ids = [1, 2, 3, 4, 5, 10, 20, 50, 100]
        
        print(f"\n🔍 Тестируем доступ к сообщениям...")
        accessible_messages = []
        
        for msg_id in test_message_ids:
            try:
                # Пробуем получить сообщение
                message = await bot.get_chat_member(channel_id, bot.id)
                print(f"   ✅ Сообщение {msg_id}: доступно")
                accessible_messages.append(msg_id)
            except TelegramBadRequest as e:
                if "message not found" in str(e).lower():
                    print(f"   ❌ Сообщение {msg_id}: не найдено")
                elif "chat not found" in str(e).lower():
                    print(f"   ❌ Сообщение {msg_id}: чат не найден")
                else:
                    print(f"   ❌ Сообщение {msg_id}: {e}")
            except Exception as e:
                print(f"   ❌ Сообщение {msg_id}: {e}")
        
        print(f"\n📊 Результаты:")
        print(f"   Доступных сообщений: {len(accessible_messages)}")
        print(f"   ID доступных сообщений: {accessible_messages}")
        
        if accessible_messages:
            print(f"\n💡 Рекомендации:")
            print(f"   - Используйте ID сообщений: {accessible_messages}")
            print(f"   - Обновите monitored_posts с этими ID")
        else:
            print(f"\n⚠️ Внимание:")
            print(f"   - Нет доступных сообщений")
            print(f"   - Возможно, бот добавлен после публикации всех постов")
            print(f"   - Нужно дождаться новых сообщений в канале")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(test_message_access())
