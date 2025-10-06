# -*- coding: utf-8 -*-
"""
Менеджер согласия на обработку персональных данных
Соответствует требованиям 152-ФЗ "О персональных данных"
"""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app_store.db.core import Session, UserConsent, PrivacyPolicy


class ConsentManager:
    """Менеджер для работы с согласием на обработку ПД"""
    
    @staticmethod
    async def check_user_consent(user_id: int) -> bool:
        """Проверяет, дал ли пользователь согласие на обработку ПД"""
        async with Session() as session:
            result = await session.execute(
                select(UserConsent).where(UserConsent.user_id == user_id)
            )
            consent = result.scalar_one_or_none()
            
            if not consent:
                return False
                
            return consent.consent_given and not consent.consent_revoked
    
    @staticmethod
    async def save_user_consent(
        user_id: int, 
        username: str = None,
        ip_address: str = None, 
        user_agent: str = None
    ) -> bool:
        """Сохраняет согласие пользователя"""
        async with Session() as session:
            # Проверяем, есть ли уже запись
            result = await session.execute(
                select(UserConsent).where(UserConsent.user_id == user_id)
            )
            consent = result.scalar_one_or_none()
            
            if consent:
                # Обновляем существующую запись
                consent.consent_given = True
                consent.consent_date = datetime.utcnow()
                consent.consent_revoked = False
                consent.revocation_date = None
                consent.revocation_reason = None
                consent.updated_at = datetime.utcnow()
            else:
                # Создаем новую запись
                consent = UserConsent(
                    user_id=user_id,
                    username=username,
                    consent_given=True,
                    consent_date=datetime.utcnow(),
                    consent_version="1.0",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                session.add(consent)
            
            await session.commit()
            return True
    
    @staticmethod
    async def revoke_user_consent(user_id: int, reason: str = None) -> bool:
        """Отзывает согласие пользователя"""
        async with Session() as session:
            result = await session.execute(
                select(UserConsent).where(UserConsent.user_id == user_id)
            )
            consent = result.scalar_one_or_none()
            
            if consent:
                consent.consent_revoked = True
                consent.revocation_date = datetime.utcnow()
                consent.revocation_reason = reason
                consent.updated_at = datetime.utcnow()
                await session.commit()
                return True
            return False
    
    @staticmethod
    async def get_consent_status(user_id: int) -> Dict[str, Any]:
        """Получает статус согласия пользователя"""
        async with Session() as session:
            result = await session.execute(
                select(UserConsent).where(UserConsent.user_id == user_id)
            )
            consent = result.scalar_one_or_none()
            
            if not consent:
                return {
                    "has_consent": False,
                    "is_revoked": False,
                    "consent_date": None,
                    "marketing_consent": False
                }
            
            return {
                "has_consent": consent.consent_given,
                "is_revoked": consent.consent_revoked,
                "consent_date": consent.consent_date,
                "marketing_consent": consent.marketing_consent,
                "consent_version": consent.consent_version
            }
    
    @staticmethod
    async def set_marketing_consent(user_id: int, consent: bool) -> bool:
        """Устанавливает согласие на маркетинговые рассылки"""
        async with Session() as session:
            result = await session.execute(
                select(UserConsent).where(UserConsent.user_id == user_id)
            )
            user_consent = result.scalar_one_or_none()
            
            if user_consent:
                user_consent.marketing_consent = consent
                user_consent.marketing_consent_date = datetime.utcnow() if consent else None
                user_consent.updated_at = datetime.utcnow()
                await session.commit()
                return True
            return False
    
    @staticmethod
    async def get_consent_statistics() -> Dict[str, int]:
        """Получает статистику согласий"""
        async with Session() as session:
            # Общее количество пользователей с согласием
            total_consent = await session.execute(
                select(UserConsent).where(
                    UserConsent.consent_given == True,
                    UserConsent.consent_revoked == False
                )
            )
            total_consent_count = len(total_consent.scalars().all())
            
            # Количество отзывов согласия
            revoked_consent = await session.execute(
                select(UserConsent).where(UserConsent.consent_revoked == True)
            )
            revoked_count = len(revoked_consent.scalars().all())
            
            # Количество подписок на маркетинг
            marketing_consent = await session.execute(
                select(UserConsent).where(UserConsent.marketing_consent == True)
            )
            marketing_count = len(marketing_consent.scalars().all())
            
            return {
                "total_consent": total_consent_count,
                "revoked_consent": revoked_count,
                "marketing_consent": marketing_count
            }


# Тексты для согласия (адаптированные под ваш проект)
CONSENT_TEXTS = {
    "welcome": """
🔒 <b>Согласие на обработку персональных данных</b>

Добро пожаловать в наш магазин! Для работы с ботом нам необходимо обрабатывать ваши персональные данные в соответствии с 152-ФЗ "О персональных данных".

📋 <b>Какие данные мы собираем:</b>
• Telegram ID и username (для связи с вами)
• Информация о заказах (товары, количество, цены)
• Фотографии документов (при необходимости подтверждения)
• История покупок (для улучшения сервиса)

🎯 <b>Цели обработки:</b>
• Обработка и выполнение ваших заказов
• Связь с вами по вопросам заказов
• Обеспечение безопасности и предотвращение мошенничества
• Улучшение качества сервиса

⏰ <b>Срок хранения:</b> 3 года с момента последней активности

📄 <b>Подробная информация:</b>
[Политика конфиденциальности](https://your-domain.com/privacy)
[Согласие на обработку ПД](https://your-domain.com/consent)

<i>Нажимая кнопку "Согласен", вы подтверждаете ознакомление с документами и даете согласие на обработку персональных данных.</i>
""",
    
    "welcome_wholesale": """
🔒 <b>Согласие на обработку персональных данных</b>

Добро пожаловать в наш <b>оптовый магазин</b>! 🏢

Для работы с ботом нам необходимо обрабатывать ваши персональные данные в соответствии с 152-ФЗ "О персональных данных".

📋 <b>Какие данные мы собираем:</b>
• Telegram ID и username (для связи с вами)
• Информация о заказах (товары, количество, цены)
• Фотографии документов (при необходимости подтверждения)
• История покупок (для улучшения сервиса)

🎯 <b>Цели обработки:</b>
• Обработка и выполнение ваших заказов
• Связь с вами по вопросам заказов
• Обеспечение безопасности и предотвращение мошенничества
• Улучшение качества сервиса

⏰ <b>Срок хранения:</b> 3 года с момента последней активности

📄 <b>Подробная информация:</b>
[Политика конфиденциальности](https://your-domain.com/privacy)
[Согласие на обработку ПД](https://your-domain.com/consent)

<i>Нажимая кнопку "Согласен", вы подтверждаете ознакомление с документами и даете согласие на обработку персональных данных.</i>
""",
    
    "welcome_retail": """
🔒 <b>Согласие на обработку персональных данных</b>

Добро пожаловать в <b>Techno Yard</b>! 🛍️

Для работы с ботом нам необходимо обрабатывать ваши персональные данные в соответствии с 152-ФЗ "О персональных данных".

📋 <b>Какие данные мы собираем:</b>
• Telegram ID и username (для связи с вами)
• Информация о заказах (товары, количество, цены)
• Фотографии документов (при необходимости подтверждения)
• История покупок (для улучшения сервиса)

🎯 <b>Цели обработки:</b>
• Обработка и выполнение ваших заказов
• Связь с вами по вопросам заказов
• Обеспечение безопасности и предотвращение мошенничества
• Улучшение качества сервиса

⏰ <b>Срок хранения:</b> 3 года с момента последней активности

📄 <b>Подробная информация:</b>
[Политика конфиденциальности](https://your-domain.com/privacy)
[Согласие на обработку ПД](https://your-domain.com/consent)

<i>Нажимая кнопку "Согласен", вы подтверждаете ознакомление с документами и даете согласие на обработку персональных данных.</i>
""",
    
    "marketing": """
📢 <b>Согласие на получение рекламных сообщений</b>

Хотите получать уведомления о:
• Новых поступлениях товаров
• Специальных предложениях и скидках
• Акциях и распродажах
• Важных обновлениях сервиса

<i>Вы можете отписаться в любое время командой /unsubscribe</i>
""",
    
    "revoke": """
❌ <b>Отзыв согласия</b>

Вы можете отозвать согласие на обработку персональных данных в любое время.

⚠️ <b>Внимание:</b> После отзыва согласия мы не сможем обрабатывать ваши заказы.

Выберите причину отзыва:
""",
    
    "revoked": """
✅ <b>Согласие отозвано</b>

Ваше согласие на обработку персональных данных отозвано.

Для продолжения работы с ботом необходимо дать новое согласие.
""",
    
    "consent_required": """
❌ <b>Требуется согласие</b>

Для продолжения работы необходимо дать согласие на обработку персональных данных.

Используйте команду /start для получения согласия.
"""
}
