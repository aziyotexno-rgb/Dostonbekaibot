"""Aiogram 3 Dispatcher assembly, Render Web Service / Polling lifecycle."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from ai.gemini_client import GeminiSecretary
from caller.voip_engine import TelegramVoIPCaller
from config import Settings
from database.engine import DatabaseManager
from handlers import ai_assistant, calls, reminders, settings as settings_handler, start, stats
from handlers.auth_middleware import AllowedUserMiddleware
from scheduler.jobs import BotScheduler
from web.health import start_web_server

logger = logging.getLogger("dostonbek.bot")


async def run_bot(cfg: Settings) -> None:
    db = DatabaseManager(cfg.database_url)
    await db.init_db()

    bot = Bot(
        token=cfg.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    auth_mw = AllowedUserMiddleware(cfg.allowed_telegram_id)
    dp.message.middleware(auth_mw)
    dp.callback_query.middleware(auth_mw)

    gemini = GeminiSecretary(api_key=cfg.gemini_api_key, model_name=cfg.gemini_model)
    voip = TelegramVoIPCaller(
        api_id=cfg.telegram_api_id,
        api_hash=cfg.telegram_api_hash,
        session_string=cfg.telegram_session_string,
        caller_username=cfg.caller_username,
        callee_username=cfg.callee_username,
    )
    scheduler = BotScheduler(
        bot=bot, db=db, voip=voip, gemini=gemini, settings=cfg
    )

    dp["db"] = db
    dp["gemini"] = gemini
    dp["voip"] = voip
    dp["scheduler"] = scheduler
    dp["settings"] = cfg

    dp.include_router(start.router)
    dp.include_router(reminders.router)
    dp.include_router(calls.router)
    dp.include_router(settings_handler.router)
    dp.include_router(stats.router)
    dp.include_router(ai_assistant.router)

    await scheduler.start()

    caps = voip.get_capabilities()
    logger.info("VoIP holati: %s", caps.note)

    use_webhook = bool(cfg.use_webhook and cfg.webhook_base_url)
    web_runner = None
    if cfg.enable_health_server or use_webhook:
        web_runner = await start_web_server(
            port=cfg.port,
            db=db,
            voip=voip,
            bot=bot,
            dp=dp,
            use_webhook=use_webhook,
            webhook_secret=cfg.webhook_secret,
            scheduler_running_fn=lambda: scheduler.scheduler.running,
        )

    try:
        if use_webhook:
            base = cfg.webhook_base_url.rstrip("/")
            target_url = f"{base}/webhook/{cfg.webhook_secret}"
            await bot.set_webhook(
                url=target_url,
                secret_token=cfg.webhook_secret,
                drop_pending_updates=True,
            )
            logger.info("Bot Webhook rejimida ishga tushdi: %s", base)
            stop_event = asyncio.Event()
            await stop_event.wait()
        else:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Bot Polling rejimida ishga tushdi (/health faol).")
            await dp.start_polling(bot)
    finally:
        await scheduler.shutdown()
        await voip.stop()
        if web_runner:
            await web_runner.cleanup()
        await bot.session.close()
        await db.dispose()
