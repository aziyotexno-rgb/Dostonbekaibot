"""Start command and main inline menu navigation."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from database.engine import DatabaseManager
from database.repository import BotRepository
from keyboards.inline import main_menu_kb

router = Router(name="start")


def _welcome_text(name: str) -> str:
    return (
        f"👋 <b>Assalomu alaykum, {name}!</b>\n\n"
        "Men <b>Dostonbek AI Bot</b> — sizning shaxsiy AI kotibingizman.\n"
        "Quyidagi menyudan bo‘limni tanlang yoki menga oddiy matn / ovozli xabar yuboring:"
    )


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(
    message: Message,
    state: FSMContext,
    db: DatabaseManager,
    settings: Settings,
) -> None:
    await state.clear()
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.first_name or "Dostonbek",
            default_timezone=settings.default_timezone,
            default_voice_name=settings.default_voice_name,
            default_voice_rate=settings.default_voice_rate,
        )
    await message.answer(
        _welcome_text(user.full_name),
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:home")
async def cb_home(
    callback: CallbackQuery,
    state: FSMContext,
    db: DatabaseManager,
    settings: Settings,
) -> None:
    await state.clear()
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.first_name or "Dostonbek",
            default_timezone=settings.default_timezone,
        )
    if callback.message:
        await callback.message.edit_text(
            _welcome_text(user.full_name),
            reply_markup=main_menu_kb(),
            parse_mode="HTML",
        )
    await callback.answer()
