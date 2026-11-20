"""AI Personal Secretary handler supporting Uzbek text and voice commands."""

from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, FSInputFile, Message

from ai.gemini_client import GeminiSecretary
from config import Settings
from database.engine import DatabaseManager
from database.repository import BotRepository
from keyboards.inline import back_home_kb, confirm_delete_kb
from scheduler.jobs import BotScheduler
from services.reminder_service import format_reminder_card
from utils.time_utils import combine_local, now_in_tz, parse_user_date, parse_user_time
from voice.commands import classify_call_voice_phrase
from voice.stt import transcribe_voice_file
from voice.tts import cleanup_audio_files, synthesize_uzbek_speech

logger = logging.getLogger("dostonbek.handlers.ai")
router = Router(name="ai_assistant")


@router.callback_query(F.data == "menu:ai")
async def cb_ai_menu(callback: CallbackQuery) -> None:
    text = (
        "🤖 <b>AI Shaxsiy Kotib</b>\n\n"
        "Menga istalgan o‘zbekcha matn yoki ovozli xabar yuboring. Masalan:\n"
        "• <i>\"Bugun soat 15:00 da Bahodirga qo‘ng‘iroq qilishimni eslat.\"</i>\n"
        "• <i>\"Har kuni ertalab soat 8 da kunlik rejalarimni ayt.\"</i>\n"
        "• <i>\"Ertangi soat 10 dagi vazifamni o‘chir.\"</i>\n"
        "• <i>\"Bugun qanday ishlarim bor?\"</i>\n"
        "• Tezkor buyruqlar: <i>\"Ha, bajardim\"</i>, <i>\"Hali bajarmadim\"</i>, "
        "<i>\"Keyinroq eslat\"</i>, <i>\"Bir soatdan keyin eslat\"</i>"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=back_home_kb(), parse_mode="HTML")
    await callback.answer()


@router.message(StateFilter(None), F.voice)
async def handle_voice_command(
    message: Message,
    db: DatabaseManager,
    gemini: GeminiSecretary,
    scheduler: BotScheduler,
    settings: Settings,
) -> None:
    if not gemini.is_configured:
        await message.answer("⚠️ GEMINI_API_KEY sozlanmaganligi sababli ovozli xabar tahlil qilinmadi.")
        return

    voice = message.voice
    assert voice is not None
    tmp_path = settings.audio_output_dir / f"in_{voice.file_unique_id}.ogg"
    settings.audio_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        await message.bot.download(voice, destination=tmp_path)
        transcript = await transcribe_voice_file(gemini, tmp_path, mime_type="audio/ogg")
        if not transcript:
            await message.answer("Ovozli xabarni aniqlab bo‘lmadi. Iltimos, qayta urinib ko‘ring.")
            return
        await message.answer(f"🎙 <i>Siz:</i> {transcript}", parse_mode="HTML")
        await _process_ai_text(
            message=message,
            user_text=transcript,
            db=db,
            gemini=gemini,
            scheduler=scheduler,
            settings=settings,
            reply_with_voice=True,
        )
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def handle_text_command(
    message: Message,
    db: DatabaseManager,
    gemini: GeminiSecretary,
    scheduler: BotScheduler,
    settings: Settings,
) -> None:
    await _process_ai_text(
        message=message,
        user_text=message.text or "",
        db=db,
        gemini=gemini,
        scheduler=scheduler,
        settings=settings,
        reply_with_voice=False,
    )


async def _send_voice_reply_if_requested(
    message: Message,
    reply_text: str,
    reply_with_voice: bool,
    settings: Settings,
    voice_name: str,
    voice_rate: str,
) -> None:
    if not reply_with_voice:
        return
    audio = None
    try:
        clean_spoken = reply_text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
        audio = await synthesize_uzbek_speech(
            text=clean_spoken[:500],
            output_dir=settings.audio_output_dir,
            voice_name=voice_name,
            voice_rate=voice_rate,
        )
        await message.answer_voice(FSInputFile(str(audio.ogg_path or audio.mp3_path)))
    except Exception as tts_exc:
        logger.debug("AI ovozli javob yuborilmadi: %s", tts_exc)
    finally:
        if audio:
            cleanup_audio_files(audio)


