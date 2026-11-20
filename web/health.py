"""Render Web Service HTTP server: /health diagnostics + optional Aiogram webhook endpoint."""

from __future__ import annotations

import logging
from typing import Any, Optional

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from caller.voip_engine import TelegramVoIPCaller
from database.engine import DatabaseManager

logger = logging.getLogger("dostonbek.web.health")


async def start_web_server(
    port: int,
    db: DatabaseManager,
    voip: TelegramVoIPCaller,
    bot: Optional[Bot] = None,
    dp: Optional[Dispatcher] = None,
    use_webhook: bool = False,
    webhook_secret: str = "dostonbek-webhook-secret",
    scheduler_running_fn: Any = None,
) -> web.AppRunner:
    app = web.Application()

    async def _health_handler(_request: web.Request) -> web.Response:
        db_ok = await db.ping()
        caps = voip.get_capabilities()
        sched_ok = bool(scheduler_running_fn()) if callable(scheduler_running_fn) else True
        payload = {
            "holat": "ishlayapti" if db_ok else "xatolik",
            "xizmat": "Dostonbek AI Bot",
            "rejim": "webhook" if use_webhook else "polling",
            "malumotlar_bazasi": "ulangan" if db_ok else "ulanmagan",
            "rejalashtiruvchi": "faol" if sched_ok else "to'xtatilgan",
            "voip_tayyor": caps.supported,
            "voip_izoh": caps.note,
        }
        status_code = 200 if db_ok else 503
        return web.json_response(payload, status=status_code)

    app.router.add_get("/health", _health_handler)
    app.router.add_get("/", _health_handler)

    if use_webhook and bot is not None and dp is not None:
        webhook_path = f"/webhook/{webhook_secret}"
        handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=webhook_secret)
        handler.register(app, path=webhook_path)
        setup_application(app, dp, bot=bot)
        logger.info("Webhook marshruti ro'yxatdan o'tkazildi: %s", webhook_path)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Render Web Service HTTP serveri 0.0.0.0:%d portida ishga tushdi", port)
    return runner
