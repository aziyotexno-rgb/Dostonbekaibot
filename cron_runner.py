"""Standalone Cron Job entry point for Render Cron Services.

Checks and executes:
1. Due reminders and unanswered follow-up reminders.
2. Recurring tasks due at or before the current window.
3. Morning briefing call (when within scheduled morning window).
4. Evening daily report (when within scheduled evening window).

Uses PostgreSQL `notification_dispatches` idempotency keys so running alongside
a Render Web Service never sends duplicate notifications.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ai.gemini_client import GeminiSecretary
from caller.voip_engine import TelegramVoIPCaller
from config import get_settings
from database.engine import DatabaseManager
from database.repository import BotRepository
from scheduler.jobs import BotScheduler
from utils.logging_setup import configure_logging
from utils.time_utils import now_in_tz, parse_user_time


async def run_cron_cycle() -> None:
    cfg = get_settings()
    configure_logging(level=cfg.log_level, secrets=cfg.get_sensitive_values())
    logger = logging.getLogger("dostonbek.cron")
    cfg.validate_for_runtime()

    db = DatabaseManager(cfg.database_url)
    await db.init_db()

    bot = Bot(
        token=cfg.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    gemini = GeminiSecretary(api_key=cfg.gemini_api_key, model_name=cfg.gemini_model)
    voip = TelegramVoIPCaller(
        api_id=cfg.telegram_api_id,
        api_hash=cfg.telegram_api_hash,
        session_string=cfg.telegram_session_string,
        caller_username=cfg.caller_username,
        callee_username=cfg.callee_username,
    )
    scheduler = BotScheduler(bot=bot, db=db, voip=voip, settings=cfg)

    try:
        async with db.session() as sess:
            repo = BotRepository(sess)
            user = await repo.get_or_create_user(
                telegram_id=cfg.allowed_telegram_id,
                default_timezone=cfg.default_timezone,
                default_voice_name=cfg.default_voice_name,
                default_voice_rate=cfg.default_voice_rate,
            )
            bot_cfg = await repo.get_settings(user.id)
            now = now_in_tz(user.timezone)
            due_reminders = await repo.list_due_pending_reminders(now)

            morning_t = parse_user_time(bot_cfg.morning_call_time)
            evening_t = parse_user_time(bot_cfg.evening_report_time)
            should_morning = (
                bot_cfg.morning_call_enabled
                and morning_t is not None
                and now.hour == morning_t.hour
                and abs(now.minute - morning_t.minute) <= 10
            )
            should_evening = (
                bot_cfg.evening_report_enabled
                and evening_t is not None
                and now.hour == evening_t.hour
                and abs(now.minute - evening_t.minute) <= 10
            )
            due_ids = [r.id for r in due_reminders]
            user_id = user.id
            tg_id = user.telegram_id

        logger.info("Cron tekshiruvi: %d ta muddati kelgan eslatma topildi.", len(due_ids))
        for rid in due_ids:
            await scheduler.run_due_reminder_from_cron(rid)

        if should_morning:
            await scheduler.run_morning_from_cron(user_id, tg_id)
        if should_evening:
            await scheduler.run_evening_from_cron(user_id, tg_id)

        logger.info("Cron sikli muvaffaqiyatli yakunlandi.")
    finally:
        await voip.stop()
        await bot.session.close()
        await db.dispose()


def main() -> None:
    try:
        asyncio.run(run_cron_cycle())
    except Exception as exc:
        logging.getLogger("dostonbek.cron").critical(
            "Cron job xatoligi: %s", exc, exc_info=True
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