async def _process_ai_text(
    message: Message,
    user_text: str,
    db: DatabaseManager,
    gemini: GeminiSecretary,
    scheduler: BotScheduler,
    settings: Settings,
    reply_with_voice: bool,
) -> None:
    quick = classify_call_voice_phrase(user_text)
    if quick is not None:
        async with db.session() as sess:
            repo = BotRepository(sess)
            user = await repo.get_or_create_user(message.from_user.id)
            cfg = await repo.get_settings(user.id)
            pending = await repo.list_reminders(user.id, status="pending", limit=10)

            if quick.command == "list_today":
                today = now_in_tz(user.timezone).date()
                todays = await repo.list_reminders_for_date(user.id, today, user.timezone)
                if not todays:
                    reply_text = "Bugun uchun belgilangan vazifalar mavjud emas."
                else:
                    cards = [format_reminder_card(r, user.timezone) for r in todays]
                    reply_text = "📅 <b>Bugungi vazifalaringiz:</b>\n\n" + "\n\n".join(cards)
                await message.answer(reply_text, parse_mode="HTML")
                await _send_voice_reply_if_requested(message, reply_text, reply_with_voice, settings, cfg.voice_name, cfg.voice_rate)
                return

            if quick.command == "cancel_reminder" and pending:
                target = pending[0]
                pc = await repo.create_pending_confirmation(
                    user_id=user.id,
                    action_type="delete_reminder",
                    target_reminder_id=target.id,
                    payload={"title": target.title},
                )
                reply_text = (
                    "⚠️ <b>Tasdiqlash kerak:</b>\n\n"
                    "Ushbu eslatmani o‘chirmoqchimisiz?\n"
                    f"{format_reminder_card(target, user.timezone)}"
                )
                await message.answer(reply_text, reply_markup=confirm_delete_kb(pc.id), parse_mode="HTML")
                return

            if pending:
                target = pending[0]
                if quick.command == "done":
                    done_rem = await repo.mark_completed(target.id, user.id)
                    if done_rem:
                        scheduler.cancel_reminder_job(done_rem.id)
                        reply_text = f"✅ {quick.reply_uz}\n\n{format_reminder_card(done_rem, user.timezone)}"
                        await message.answer(reply_text, parse_mode="HTML")
                        await _send_voice_reply_if_requested(message, quick.reply_uz, reply_with_voice, settings, cfg.voice_name, cfg.voice_rate)
                        return
                elif quick.command in {"snooze_later", "snooze_1h", "not_done"}:
                    delay_mins = 60 if quick.command == "snooze_1h" else max(5, cfg.retry_call_delay_minutes)
                    next_at = now_in_tz(user.timezone) + timedelta(minutes=delay_mins)
                    await repo.update_reminder(target.id, user.id, scheduled_at=next_at, awaiting_response=False)
                    scheduler.schedule_reminder(target.id, next_at, user.timezone)
                    reply_text = f"⏰ {quick.reply_uz}\n\n{format_reminder_card(target, user.timezone)}"
                    await message.answer(reply_text, parse_mode="HTML")
                    await _send_voice_reply_if_requested(message, quick.reply_uz, reply_with_voice, settings, cfg.voice_name, cfg.voice_rate)
                    return

    if not gemini.is_configured:
        await message.answer(
            "⚠️ AI buyruqlarini tushunish uchun <code>GEMINI_API_KEY</code> ni sozlang.",
            parse_mode="HTML",
        )
        return

    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(message.from_user.id)
        cfg = await repo.get_settings(user.id)
        pending = await repo.list_reminders(user.id, status="pending", limit=15)
        upcoming_summary = "\n".join(
            f"#{r.id}: {r.title} ({r.scheduled_at.isoformat()})" for r in pending
        ) or "Hozircha vazifalar yo‘q"

    try:
        action = await gemini.parse_user_command(
            user_text=user_text,
            tz_name=user.timezone,
            ai_style=cfg.ai_style,
            upcoming_summary=upcoming_summary,
        )
    except Exception as exc:
        logger.exception("Gemini buyruqni tahlil qilishda xatolik")
        await message.answer(f"⚠️ AI tahlil xatoligi: <code>{exc}</code>", parse_mode="HTML")
        return

    reply_text = action.reply_uz
    extra_markup = None

    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(message.from_user.id)
        cfg = await repo.get_settings(user.id)

        if action.intent == "create_reminder" and action.title:
            target_date = parse_user_date(action.date or "bugun", user.timezone) or now_in_tz(user.timezone).date()
            target_time = parse_user_time(action.time or "09:00") or parse_user_time("09:00")
            assert target_time is not None
            scheduled_dt = combine_local(target_date, target_time, user.timezone)
            method = action.delivery_method or cfg.default_reminder_mode

            rem = await repo.create_reminder(
                user_id=user.id,
                title=action.title,
                description=action.description or "",
                scheduled_at=scheduled_dt,
                recurrence_type=action.recurrence_type,
                recurrence_days=action.recurrence_days,
                delivery_method=method,
                is_voice=(method in {"voice", "call"}),
            )
            scheduler.schedule_reminder(rem.id, scheduled_dt, user.timezone)
            reply_text = f"{action.reply_uz}\n\n{format_reminder_card(rem, user.timezone)}"

        elif action.intent == "update_morning_call" and action.time:
            parsed_t = parse_user_time(action.time)
            if parsed_t:
                t_str = parsed_t.strftime("%H:%M")
                cfg = await repo.update_settings(
                    user.id, morning_call_time=t_str, morning_call_enabled=True
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

        elif action.intent == "update_evening_report" and action.time:
            parsed_t = parse_user_time(action.time)
            if parsed_t:
                t_str = parsed_t.strftime("%H:%M")
                cfg = await repo.update_settings(
                    user.id, evening_report_time=t_str, evening_report_enabled=True
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

        elif action.intent == "list_today_tasks":
            today = now_in_tz(user.timezone).date()
            todays = await repo.list_reminders_for_date(user.id, today, user.timezone)
            if not todays:
                reply_text = "Bugun uchun belgilangan vazifalar mavjud emas."
            else:
                cards = [format_reminder_card(r, user.timezone) for r in todays]
                reply_text = "📅 <b>Bugungi vazifalaringiz:</b>\n\n" + "\n\n".join(cards)

        elif action.intent == "request_delete_reminder":
            # NEVER delete without explicit user inline confirmation!
            target_date = parse_user_date(action.date, user.timezone) if action.date else None
            matches = await repo.find_matching_reminders(
                user_id=user.id,
                query_text=action.search_query,
                target_date=target_date,
                target_hour=action.target_hour,
                tz_name=user.timezone,
            )
            if not matches:
                reply_text = "O‘chirish uchun mos keladigan faol eslatma topilmadi."
            else:
                target = matches[0]
                pc = await repo.create_pending_confirmation(
                    user_id=user.id,
                    action_type="delete_reminder",
                    target_reminder_id=target.id,
                    payload={"title": target.title},
                )
                reply_text = (
                    f"⚠️ <b>Tasdiqlash kerak:</b>\n\n"
                    f"Quyidagi eslatmani o‘chirmoqchimisiz?\n"
                    f"{format_reminder_card(target, user.timezone)}"
                )
                extra_markup = confirm_delete_kb(pc.id)

        elif action.intent == "mark_completed":
            matches = await repo.find_matching_reminders(
                user_id=user.id,
                query_text=action.search_query,
                tz_name=user.timezone,
            )
            if matches:
                done_rem = await repo.mark_completed(matches[0].id, user.id)
                if done_rem:
                    scheduler.cancel_reminder_job(done_rem.id)
                    reply_text = f"✅ Vazifa bajarildi deb belgilandi:\n{format_reminder_card(done_rem, user.timezone)}"

    await message.answer(reply_text, reply_markup=extra_markup, parse_mode="HTML")

    if reply_with_voice and extra_markup is None:
        audio = None
        try:
            clean_spoken = reply_text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
            audio = await synthesize_uzbek_speech(
                text=clean_spoken[:500],
                output_dir=settings.audio_output_dir,
                voice_name=cfg.voice_name,
                voice_rate=cfg.voice_rate,
            )
            await message.answer_voice(FSInputFile(str(audio.ogg_path or audio.mp3_path)))
        except Exception as tts_exc:
            logger.debug("AI ovozli javob yuborilmadi: %s", tts_exc)
        finally:
            if audio:
                cleanup_audio_files(audio)
