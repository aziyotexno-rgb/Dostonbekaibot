"""Entry point for Dostonbek AI Bot (Worker + Scheduler + MTProto VoIP)."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from bot.app import run_bot
from config import get_settings
from utils.logging_setup import configure_logging


async def _main() -> None:
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        secrets=settings.get_sensitive_values(),
    )
    logger = logging.getLogger("dostonbek.main")
    settings.validate_for_runtime()

    logger.info(
        "Dostonbek AI Bot ishga tushirilmoqda (timezone=%s, caller=%s, callee=%s)",
        settings.default_timezone,
        settings.caller_username,
        settings.callee_username,
    )
    await run_bot(settings)


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nBot foydalanuvchi tomonidan to'xtatildi.")
    except Exception as exc:
        logging.getLogger("dostonbek.main").critical(
            "Bot ishga tushishida jiddiy xatolik: %s", exc, exc_info=True
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
