"""Centralized logging configuration with automatic secret masking."""

from __future__ import annotations

import logging
import re
from typing import Iterable


class SecretMaskingFilter(logging.Filter):
    """Redacts sensitive tokens, session strings, and passwords from logs."""

    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = [s for s in set(secrets) if s and len(s) >= 6]
        self._bot_token_re = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,50}\b")

    def _mask(self, text: str) -> str:
        masked = self._bot_token_re.sub("[REDACTED_BOT_TOKEN]", text)
        for secret in self._secrets:
            if secret in masked:
                masked = masked.replace(secret, "[REDACTED]")
        return masked

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._mask(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    self._mask(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: self._mask(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        return True


def configure_logging(level: str = "INFO", secrets: Iterable[str] = ()) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(SecretMaskingFilter(secrets))

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(numeric_level)
    root.addHandler(handler)

    # Reduce noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
