"""Personal bot settings and admin-only PRO trial mode managed inside Telegram."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import Settings
from database.engine import DatabaseManager
from database.repository import BotRepository
from keyboards.inline import back_home_kb, bot_settings_kb, pro_trial_kb
from scheduler.jobs import BotScheduler
from utils.time_utils import format_uz_datetime, parse_quiet_range, parse_user_time
from voice.tts import SUPPORTED_UZBEK_VOICES, SUPPORTED_VOICE_RATES

router = Router(name="settings")


class SettingsStates(StatesGroup):
    morning_time = State()
    evening_time = State()
    timezone = State()
    quiet_hours = State()
    pro_days = State()


def _pro_panel_text(is_pro: bool, expires_at, tz_name: str) -> str:
    status_line = (
        f"✅ <b>Faol (Sinov rejimi)</b>\n"
        f"⏳ Tugash muddati: {format_uz_datetime(expires_at, tz_name) if expires_at else 'Cheklanmagan'}"
        if is_pro
        else "⚪ <b>Oddiy foydalanuvchi rejimi</b>"
    )
    return (
        "🧪 <b>PRO Obuna Sinov Rejimi (Faqat administrator uchun)</b>\n\n"
        f"Joriy holat: {status_line}\n\n"
        "<i>Eslatma: Bu faqat tizim imkoniyatlarini sinash uchun mo‘ljallangan rejim. "
        "Hech qanday haqiqiy to‘lov amalga oshirilmaydi.</i>\n\n"
        "<b>Taqqoslash:</b>\n"
        "• <b>Oddiy rejim:</b> Kuniga 3 tagacha qayta qo‘ng‘iroq, standart ovozli eslatmalar.\n"
        "• <b>PRO (Sinov):</b> 10 tagacha qayta qo‘ng‘iroq, kengaytirilgan javob kutish oynasi, cheksiz takroriy rejalar."
    )


@router.callback_query(F.data == "menu:bot_settings")
async def cb_bot_settings(callback: CallbackQuery, db: DatabaseManager) -> None:
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.get_settings(user.id)
        is_pro = await repo.is_pro_effective(user.id)

    if callback.message:
        await callback.message.edit_text(
            "⚙️ <b>Shaxsiy bot sozlamalari</b>\n\nO‘zgartirmoqchi bo‘lgan bandni tanlang:",
            reply_markup=bot_settings_kb(cfg, user.timezone, is_pro),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "cfg:set_morning_time")
async def cb_set_morning_time(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.morning_time)
    if callback.message:
        await callback.message.edit_text(
            "☀️ <b>Ertalabki qo‘ng‘iroq vaqtini kiriting</b>\n\nFormat: <code>SS:DD</code> (masalan: <code>08:00</code>):",
            reply_markup=back_home_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(SettingsStates.morning_time)
async def fsm_morning_time(
    message: Message,
    state: FSMContext,
    db: DatabaseManager,
    scheduler: BotScheduler,
) -> None:
    parsed = parse_user_time(message.text or "")
    if parsed is None:
        await message.answer("Noto‘g‘ri vaqt formati. Masalan: <code>08:00</code>.", parse_mode="HTML")
        return

    time_str = parsed.strftime("%H:%M")
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(message.from_user.id)
        cfg = await repo.update_settings(user.id, morning_call_time=time_str)
        is_pro = await repo.is_pro_effective(user.id)
        scheduler.sync_daily_jobs(
            user_id=user.id,
            telegram_id=user.telegram_id,
            tz_name=user.timezone,
            morning_time=cfg.morning_call_time,
            morning_enabled=cfg.morning_call_enabled,
            evening_time=cfg.evening_report_time,
            evening_enabled=cfg.evening_report_enabled,
        )

    await state.clear()
    await message.answer(
        f"✅ Qo‘ng‘iroq vaqti <b>{time_str}</b> ga o‘zgartirildi.",
        reply_markup=bot_settings_kb(cfg, user.timezone, is_pro),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cfg:set_evening_time")
async def cb_set_evening_time(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.evening_time)
    if callback.message:
        await callback.message.edit_text(
            "🌙 <b>Kunlik hisobot vaqtini kiriting</b>\n\nFormat: <code>SS:DD</code> (masalan: <code>21:00</code>):",
            reply_markup=back_home_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(SettingsStates.evening_time)
async def fsm_evening_time(
    message: Message,
    state: FSMContext,
    db: DatabaseManager,
    scheduler: BotScheduler,
) -> None:
    parsed = parse_user_time(message.text or "")
    if parsed is None:
        await message.answer("Noto‘g‘ri vaqt formati. Masalan: <code>21:00</code>.", parse_mode="HTML")
        return

    time_str = parsed.strftime("%H:%M")
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(message.from_user.id)
        cfg = await repo.update_settings(user.id, evening_report_time=time_str)
        is_pro = await repo.is_pro_effective(user.id)
        scheduler.sync_daily_jobs(
            user_id=user.id,
            telegram_id=user.telegram_id,
            tz_name=user.timezone,
            morning_time=cfg.morning_call_time,
            morning_enabled=cfg.morning_call_enabled,
            evening_time=cfg.evening_report_time,
            evening_enabled=cfg.evening_report_enabled,
        )

    await state.clear()
    await message.answer(
        f"✅ Kunlik hisobot vaqti <b>{time_str}</b> ga o‘zgartirildi.",
        reply_markup=bot_settings_kb(cfg, user.timezone, is_pro),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cfg:cycle_retry_delay")
async def cb_cycle_retry_delay(callback: CallbackQuery, db: DatabaseManager) -> None:
    delays = [3, 5, 10, 15, 30]
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.get_settings(user.id)
        is_pro = await repo.is_pro_effective(user.id)
        idx = delays.index(cfg.retry_call_delay_minutes) if cfg.retry_call_delay_minutes in delays else 1
        next_delay = delays[(idx + 1) % len(delays)]
        cfg = await repo.update_settings(user.id, retry_call_delay_minutes=next_delay)

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=bot_settings_kb(cfg, user.timezone, is_pro)
        )
    await callback.answer(f"Qayta qo‘ng‘iroq oralig‘i: {next_delay} daqiqa")


@router.callback_query(F.data == "cfg:cycle_max_attempts")
async def cb_cycle_max_attempts(callback: CallbackQuery, db: DatabaseManager) -> None:
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.get_settings(user.id)
        is_pro = await repo.is_pro_effective(user.id)
        allowed = [1, 2, 3, 5, 7, 10] if is_pro else [1, 2, 3]
        idx = allowed.index(cfg.retry_call_max_attempts) if cfg.retry_call_max_attempts in allowed else 0
        next_val = allowed[(idx + 1) % len(allowed)]
        cfg = await repo.update_settings(user.id, retry_call_max_attempts=next_val)

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=bot_settings_kb(cfg, user.timezone, is_pro)
        )
    await callback.answer(f"Maksimal urinishlar soni: {next_val} marta")


@router.callback_query(F.data == "cfg:cycle_wait_seconds")
async def cb_cycle_wait_seconds(callback: CallbackQuery, db: DatabaseManager) -> None:
    waits = [10, 15, 20, 30]
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.get_settings(user.id)
        is_pro = await repo.is_pro_effective(user.id)
        idx = waits.index(cfg.response_wait_seconds) if cfg.response_wait_seconds in waits else 1
        next_wait = waits[(idx + 1) % len(waits)]
        cfg = await repo.update_settings(user.id, response_wait_seconds=next_wait)

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=bot_settings_kb(cfg, user.timezone, is_pro)
        )
    await callback.answer(f"Javob kutish vaqti: {next_wait} soniya")


@router.callback_query(F.data == "cfg:set_quiet_hours")
async def cb_set_quiet_hours(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.quiet_hours)
    if callback.message:
        await callback.message.edit_text(
            "🔕 <b>Tinch vaqt oralig‘ini kiriting</b>\n\n"
            "Ushbu vaqt ichida bot qo‘ng‘iroq qilmaydi.\n"
            "Format: <code>23:00-07:00</code> (yoki o‘chirish uchun <code>o‘chirish</code> yozing):",
            reply_markup=back_home_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(SettingsStates.quiet_hours)
async def fsm_quiet_hours(
    message: Message, state: FSMContext, db: DatabaseManager
) -> None:
    raw = (message.text or "").strip().lower()
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(message.from_user.id)
        is_pro = await repo.is_pro_effective(user.id)

        if raw in {"o'chirish", "o‘chirish", "off"}:
            cfg = await repo.update_settings(user.id, quiet_hours_enabled=False)
            msg_out = "🔔 Tinch vaqt cheklovi o‘chirildi."
        else:
            parsed = parse_quiet_range(raw)
            if parsed is None:
                await message.answer(
                    "Noto‘g‘ri format. Masalan: <code>23:00-07:00</code> yoki <code>o‘chirish</code>.",
                    parse_mode="HTML",
                )
                return
            start_s, end_s = parsed
            cfg = await repo.update_settings(
                user.id,
                quiet_hours_enabled=True,
                quiet_hours_start=start_s,
                quiet_hours_end=end_s,
            )
            msg_out = f"✅ Tinch vaqt oralig‘i <b>{start_s}–{end_s}</b> etib belgilandi."

    await state.clear()
    await message.answer(
        msg_out,
        reply_markup=bot_settings_kb(cfg, user.timezone, is_pro),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cfg:cycle_voice")
async def cb_cycle_voice(callback: CallbackQuery, db: DatabaseManager) -> None:
    voices = list(SUPPORTED_UZBEK_VOICES.keys())
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.get_settings(user.id)
        is_pro = await repo.is_pro_effective(user.id)
        idx = voices.index(cfg.voice_name) if cfg.voice_name in voices else 0
        next_voice = voices[(idx + 1) % len(voices)]
        cfg = await repo.update_settings(user.id, voice_name=next_voice)

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=bot_settings_kb(cfg, user.timezone, is_pro)
        )
    await callback.answer(f"Ovoz: {SUPPORTED_UZBEK_VOICES[next_voice]}")


@router.callback_query(F.data == "cfg:cycle_rate")
async def cb_cycle_rate(callback: CallbackQuery, db: DatabaseManager) -> None:
    rates = list(SUPPORTED_VOICE_RATES.keys())
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.get_settings(user.id)
        is_pro = await repo.is_pro_effective(user.id)
        idx = rates.index(cfg.voice_rate) if cfg.voice_rate in rates else 1
        next_rate = rates[(idx + 1) % len(rates)]
        cfg = await repo.update_settings(user.id, voice_rate=next_rate)

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=bot_settings_kb(cfg, user.timezone, is_pro)
        )
    await callback.answer(f"Ovoz tezligi: {SUPPORTED_VOICE_RATES[next_rate]}")


@router.callback_query(F.data == "cfg:cycle_mode")
async def cb_cycle_mode(callback: CallbackQuery, db: DatabaseManager) -> None:
    modes = ["voice", "text", "call"]
    mode_uz = {"voice": "Ovozli", "text": "Matnli", "call": "Qo‘ng‘iroq"}
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.get_settings(user.id)
        is_pro = await repo.is_pro_effective(user.id)
        idx = modes.index(cfg.default_reminder_mode) if cfg.default_reminder_mode in modes else 0
        next_mode = modes[(idx + 1) % len(modes)]
        cfg = await repo.update_settings(user.id, default_reminder_mode=next_mode)

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=bot_settings_kb(cfg, user.timezone, is_pro)
        )
    await callback.answer(f"Standart usul: {mode_uz[next_mode]}")


@router.callback_query(F.data == "cfg:cycle_ai_style")
async def cb_cycle_ai_style(callback: CallbackQuery, db: DatabaseManager) -> None:
    styles = ["friendly", "formal", "concise"]
    style_uz = {"friendly": "Samimiy", "formal": "Rasmiy", "concise": "Qisqa"}
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.get_settings(user.id)
        is_pro = await repo.is_pro_effective(user.id)
        idx = styles.index(cfg.ai_style) if cfg.ai_style in styles else 0
        next_style = styles[(idx + 1) % len(styles)]
        cfg = await repo.update_settings(user.id, ai_style=next_style)

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=bot_settings_kb(cfg, user.timezone, is_pro)
        )
    await callback.answer(f"Muloqot uslubi: {style_uz[next_style]}")


@router.callback_query(F.data == "cfg:set_timezone")
async def cb_set_timezone(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.timezone)
    if callback.message:
        await callback.message.edit_text(
            "🌍 <b>Vaqt zonasini kiriting</b>\n\nMasalan: <code>Asia/Tashkent</code>, <code>Asia/Samarkand</code>:",
            reply_markup=back_home_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(SettingsStates.timezone)
async def fsm_timezone(
    message: Message,
    state: FSMContext,
    db: DatabaseManager,
    scheduler: BotScheduler,
) -> None:
    tz_raw = (message.text or "").strip()
    try:
        ZoneInfo(tz_raw)
    except Exception:
        await message.answer("Noto‘g‘ri vaqt zonasi. Masalan: <code>Asia/Tashkent</code>.", parse_mode="HTML")
        return

    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(message.from_user.id)
        user = await repo.update_user_timezone(user.id, tz_raw)
        cfg = await repo.get_settings(user.id)
        is_pro = await repo.is_pro_effective(user.id)
        scheduler.sync_daily_jobs(
            user_id=user.id,
            telegram_id=user.telegram_id,
            tz_name=user.timezone,
            morning_time=cfg.morning_call_time,
            morning_enabled=cfg.morning_call_enabled,
            evening_time=cfg.evening_report_time,
            evening_enabled=cfg.evening_report_enabled,
        )

    await state.clear()
    await message.answer(
        f"✅ Vaqt zonasi <b>{tz_raw}</b> ga o‘zgartirildi.",
        reply_markup=bot_settings_kb(cfg, user.timezone, is_pro),
        parse_mode="HTML",
    )


# === Admin-only PRO Trial Mode ===
@router.callback_query(F.data == "menu:pro_trial")
async def cb_pro_trial(
    callback: CallbackQuery, db: DatabaseManager, settings: Settings
) -> None:
    if callback.from_user.id != settings.allowed_telegram_id:
        await callback.answer("⛔ Bu bo‘lim faqat administrator uchun.", show_alert=True)
        return

    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        is_pro = await repo.is_pro_effective(user.id)
        cfg = await repo.get_settings(user.id)

    if callback.message:
        await callback.message.edit_text(
            _pro_panel_text(is_pro, cfg.pro_trial_expires_at, user.timezone),
            reply_markup=pro_trial_kb(is_pro),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("pro:activate:"))
async def cb_pro_activate(
    callback: CallbackQuery, db: DatabaseManager, settings: Settings
) -> None:
    if callback.from_user.id != settings.allowed_telegram_id:
        await callback.answer("⛔ Faqat administrator uchun.", show_alert=True)
        return

    days = int(callback.data.split(":")[-1])
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.activate_pro_trial(user.id, days=days)
        is_pro = await repo.is_pro_effective(user.id)

    if callback.message:
        await callback.message.edit_text(
            _pro_panel_text(is_pro, cfg.pro_trial_expires_at, user.timezone),
            reply_markup=pro_trial_kb(is_pro),
            parse_mode="HTML",
        )
    await callback.answer(f"🧪 {days} kunlik PRO sinov rejimi yoqildi (to‘lovsiz).")


@router.callback_query(F.data == "pro:custom_days")
async def cb_pro_custom_days(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    if callback.from_user.id != settings.allowed_telegram_id:
        await callback.answer("⛔ Faqat administrator uchun.", show_alert=True)
        return
    await state.set_state(SettingsStates.pro_days)
    if callback.message:
        await callback.message.edit_text(
            "📅 <b>PRO sinov muddatini kiriting (kun hisobida)</b>\n\nMasalan: <code>14</code> yoki <code>30</code>:",
            reply_markup=back_home_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(SettingsStates.pro_days)
async def fsm_pro_days(
    message: Message, state: FSMContext, db: DatabaseManager, settings: Settings
) -> None:
    if message.from_user.id != settings.allowed_telegram_id:
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 365):
        await message.answer("Iltimos, 1 dan 365 gacha butun son kiriting.")
        return

    days = int(raw)
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(message.from_user.id)
        cfg = await repo.activate_pro_trial(user.id, days=days)
        is_pro = await repo.is_pro_effective(user.id)

    await state.clear()
    await message.answer(
        _pro_panel_text(is_pro, cfg.pro_trial_expires_at, user.timezone),
        reply_markup=pro_trial_kb(is_pro),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "pro:check_features")
async def cb_pro_check(
    callback: CallbackQuery, db: DatabaseManager, settings: Settings
) -> None:
    if callback.from_user.id != settings.allowed_telegram_id:
        await callback.answer("⛔ Faqat administrator uchun.", show_alert=True)
        return

    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        is_pro = await repo.is_pro_effective(user.id)

    summary = (
        "✅ PRO sinov imkoniyatlari faol:\n• Maksimal qayta qo‘ng‘iroq: 10 marta\n• Bajarilmaguncha nazorat: faol"
        if is_pro
        else "⚪ Oddiy rejim faol:\n• Maksimal qayta qo‘ng‘iroq: 3 marta\n• PRO imkoniyatlar o‘chirilgan"
    )
    await callback.answer(summary, show_alert=True)


@router.callback_query(F.data == "pro:cancel")
async def cb_pro_cancel(
    callback: CallbackQuery, db: DatabaseManager, settings: Settings
) -> None:
    if callback.from_user.id != settings.allowed_telegram_id:
        await callback.answer("⛔ Faqat administrator uchun.", show_alert=True)
        return

    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        cfg = await repo.cancel_pro_trial(user.id)
        is_pro = await repo.is_pro_effective(user.id)

    if callback.message:
        await callback.message.edit_text(
            _pro_panel_text(is_pro, cfg.pro_trial_expires_at, user.timezone),
            reply_markup=pro_trial_kb(is_pro),
            parse_mode="HTML",
        )
    await callback.answer("PRO sinov rejimi bekor qilindi.")
