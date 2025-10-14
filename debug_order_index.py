#!/usr/bin/env python3
"""
Диагностика order_index в базе данных
"""
import asyncio
import os
from sqlalchemy import text
from app_store.db.core import Session

async def debug_order_index():
    """Проверяем order_index в базе"""
    async with Session() as s:
        # Проверяем структуру таблицы
        result = await s.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'products' AND column_name = 'order_index'
        """))
        
        print("=== Структура поля order_index ===")
        for row in result:
            print(f"Column: {row[0]}, Type: {row[1]}, Nullable: {row[2]}, Default: {row[3]}")
        
        # Проверяем товары из конкретного поста
        result = await s.execute(text("""
            SELECT name, order_index, available, group_message_id, updated_at
            FROM products 
            WHERE available = true AND group_message_id = 2289
            ORDER BY name
            LIMIT 10
        """))
        
        print("\n=== Товары из поста 2289 ===")
        for row in result:
            print(f"{row[0]} | order_index: {row[1]} | available: {row[2]} | msg_id: {row[3]} | updated: {row[4]}")
        
        # Статистика по order_index
        result = await s.execute(text("""
            SELECT 
                COUNT(*) as total,
                COUNT(order_index) as with_index,
                COUNT(*) - COUNT(order_index) as null_index
            FROM products 
            WHERE available = true
        """))
        
        print("\n=== Статистика order_index ===")
        for row in result:
            print(f"Всего товаров: {row[0]}, С индексом: {row[1]}, NULL: {row[2]}")

if __name__ == "__main__":
    asyncio.run(debug_order_index())
