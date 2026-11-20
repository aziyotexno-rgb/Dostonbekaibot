"""VoIP call settings, manual test call trigger, and pure Uzbek call history viewer."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from caller.voip_engine import TelegramVoIPCaller
from config import Settings
from database.engine import DatabaseManager
from database.repository import BotRepository
from keyboards.inline import back_home_kb, call_settings_kb
from scheduler.jobs import BotScheduler
from utils.time_utils import format_uz_datetime

router = Router(name="calls")

CALL_STATUS_UZ = {
    "completed": "Muvaffaqiyatli yakunlandi",
    "answered": "Javob berildi",
    "no_response": "Javob berilmadi",
    "hung_up_unconfirmed": "Qizil tugma bilan tugatildi (vazifa tasdiqlanmadi)",
    "declined": "Rad etildi",
    "missed": "Javob berilmadi",
    "unavailable": "VoIP muhiti tayyor emas",
    "failed": "Xatolik",
}


def _build_call_settings_text(voip: TelegramVoIPCaller, settings: Settings) -> str:
    caps = voip.get_capabilities()
    voip_state = (
        "✅ Tayyor"
        if caps.supported
        else f"⚠️ Tayyor emas ({', '.join(caps.missing_components)})"
    )
    return (
        "📞 <b>Qo‘ng‘iroq sozlamalari (1:1 Telegram VoIP)</b>\n\n"
        f"• Qo‘ng‘iroq qiluvchi: <code>{settings.caller_username}</code>\n"
        f"• Qabul qiluvchi: <code>{settings.callee_username}</code>\n"
        f"• Dvigatel holati: <b>{voip_state}</b>\n\n"
        f"<i>{caps.note}</i>"
    )


@router.callback_query(F.data == "menu:call_settings")
async def cb_call_settings(
    callback: CallbackQuery,
    db: DatabaseManager,
    voip: TelegramVoIPCaller,
    settings: Settings,
) -> None:
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.get_settings(user.id)

    if callback.message:
        await callback.message.edit_text(
            _build_call_settings_text(voip, settings),
            reply_markup=call_settings_kb(cfg),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "cfg:toggle_morning")
async def cb_toggle_morning(
    callback: CallbackQuery,
    db: DatabaseManager,
    scheduler: BotScheduler,
    voip: TelegramVoIPCaller,
    settings: Settings,
) -> None:
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.get_settings(user.id)
        cfg = await repo.update_settings(
            user.id, morning_call_enabled=not cfg.morning_call_enabled
        )
        scheduler.sync_daily_jobs(
            user_id=user.id,
            telegram_id=user.telegram_id,
            tz_name=user.timezone,
            morning_time=cfg.morning_call_time,
            morning_enabled=cfg.morning_call_enabled,
            evening_time=cfg.evening_report_time,
            evening_enabled=cfg.evening_report_enabled,
        )

    if callback.message:
        await callback.message.edit_text(
            _build_call_settings_text(voip, settings),
            reply_markup=call_settings_kb(cfg),
            parse_mode="HTML",
        )
    await callback.answer("Yangilandi")


@router.callback_query(F.data == "cfg:toggle_retry")
async def cb_toggle_retry(
    callback: CallbackQuery,
    db: DatabaseManager,
    voip: TelegramVoIPCaller,
    settings: Settings,
) -> None:
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.get_settings(user.id)
        cfg = await repo.update_settings(
            user.id, retry_call_enabled=not cfg.retry_call_enabled
        )

    if callback.message:
        await callback.message.edit_text(
            _build_call_settings_text(voip, settings),
            reply_markup=call_settings_kb(cfg),
            parse_mode="HTML",
        )
    await callback.answer("Qayta qo‘ng‘iroq sozlamasi yangilandi")


@router.callback_query(F.data == "call:test_now")
async def cb_test_call_now(
    callback: CallbackQuery,
    db: DatabaseManager,
    scheduler: BotScheduler,
) -> None:
    await callback.answer("Qo‘ng‘iroq boshlanmoqda...")
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        user_id = user.id
        tg_id = user.telegram_id

    status = await scheduler.trigger_morning_call_now(user_id, tg_id)
    human_status = CALL_STATUS_UZ.get(status, status)
    if callback.message:
        await callback.message.answer(
            f"📞 Sinov qo‘ng‘irog‘i natijasi: <b>{human_status}</b>",
            reply_markup=back_home_kb(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "call:history")
async def cb_call_history(callback: CallbackQuery, db: DatabaseManager) -> None:
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        calls = await repo.list_recent_calls(user.id, limit=10)

    if not calls:
        text = "📜 <b>Qo‘ng‘iroqlar tarixi</b>\n\nHali qo‘ng‘iroqlar amalga oshirilmagan."
    else:
        lines = []
        for c in calls:
            dt_str = format_uz_datetime(c.created_at, user.timezone) if c.created_at else "-"
            status_label = CALL_STATUS_UZ.get(c.status, c.status)
            reply_line = f"\n  🗣 Javob: <i>{c.user_voice_reply}</i>" if c.user_voice_reply else ""
            lines.append(
                f"• <b>{status_label}</b> ({c.duration_seconds} soniya) · {dt_str}\n"
                f"  {c.caller_username} → {c.callee_username} · urinish #{c.attempt_number}"
                f"{reply_line}"
                + (f"\n  ℹ️ {c.error_detail}" if c.error_detail else "")
            )
        text = "📜 <b>So‘nggi qo‘ng‘iroqlar tarixi</b>\n\n" + "\n\n".join(lines)

    if callback.message:
        await callback.message.edit_text(
            text, reply_markup=back_home_kb(), parse_mode="HTML"
        )
    await callback.answer()
