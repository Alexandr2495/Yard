#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для получения ID канала по username
"""
import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot

load_dotenv()

async def get_channel_id_by_username(username: str, bot_token: str):
    """Получить ID канала по username"""
    bot = Bot(token=bot_token)
    
    try:
        chat = await bot.get_chat(f"@{username}")
        print(f"📱 Канал: {chat.title}")
        print(f"   Username: @{chat.username}")
        print(f"   ID: {chat.id}")
        print(f"   Тип: {chat.type}")
        return chat.id
    except Exception as e:
        print(f"❌ Ошибка получения канала @{username}: {e}")
        return None
    finally:
        await bot.session.close()

async def main():
    """Основная функция"""
    print("🔍 ПОЛУЧЕНИЕ ID КАНАЛА ПО USERNAME")
    print("=" * 40)
    
    # Замените на username ваших каналов
    retail_channel_username = input("Введите username розничного канала (без @): ")
    opt_channel_username = input("Введите username оптового канала (без @): ")
    
    retail_token = os.getenv("TG_TOKEN_RETAIL")
    opt_token = os.getenv("TG_TOKEN_OPT")
    
    if retail_channel_username:
        print(f"\n📱 РОЗНИЧНЫЙ КАНАЛ:")
        await get_channel_id_by_username(retail_channel_username, retail_token)
    
    if opt_channel_username:
        print(f"\n🏢 ОПТОВЫЙ КАНАЛ:")
        await get_channel_id_by_username(opt_channel_username, opt_token)

if __name__ == "__main__":
    asyncio.run(main())
