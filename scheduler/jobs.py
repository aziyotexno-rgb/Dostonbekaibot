"""Persistent APScheduler engine with quiet-hours guard, interactive calls, and idempotency."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from ai.gemini_client import GeminiSecretary
from caller.voip_engine import TelegramVoIPCaller
from config import Settings
from database.engine import DatabaseManager
from database.repository import BotRepository
from services.reminder_service import (
    build_interactive_reminder_prompt,
    build_morning_briefing_text,
    build_repeat_prompt,
)
from services.report_service import build_and_save_evening_report
from utils.time_utils import (
    compute_next_occurrence,
    get_zone,
    is_in_quiet_hours,
    next_allowed_after_quiet_hours,
    now_in_tz,
    to_tz,
)
from voice.tts import cleanup_audio_files, synthesize_uzbek_speech

logger = logging.getLogger("dostonbek.scheduler")


class BotScheduler:
    def __init__(
        self,
        bot: Bot,
        db: DatabaseManager,
        voip: TelegramVoIPCaller,
        gemini: GeminiSecretary,
        settings: Settings,
    ) -> None:
        self.bot = bot
        self.db = db
        self.voip = voip
        self.gemini = gemini
        self.settings = settings
        self.scheduler = AsyncIOScheduler(timezone=get_zone(settings.default_timezone))

    async def start(self) -> None:
        self.scheduler.start()
        await self.restore_all_jobs()

    async def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def restore_all_jobs(self) -> None:
        """Restore every pending reminder and daily morning/evening schedule from DB."""
        async with self.db.session() as sess:
            repo = BotRepository(sess)
            user = await repo.get_or_create_user(
                telegram_id=self.settings.allowed_telegram_id,
                default_timezone=self.settings.default_timezone,
                default_voice_name=self.settings.default_voice_name,
                default_voice_rate=self.settings.default_voice_rate,
            )
            bot_cfg = await repo.get_settings(user.id)
            pending = await repo.list_all_pending_reminders()

            now = now_in_tz(user.timezone)
            restored_count = 0
            for rem in pending:
                local_dt = to_tz(rem.scheduled_at, user.timezone)
                if local_dt <= now:
                    if rem.recurrence_type != "once":
                        next_dt = compute_next_occurrence(
                            local_dt,
                            rem.recurrence_type,
                            rem.recurrence_days,
                            tz_name=user.timezone,
                            reference_now=now,
                        )
                        if next_dt:
                            rem.scheduled_at = next_dt
                            self.schedule_reminder(rem.id, next_dt, user.timezone)
                            restored_count += 1
                    else:
                        catchup = now + timedelta(seconds=15)
                        self.schedule_reminder(rem.id, catchup, user.timezone)
                        restored_count += 1
                else:
                    self.schedule_reminder(rem.id, local_dt, user.timezone)
                    restored_count += 1

            self.sync_daily_jobs(
                user_id=user.id,
                telegram_id=user.telegram_id,
                tz_name=user.timezone,
                morning_time=bot_cfg.morning_call_time,
                morning_enabled=bot_cfg.morning_call_enabled,
                evening_time=bot_cfg.evening_report_time,
                evening_enabled=bot_cfg.evening_report_enabled,
            )

        logger.info(
            "Rejalashtiruvchi tiklandi: %d ta eslatma va kunlik jadvallar yuklandi.",
            restored_count,
        )

    def schedule_reminder(self, reminder_id: int, run_at: datetime, tz_name: str) -> None:
        job_id = f"reminder_{reminder_id}"
        local_dt = to_tz(run_at, tz_name)
        self.scheduler.add_job(
            self._execute_reminder,
            trigger=DateTrigger(run_date=local_dt),
            id=job_id,
            args=[reminder_id, "scheduler"],
            replace_existing=True,
            misfire_grace_time=300,
        )

    def cancel_reminder_job(self, reminder_id: int) -> None:
        job_id = f"reminder_{reminder_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    def sync_daily_jobs(
        self,
        user_id: int,
        telegram_id: int,
        tz_name: str,
        morning_time: str,
        morning_enabled: bool,
        evening_time: str,
        evening_enabled: bool,
    ) -> None:
        zone = get_zone(tz_name)

        morning_job_id = f"morning_call_{user_id}"
        if self.scheduler.get_job(morning_job_id):
            self.scheduler.remove_job(morning_job_id)
        if morning_enabled:
            h, m = map(int, morning_time.split(":"))
            self.scheduler.add_job(
                self._execute_morning_call,
                trigger=CronTrigger(hour=h, minute=m, timezone=zone),
                id=morning_job_id,
                args=[user_id, telegram_id, 1, "scheduler"],
                replace_existing=True,
            )

        evening_job_id = f"evening_report_{user_id}"
        if self.scheduler.get_job(evening_job_id):
            self.scheduler.remove_job(evening_job_id)
        if evening_enabled:
            eh, em = map(int, evening_time.split(":"))
            self.scheduler.add_job(
                self._execute_evening_report,
                trigger=CronTrigger(hour=eh, minute=em, timezone=zone),
                id=evening_job_id,
                args=[user_id, telegram_id, "scheduler"],
                replace_existing=True,
            )

    async def trigger_morning_call_now(
        self, user_id: int, telegram_id: int, attempt: int = 1
    ) -> str:
        return await self._execute_morning_call(
            user_id, telegram_id, attempt, source="manual", bypass_idempotency=True
        )

    async def run_due_reminder_from_cron(self, reminder_id: int) -> None:
        await self._execute_reminder(reminder_id, source="cron")

    async def run_morning_from_cron(self, user_id: int, telegram_id: int) -> str:
        return await self._execute_morning_call(user_id, telegram_id, 1, source="cron")

    async def run_evening_from_cron(self, user_id: int, telegram_id: int) -> None:
        await self._execute_evening_report(user_id, telegram_id, source="cron")

    async def _execute_reminder(self, reminder_id: int, source: str = "scheduler") -> None:
        async with self.db.session() as sess:
            repo = BotRepository(sess)
            rem = await repo.get_reminder(reminder_id)
            if rem is None or rem.status != "pending":
                return

            user = await repo.get_or_create_user(self.settings.allowed_telegram_id)
            cfg = await repo.get_settings(user.id)
            now = now_in_tz(user.timezone)

            # Respect quiet hours — never call during sleep window
            if cfg.quiet_hours_enabled and is_in_quiet_hours(
                now, cfg.quiet_hours_start, cfg.quiet_hours_end, user.timezone
            ):
                resumed = next_allowed_after_quiet_hours(
                    now, cfg.quiet_hours_start, cfg.quiet_hours_end, user.timezone
                )
                rem.scheduled_at = resumed
                self.schedule_reminder(rem.id, resumed, user.timezone)
                logger.info(
                    "Tinch vaqt (%s-%s): #%d eslatma %s ga ko'chirildi.",
                    cfg.quiet_hours_start,
                    cfg.quiet_hours_end,
                    rem.id,
                    resumed.strftime("%H:%M"),
                )
                return

            dispatch_key = f"rem:{rem.id}:{to_tz(rem.scheduled_at, user.timezone).strftime('%Y%m%d%H%M')}:att{rem.attempts_count + 1}"
            claimed = await repo.claim_dispatch_key(
                dispatch_key, dispatch_type="reminder", reminder_id=rem.id, source=source
            )
            if not claimed:
                logger.info("Idempotency: %s allaqachon bajarilgan, o'tkazildi.", dispatch_key)
                return

            rem.attempts_count += 1
            rem.last_triggered_at = now

            text_msg = (
                f"🔔 <b>Eslatma #{rem.id}</b>\n\n"
                f"📌 <b>{rem.title}</b>\n"
                + (f"📝 {rem.description}\n" if rem.description else "")
            )
            spoken_prompt = build_interactive_reminder_prompt(user.full_name, rem, user.timezone)
            repeat_prompt = build_repeat_prompt(user.full_name, rem)

            if rem.delivery_method == "call":
                outcome_status, detected_intent = await self._deliver_interactive_call_or_fallback(
                    repo=repo,
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                    user_name=user.full_name,
                    tz_name=user.timezone,
                    voice_name=cfg.voice_name,
                    voice_rate=cfg.voice_rate,
                    response_wait_seconds=cfg.response_wait_seconds,
                    spoken_text=spoken_prompt,
                    repeat_text=repeat_prompt,
                    purpose=f"eslatma_{rem.id}",
                    caption=text_msg,
                    attempt=rem.attempts_count,
                    reminder_id=rem.id,
                    task_title=rem.title,
                )

                # If user already resolved via spoken command in call, stop here
                refreshed = await repo.get_reminder(rem.id)
                if refreshed and refreshed.status in {"completed", "cancelled"}:
                    return

                # Check retry rules when unanswered / hung up / until_completed
                needs_followup = (
                    outcome_status in {"missed", "declined", "hung_up_unconfirmed", "no_response"}
                    or (rem.reminder_policy == "until_completed" and detected_intent != "done")
                )
                if (
                    needs_followup
                    and rem.reminder_policy != "once"
                    and cfg.retry_call_enabled
                    and rem.attempts_count < cfg.retry_call_max_attempts
                ):
                    retry_dt = now + timedelta(minutes=cfg.retry_call_delay_minutes)
                    if cfg.quiet_hours_enabled and is_in_quiet_hours(
                        retry_dt, cfg.quiet_hours_start, cfg.quiet_hours_end, user.timezone
                    ):
                        retry_dt = next_allowed_after_quiet_hours(
                            retry_dt, cfg.quiet_hours_start, cfg.quiet_hours_end, user.timezone
                        )
                    rem.scheduled_at = retry_dt
                    rem.awaiting_response = True
                    self.schedule_reminder(rem.id, retry_dt, user.timezone)
                    return

            elif rem.delivery_method == "voice" or rem.is_voice:
                await self._send_uzbek_voice_message(
                    telegram_id=user.telegram_id,
                    spoken_text=spoken_prompt,
                    voice_name=cfg.voice_name,
                    voice_rate=cfg.voice_rate,
                    caption=text_msg,
                )
            else:
                await self.bot.send_message(user.telegram_id, text_msg, parse_mode="HTML")

            # Advance recurring reminder or finalize once reminder
            if rem.recurrence_type == "once":
                if rem.reminder_policy != "until_completed":
                    rem.status = "completed"
                    rem.completed_at = now
                else:
                    rem.awaiting_response = True
            else:
                next_dt = compute_next_occurrence(
                    rem.scheduled_at,
                    rem.recurrence_type,
                    rem.recurrence_days,
                    tz_name=user.timezone,
                    reference_now=now,
                )
                if next_dt:
                    rem.scheduled_at = next_dt
                    rem.attempts_count = 0
                    self.schedule_reminder(rem.id, next_dt, user.timezone)

    async def _execute_morning_call(
        self,
        user_id: int,
        telegram_id: int,
        attempt: int = 1,
        source: str = "scheduler",
        bypass_idempotency: bool = False,
    ) -> str:
        async with self.db.session() as sess:
            repo = BotRepository(sess)
            user = await repo.get_or_create_user(telegram_id)
            cfg = await repo.get_settings(user.id)
            now = now_in_tz(user.timezone)

            if not bypass_idempotency:
                if cfg.quiet_hours_enabled and is_in_quiet_hours(
                    now, cfg.quiet_hours_start, cfg.quiet_hours_end, user.timezone
                ):
                    return "quiet_hours_skipped"

                key = f"morning:{user.id}:{now.date().isoformat()}:att{attempt}"
                if not await repo.claim_dispatch_key(key, "morning_call", source=source):
                    return "already_dispatched"

            today = now.date()
            todays_tasks = await repo.list_reminders_for_date(user.id, today, user.timezone)
            briefing = build_morning_briefing_text(user.full_name, todays_tasks, user.timezone)

            status, _ = await self._deliver_interactive_call_or_fallback(
                repo=repo,
                user_id=user.id,
                telegram_id=telegram_id,
                user_name=user.full_name,
                tz_name=user.timezone,
                voice_name=cfg.voice_name,
                voice_rate=cfg.voice_rate,
                response_wait_seconds=cfg.response_wait_seconds,
                spoken_text=briefing,
                repeat_text=None,
                purpose="ertalabki_reja",
                caption="☀️ <b>Ertalabki kunlik reja (ovozli xabar)</b>",
                attempt=attempt,
                reminder_id=None,
                task_title="Bugungi kunlik rejalar",
            )

            if (
                status in {"missed", "declined", "hung_up_unconfirmed", "no_response"}
                and cfg.retry_call_enabled
                and attempt < cfg.retry_call_max_attempts
            ):
                retry_at = now + timedelta(minutes=cfg.retry_call_delay_minutes)
                if not (
                    cfg.quiet_hours_enabled
                    and is_in_quiet_hours(
                        retry_at, cfg.quiet_hours_start, cfg.quiet_hours_end, user.timezone
                    )
                ):
                    self.scheduler.add_job(
                        self._execute_morning_call,
                        trigger=DateTrigger(run_date=retry_at),
                        id=f"retry_morning_{user_id}_{attempt + 1}",
                        args=[user_id, telegram_id, attempt + 1, "retry"],
                        replace_existing=True,
                    )
            return status

    async def _execute_evening_report(
        self, user_id: int, telegram_id: int, source: str = "scheduler"
    ) -> None:
        async with self.db.session() as sess:
            repo = BotRepository(sess)
            user = await repo.get_or_create_user(telegram_id)
            today = now_in_tz(user.timezone).date()
            key = f"evening:{user.id}:{today.isoformat()}"
            if not await repo.claim_dispatch_key(key, "evening_report", source=source):
                return
            summary = await build_and_save_evening_report(
                repo, user.id, user.full_name, user.timezone
            )
            await self.bot.send_message(telegram_id, summary, parse_mode="HTML")

    async def _send_uzbek_voice_message(
        self,
        telegram_id: int,
        spoken_text: str,
        voice_name: str,
        voice_rate: str,
        caption: str,
    ) -> None:
        audio = None
        try:
            audio = await synthesize_uzbek_speech(
                text=spoken_text,
                output_dir=self.settings.audio_output_dir,
                voice_name=voice_name,
                voice_rate=voice_rate,
                for_voip_pcm=False,
            )
            target_file = audio.ogg_path or audio.mp3_path
            await self.bot.send_voice(
                chat_id=telegram_id,
                voice=FSInputFile(str(target_file)),
                caption=caption[:1000],
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("Ovozli xabar yuborishda xatolik: %s", exc)
            await self.bot.send_message(
                telegram_id,
                f"{caption}\n\n🗣 <i>{html.escape(spoken_text)}</i>",
                parse_mode="HTML",
            )
        finally:
            if audio:
                cleanup_audio_files(audio)

    async def _deliver_interactive_call_or_fallback(
        self,
        repo: BotRepository,
        user_id: int,
        telegram_id: int,
        user_name: str,
        tz_name: str,
        voice_name: str,
        voice_rate: str,
        response_wait_seconds: int,
        spoken_text: str,
        repeat_text: Optional[str],
        purpose: str,
        caption: str,
        attempt: int,
        reminder_id: Optional[int],
        task_title: str,
    ) -> tuple[str, Optional[str]]:
        audio = None
        repeat_audio = None
        reply_audios = []
        try:
            audio = await synthesize_uzbek_speech(
                text=spoken_text,
                output_dir=self.settings.audio_output_dir,
                voice_name=voice_name,
                voice_rate=voice_rate,
                for_voip_pcm=True,
            )
            if repeat_text:
                repeat_audio = await synthesize_uzbek_speech(
                    text=repeat_text,
                    output_dir=self.settings.audio_output_dir,
                    voice_name=voice_name,
                    voice_rate=voice_rate,
                    for_voip_pcm=True,
                )

            async def _transcribe_wav(wav_bytes: bytes) -> str:
                if not self.gemini.is_configured:
                    return ""
                return await self.gemini.transcribe_uzbek_audio(wav_bytes, mime_type="audio/wav")

            async def _handle_voice_reply(
                transcript: str,
            ) -> tuple[str, Optional[Path], float]:
                action = await self.gemini.parse_call_voice_reply(transcript, task_title)
                reply_text = action.reply_uz
                now_local = now_in_tz(tz_name)

                if reminder_id is not None:
                    if action.command == "done":
                        await repo.mark_completed(reminder_id, user_id, response_text=transcript)
                        self.cancel_reminder_job(reminder_id)
                    elif action.command == "cancel_reminder":
                        await repo.mark_cancelled(reminder_id, user_id, response_text=transcript)
                        self.cancel_reminder_job(reminder_id)
                    elif action.command == "snooze_later":
                        snooze_dt = now_local + timedelta(minutes=15)
                        await repo.update_reminder(
                            reminder_id, user_id, scheduled_at=snooze_dt, last_response_text=transcript
                        )
                        self.schedule_reminder(reminder_id, snooze_dt, tz_name)
                    elif action.command == "snooze_1h":
                        snooze_dt = now_local + timedelta(hours=1)
                        await repo.update_reminder(
                            reminder_id, user_id, scheduled_at=snooze_dt, last_response_text=transcript
                        )
                        self.schedule_reminder(reminder_id, snooze_dt, tz_name)
                    elif action.command == "not_done":
                        await repo.update_reminder(
                            reminder_id, user_id, awaiting_response=True, last_response_text=transcript
                        )

                if action.command == "list_today":
                    todays = await repo.list_reminders_for_date(user_id, now_local.date(), tz_name)
                    reply_text = build_morning_briefing_text(user_name, todays, tz_name)

                reply_audio = await synthesize_uzbek_speech(
                    text=reply_text,
                    output_dir=self.settings.audio_output_dir,
                    voice_name=voice_name,
                    voice_rate=voice_rate,
                    for_voip_pcm=True,
                )
                reply_audios.append(reply_audio)
                return action.command, reply_audio.pcm_path, reply_audio.duration_seconds

            outcome = await self.voip.place_interactive_call(
                greeting_pcm_path=audio.pcm_path,
                greeting_duration_seconds=audio.duration_seconds,
                repeat_pcm_path=repeat_audio.pcm_path if repeat_audio else None,
                repeat_duration_seconds=repeat_audio.duration_seconds if repeat_audio else 0.0,
                response_wait_seconds=response_wait_seconds,
                target_username=self.settings.callee_username,
                transcribe_fn=_transcribe_wav,
                handle_reply_fn=_handle_voice_reply,
            )

            await repo.log_call(
                user_id=user_id,
                caller_username=self.settings.caller_username,
                callee_username=self.settings.callee_username,
                purpose=purpose,
                status=outcome.status,
                duration_seconds=outcome.duration_seconds,
                transcript_text=spoken_text,
                error_detail=outcome.error_detail,
                attempt_number=attempt,
                reminder_id=reminder_id,
                user_voice_reply=outcome.user_transcript,
                detected_intent=outcome.detected_intent,
            )

            status_uz = {
                "completed": "Muvaffaqiyatli yakunlandi",
                "answered": "Javob berildi",
                "no_response": "Javob berilmadi",
                "hung_up_unconfirmed": "Qo‘ng‘iroq qizil tugma bilan tugatildi (vazifa tasdiqlanmadi)",
                "declined": "Qo‘ng‘iroq rad etildi",
                "missed": "Javob berilmadi",
                "unavailable": "VoIP qo‘ng‘iroq muhiti tayyor emas",
                "failed": "Xatolik yuz berdi",
            }
            human_status = status_uz.get(outcome.status, outcome.status)

            if outcome.status in {"unavailable", "failed"}:
                reason_text = html.escape(outcome.error_detail or human_status)
                fallback_caption = (
                    f"{caption}\n\n"
                    f"📞 1:1 qo‘ng‘iroq holati: <b>{human_status}</b>\n"
                    f"ℹ️ Sabab: <code>{reason_text}</code>\n"
                    f"🎙 Shuning uchun sizga ovozli xabar yuborildi (bu haqiqiy qo‘ng‘iroq o‘rnini bosuvchi zaxira bildirishnoma)."
                )
                target_file = audio.ogg_path or audio.mp3_path
                await self.bot.send_voice(
                    chat_id=telegram_id,
                    voice=FSInputFile(str(target_file)),
                    caption=fallback_caption[:1000],
                    parse_mode="HTML",
                )
            else:
                reply_line = (
                    f"\n🗣 Sizning javobingiz: <i>{html.escape(outcome.user_transcript)}</i>"
                    if outcome.user_transcript
                    else ""
                )
                await self.bot.send_message(
                    telegram_id,
                    f"📞 <b>Qo‘ng‘iroq hisoboti</b> ({self.settings.caller_username} → {self.settings.callee_username})\n"
                    f"• Holat: <b>{human_status}</b>\n"
                    f"• Davomiyligi: <b>{outcome.duration_seconds} soniya</b>{reply_line}",
                    parse_mode="HTML",
                )
            return outcome.status, outcome.detected_intent
        except Exception as exc:
            logger.exception("Qo'ng'iroq yetkazishda xatolik")
            await repo.log_call(
                user_id=user_id,
                caller_username=self.settings.caller_username,
                callee_username=self.settings.callee_username,
                purpose=purpose,
                status="failed",
                duration_seconds=0,
                transcript_text=spoken_text,
                error_detail=str(exc),
                attempt_number=attempt,
                reminder_id=reminder_id,
            )
            await self.bot.send_message(
                telegram_id,
                f"{caption}\n\n⚠️ Qo‘ng‘iroq bajarilmadi: <code>{html.escape(str(exc))}</code>",
                parse_mode="HTML",
            )
            return "failed", None
        finally:
            if audio:
                cleanup_audio_files(audio)
            if repeat_audio:
                cleanup_audio_files(repeat_audio)
            for ra in reply_audios:
                cleanup_audio_files(ra)
