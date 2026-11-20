"""Strict Telegram ID whitelist middleware blocking all unauthorized users."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger("dostonbek.security")


def is_authorized_user(user_id: int | None, allowed_id: int) -> bool:
    return user_id is not None and allowed_id > 0 and user_id == allowed_id


class AllowedUserMiddleware(BaseMiddleware):
    """Rejects any Message or CallbackQuery not originating from ALLOWED_TELEGRAM_ID."""

    def __init__(self, allowed_telegram_id: int) -> None:
        super().__init__()
        self.allowed_telegram_id = allowed_telegram_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        user_id = getattr(user, "id", None)

        if not is_authorized_user(user_id, self.allowed_telegram_id):
            logger.warning("Ruxsatsiz foydalanuvchi urinishi bloklandi (user_id=%s)", user_id)
            if isinstance(event, CallbackQuery):
                await event.answer(
                    "⛔ Kirish taqiqlangan. Bu shaxsiy bot faqat egasi uchun.",
                    show_alert=True,
                )
            elif isinstance(event, Message):
                await event.answer(
                    "⛔ <b>Ruxsat berilmagan.</b>\n"
                    "Ushbu shaxsiy AI kotib faqat belgilangan Telegram egasi tomonidan boshqariladi.",
                    parse_mode="HTML",
                )
            return None

        return await handler(event, data)
