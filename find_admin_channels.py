#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для поиска всех каналов, где боты являются администраторами
"""
import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner, Update
from aiogram.exceptions import TelegramBadRequest

load_dotenv()

async def find_admin_channels(bot_token: str, bot_name: str):
    """Найти все каналы, где бот является администратором"""
    print(f"\n🔍 Поиск каналов для {bot_name}...")
    
    bot = Bot(token=bot_token)
    admin_channels = []
    
    try:
        # Получаем информацию о боте
        bot_info = await bot.get_me()
        print(f"   Бот: @{bot_info.username} (ID: {bot_info.id})")
        
        # К сожалению, Telegram Bot API не предоставляет прямой способ
        # получить список всех каналов, где бот является админом
        # Нужно проверять каналы вручную или использовать другие методы
        
        print("   ⚠️  Telegram Bot API не позволяет автоматически найти все каналы")
        print("   📝 Нужно проверить каналы вручную")
        
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
    finally:
        await bot.session.close()
    
    return admin_channels

async def check_specific_channel(bot_token: str, channel_id: int, bot_name: str):
    """Проверить конкретный канал"""
    bot = Bot(token=bot_token)
    
    try:
        chat_member = await bot.get_chat_member(channel_id, bot.id)
        
        if isinstance(chat_member, (ChatMemberAdministrator, ChatMemberOwner)):
            chat_info = await bot.get_chat(channel_id)
            print(f"   ✅ {bot_name} - АДМИНИСТРАТОР в канале:")
            print(f"      ID: {channel_id}")
            print(f"      Название: {chat_info.title}")
            print(f"      Username: @{chat_info.username}" if chat_info.username else "      Username: Нет")
            return True
        else:
            print(f"   ❌ {bot_name} - НЕ АДМИНИСТРАТОР в канале {channel_id}")
            return False
            
    except TelegramBadRequest as e:
        if "chat not found" in str(e).lower():
            print(f"   ❌ Канал {channel_id} не найден или бот не добавлен")
        else:
            print(f"   ❌ Ошибка доступа к каналу {channel_id}: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Ошибка проверки канала {channel_id}: {e}")
        return False
    finally:
        await bot.session.close()

async def main():
    """Основная функция"""
    print("🔍 ПОИСК КАНАЛОВ, ГДЕ БОТЫ ЯВЛЯЮТСЯ АДМИНИСТРАТОРАМИ")
    print("=" * 60)
    
    # Токены ботов
    retail_token = os.getenv("TG_TOKEN_RETAIL")
    opt_token = os.getenv("TG_TOKEN_OPT")
    
    if not retail_token or not opt_token:
        print("❌ Токены ботов не найдены в .env файле")
        return
    
    # Проверяем текущие каналы
    print("\n📱 ПРОВЕРКА ТЕКУЩИХ КАНАЛОВ:")
    print("-" * 40)
    
    # Retail бот
    store_channel = int(os.getenv("CHANNEL_ID_STORE", "0"))
    if store_channel:
        await check_specific_channel(retail_token, store_channel, "RETAIL БОТ")
    
    # Opt бот  
    opt_channel = int(os.getenv("CHANNEL_ID_OPT", "0"))
    if opt_channel:
        await check_specific_channel(opt_token, opt_channel, "OPT БОТ")
    
    print("\n" + "=" * 60)
    print("📋 ИНСТРУКЦИИ ДЛЯ ПОИСКА ПРОДАКШН КАНАЛОВ:")
    print("=" * 60)
    print("1. Зайдите в каждый канал, где должен работать бот")
    print("2. Убедитесь, что бот добавлен как администратор")
    print("3. Скопируйте ID канала (начинается с -100)")
    print("4. Обновите .env файл с новыми ID")
    print("\n💡 Для получения ID канала:")
    print("   - Перешлите сообщение из канала в @userinfobot")
    print("   - Или используйте @getidsbot")
    print("   - Или добавьте бота в канал и проверьте логи")

if __name__ == "__main__":
    asyncio.run(main())
