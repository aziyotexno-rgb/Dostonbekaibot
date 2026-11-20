"""Idempotent schema migration runner supporting PostgreSQL and SQLite."""

from __future__ import annotations

import logging
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger("dostonbek.db.migrations")

# Additive column migrations applied safely after Base.metadata.create_all
COLUMN_MIGRATIONS: list[tuple[str, str, str, str]] = [
    ("002_bot_settings_response_wait", "bot_settings", "response_wait_seconds", "INTEGER DEFAULT 15"),
    ("002_bot_settings_quiet_enabled", "bot_settings", "quiet_hours_enabled", "BOOLEAN DEFAULT TRUE"),
    ("002_bot_settings_quiet_start", "bot_settings", "quiet_hours_start", "VARCHAR(5) DEFAULT '23:00'"),
    ("002_bot_settings_quiet_end", "bot_settings", "quiet_hours_end", "VARCHAR(5) DEFAULT '07:00'"),
    ("002_bot_settings_pro_active", "bot_settings", "pro_trial_active", "BOOLEAN DEFAULT FALSE"),
    ("002_bot_settings_pro_expires", "bot_settings", "pro_trial_expires_at", "TIMESTAMP WITH TIME ZONE"),
    ("002_reminders_policy", "reminders", "reminder_policy", "VARCHAR(32) DEFAULT 'until_completed'"),
    ("002_reminders_attempts", "reminders", "attempts_count", "INTEGER DEFAULT 0"),
    ("002_reminders_last_reply", "reminders", "last_response_text", "TEXT"),
    ("002_reminders_awaiting", "reminders", "awaiting_response", "BOOLEAN DEFAULT FALSE"),
    ("002_call_logs_reminder_id", "call_logs", "reminder_id", "INTEGER"),
    ("002_call_logs_voice_reply", "call_logs", "user_voice_reply", "TEXT"),
    ("002_call_logs_intent", "call_logs", "detected_intent", "VARCHAR(48)"),
]


async def _sqlite_columns(conn: AsyncConnection, table: str) -> set[str]:
    res = await conn.execute(text(f"PRAGMA table_info({table})"))
    return {row[1] for row in res.fetchall()}


async def _pg_column_exists(conn: AsyncConnection, table: str, column: str) -> bool:
    res = await conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :tbl AND column_name = :col"
        ),
        {"tbl": table, "col": column},
    )
    return res.first() is not None


async def apply_schema_migrations(conn: AsyncConnection) -> list[str]:
    """Ensure all additive columns and migration history rows exist."""
    dialect = conn.dialect.name
    applied: list[str] = []

    res = await conn.execute(text("SELECT version FROM schema_migrations"))
    existing_versions: set[str] = {row[0] for row in res.fetchall()}

    sqlite_cache: dict[str, set[str]] = {}

    for version, table, column, col_def in COLUMN_MIGRATIONS:
        if version in existing_versions:
            continue

        if dialect == "sqlite":
            if table not in sqlite_cache:
                sqlite_cache[table] = await _sqlite_columns(conn, table)
            if column not in sqlite_cache[table]:
                sqlite_type = col_def.replace("TIMESTAMP WITH TIME ZONE", "DATETIME")
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sqlite_type}"))
                sqlite_cache[table].add(column)
        else:
            if not await _pg_column_exists(conn, table, column):
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_def}")
                )

        await conn.execute(
            text(
                "INSERT INTO schema_migrations (version, description) "
                "VALUES (:ver, :desc)"
            ),
            {"ver": version, "desc": f"{table}.{column}"},
        )
        applied.append(version)

    if applied:
        logger.info("Qo'llangan DB migratsiyalar: %s", ", ".join(applied))
    return applied
