# -*- coding: utf-8 -*-
"""
Обработчики для системы согласия на обработку персональных данных
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app_store.privacy.consent_manager import ConsentManager, CONSENT_TEXTS


# Создаем роутер для обработчиков согласия
consent_router = Router()


class ConsentStates(StatesGroup):
    waiting_for_revoke_reason = State()


def get_consent_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для согласия"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Согласен", callback_data="consent_agree"),
            InlineKeyboardButton(text="❌ Отказаться", callback_data="consent_decline")
        ],
        [
            InlineKeyboardButton(text="📄 Политика конфиденциальности", url="https://your-domain.com/privacy"),
            InlineKeyboardButton(text="📋 Согласие на обработку ПД", url="https://your-domain.com/consent")
        ]
    ])


def get_marketing_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для маркетингового согласия"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подписаться", callback_data="marketing_agree"),
            InlineKeyboardButton(text="❌ Отказаться", callback_data="marketing_decline")
        ]
    ])


def get_revoke_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для отзыва согласия"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔒 Отозвать согласие", callback_data="consent_revoke"),
            InlineKeyboardButton(text="📧 Отписаться от рассылок", callback_data="marketing_unsubscribe")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
        ]
    ])


@consent_router.message(Command("start"))
async def cmd_start_with_consent(message: Message):
    """Обработчик команды /start с проверкой согласия"""
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Проверяем, есть ли согласие
    has_consent = await ConsentManager.check_user_consent(user_id)
    
    if not has_consent:
        # Показываем согласие на обработку ПД
        await message.answer(
            CONSENT_TEXTS["welcome"],
            reply_markup=get_consent_keyboard(),
            parse_mode="HTML"
        )
    else:
        # Показываем основное меню (это будет переопределено в основном боте)
        await message.answer(
            "✅ <b>Добро пожаловать!</b>\n\n"
            "Вы уже дали согласие на обработку персональных данных.\n"
            "Можете пользоваться всеми функциями бота.",
            parse_mode="HTML"
        )


@consent_router.callback_query(F.data == "consent_agree")
async def handle_consent_agree(callback: CallbackQuery):
    """Обработчик согласия на обработку ПД"""
    user_id = callback.from_user.id
    username = callback.from_user.username
    
    # Сохраняем согласие
    await ConsentManager.save_user_consent(
        user_id=user_id,
        username=username,
        ip_address=str(callback.message.chat.id),  # В реальности нужно получать IP
        user_agent="Telegram Bot"
    )
    
    await callback.message.edit_text(
        "✅ <b>Согласие получено!</b>\n\n"
        "Теперь вы можете пользоваться нашим магазином.\n\n"
        "Хотите подписаться на уведомления о новых товарах?",
        reply_markup=get_marketing_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@consent_router.callback_query(F.data == "consent_decline")
async def handle_consent_decline(callback: CallbackQuery):
    """Обработчик отказа от согласия"""
    await callback.message.edit_text(
        "❌ <b>Согласие не получено</b>\n\n"
        "К сожалению, без согласия на обработку персональных данных "
        "мы не можем предоставить вам услуги.\n\n"
        "Если передумаете, используйте команду /start",
        parse_mode="HTML"
    )
    await callback.answer()


@consent_router.callback_query(F.data == "marketing_agree")
async def handle_marketing_agree(callback: CallbackQuery):
    """Обработчик согласия на маркетинговые рассылки"""
    user_id = callback.from_user.id
    
    await ConsentManager.set_marketing_consent(user_id, True)
    
    await callback.message.edit_text(
        "✅ <b>Подписка оформлена!</b>\n\n"
        "Теперь вы будете получать новости и специальные предложения.\n\n"
        "Добро пожаловать в наш магазин! 🛍",
        parse_mode="HTML"
    )
    await callback.answer()


@consent_router.callback_query(F.data == "marketing_decline")
async def handle_marketing_decline(callback: CallbackQuery):
    """Обработчик отказа от маркетинговых рассылок"""
    user_id = callback.from_user.id
    
    await ConsentManager.set_marketing_consent(user_id, False)
    
    await callback.message.edit_text(
        "❌ <b>Подписка отклонена</b>\n\n"
        "Вы не будете получать рекламные сообщения.\n\n"
        "Добро пожаловать в наш магазин! 🛍",
        parse_mode="HTML"
    )
    await callback.answer()


@consent_router.callback_query(F.data == "consent_revoke")
async def handle_consent_revoke(callback: CallbackQuery):
    """Обработчик отзыва согласия"""
    user_id = callback.from_user.id
    
    # Отзываем согласие
    await ConsentManager.revoke_user_consent(user_id, "Пользователь отозвал согласие")
    
    await callback.message.edit_text(
        CONSENT_TEXTS["revoked"],
        parse_mode="HTML"
    )
    await callback.answer()


@consent_router.callback_query(F.data == "marketing_unsubscribe")
async def handle_marketing_unsubscribe(callback: CallbackQuery):
    """Обработчик отписки от маркетинговых рассылок"""
    user_id = callback.from_user.id
    
    await ConsentManager.set_marketing_consent(user_id, False)
    
    await callback.message.edit_text(
        "✅ <b>Отписка выполнена</b>\n\n"
        "Вы больше не будете получать рекламные сообщения.",
        parse_mode="HTML"
    )
    await callback.answer()


@consent_router.message(Command("privacy"))
async def cmd_privacy(message: Message):
    """Команда для просмотра политики конфиденциальности"""
    await message.answer(
        "🔒 <b>Политика конфиденциальности</b>\n\n"
        "📄 [Полная политика конфиденциальности](https://your-domain.com/privacy)\n"
        "📋 [Согласие на обработку ПД](https://your-domain.com/consent)\n\n"
        "Для управления согласием используйте команду /consent",
        parse_mode="HTML"
    )


@consent_router.message(Command("consent"))
async def cmd_consent_management(message: Message):
    """Управление согласием"""
    user_id = message.from_user.id
    status = await ConsentManager.get_consent_status(user_id)
    
    if not status["has_consent"]:
        await message.answer(
            "❌ <b>Согласие не получено</b>\n\n"
            "Для работы с ботом необходимо дать согласие на обработку персональных данных.\n"
            "Используйте команду /start",
            parse_mode="HTML"
        )
    else:
        consent_date = status['consent_date'].strftime('%d.%m.%Y %H:%M') if status['consent_date'] else 'Неизвестно'
        await message.answer(
            "🔒 <b>Управление согласием</b>\n\n"
            f"✅ Согласие получено: {consent_date}\n"
            f"📧 Маркетинговые рассылки: {'Включены' if status['marketing_consent'] else 'Отключены'}\n"
            f"❌ Статус: {'Отозвано' if status['is_revoked'] else 'Активно'}",
            reply_markup=get_revoke_keyboard(),
            parse_mode="HTML"
        )


@consent_router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    """Отписка от рассылок"""
    user_id = message.from_user.id
    await ConsentManager.set_marketing_consent(user_id, False)
    
    await message.answer(
        "✅ <b>Отписка выполнена</b>\n\n"
        "Вы больше не будете получать рекламные сообщения.",
        parse_mode="HTML"
    )


# Middleware для проверки согласия
class ConsentMiddleware:
    """Middleware для проверки согласия на обработку ПД"""
    
    async def __call__(self, handler, event, data):
        # Пропускаем команды управления согласием
        if hasattr(event, 'text') and event.text:
            if event.text.startswith('/privacy') or event.text.startswith('/consent') or event.text.startswith('/unsubscribe') or event.text.startswith('/start'):
                return await handler(event, data)
        
        # Пропускаем callback'и согласия
        if hasattr(event, 'data') and event.data:
            if event.data.startswith('consent_') or event.data.startswith('marketing_'):
                return await handler(event, data)
        
        # Проверяем согласие для всех остальных действий
        if hasattr(event, 'from_user') and event.from_user:
            user_id = event.from_user.id
            has_consent = await ConsentManager.check_user_consent(user_id)
            
            if not has_consent:
                if hasattr(event, 'answer'):
                    await event.answer(
                        CONSENT_TEXTS["consent_required"],
                        parse_mode="HTML"
                    )
                return
        
        return await handler(event, data)
