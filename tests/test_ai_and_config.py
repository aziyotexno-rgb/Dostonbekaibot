"""Optional integration tests for SQLAlchemy migrations, idempotency, PRO trial, and AI schemas.

These tests automatically execute in full when project dependencies from requirements.txt
are installed (e.g., locally or in CI/Render), and gracefully skip if a third-party package
is not present in a minimal Python runtime.
"""

from __future__ import annotations

import asyncio
import importlib.util
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo


HAS_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None and importlib.util.find_spec("aiosqlite") is not None
HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_AIOGRAM = importlib.util.find_spec("aiogram") is not None


class DatabaseAndIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(HAS_SQLALCHEMY, "sqlalchemy + aiosqlite not installed in minimal env")
    def test_database_crud_idempotency_and_pro_trial(self) -> None:
        from database.engine import DatabaseManager
        from database.repository import BotRepository

        async def _run() -> None:
            db = DatabaseManager("sqlite+aiosqlite:///:memory:")
            await db.init_db()
            try:
                async with db.session() as sess:
                    repo = BotRepository(sess)
                    user = await repo.get_or_create_user(
                        telegram_id=999000111,
                        username="D_admin_aka",
                        full_name="Dostonbek",
                    )
                    tz = ZoneInfo("Asia/Tashkent")
                    rem = await repo.create_reminder(
                        user_id=user.id,
                        title="Bahodirga qo'ng'iroq qilish",
                        scheduled_at=datetime(2026, 11, 20, 15, 0, tzinfo=tz),
                        recurrence_type="once",
                        delivery_method="call",
                        reminder_policy="until_completed",
                    )
                    self.assertEqual(rem.status, "pending")
                    self.assertEqual(rem.reminder_policy, "until_completed")

                    # Idempotency ledger check (Web Service + Cron Job dedup)
                    first_claim = await repo.claim_dispatch_key(
                        f"reminder:{rem.id}:attempt:1", "reminder_due", rem.id
                    )
                    second_claim = await repo.claim_dispatch_key(
                        f"reminder:{rem.id}:attempt:1", "reminder_due", rem.id
                    )
                    self.assertTrue(first_claim)
                    self.assertFalse(second_claim)

                    # Admin-only PRO trial activation & cancellation
                    cfg = await repo.activate_pro_trial(user.id, days=7)
                    self.assertTrue(repo.is_pro_effective(cfg))
                    cfg = await repo.cancel_pro_trial(user.id)
                    self.assertFalse(repo.is_pro_effective(cfg))

                    # Delete confirmation token flow
                    pc = await repo.create_pending_confirmation(
                        user_id=user.id,
                        action_type="delete_reminder",
                        target_reminder_id=rem.id,
                        payload={"title": rem.title},
                    )
                    loaded_pc = await repo.get_pending_confirmation(pc.id, user.id)
                    self.assertIsNotNone(loaded_pc)
                    self.assertEqual(loaded_pc.target_reminder_id, rem.id)

                    done = await repo.mark_completed(rem.id, user.id)
                    self.assertEqual(done.status, "completed")
            finally:
                await db.dispose()

        asyncio.run(_run())

    @unittest.skipUnless(HAS_PYDANTIC, "pydantic not installed in minimal env")
    def test_ai_command_and_call_voice_schemas(self) -> None:
        from ai.prompts import (
            AICommandAction,
            CallVoiceReplyAction,
            build_secretary_system_prompt,
        )

        prompt = build_secretary_system_prompt(
            today_iso="2026-11-20",
            now_time="08:00",
            tz_name="Asia/Tashkent",
            ai_style="friendly",
            upcoming_summary="Yo'q",
        )
        self.assertIn("Asia/Tashkent", prompt)
        self.assertIn("request_delete_reminder", prompt)

        parsed = AICommandAction.model_validate(
            {
                "intent": "create_reminder",
                "title": "Bahodirga qo'ng'iroq qilish",
                "date": "2026-11-20",
                "time": "15:00",
                "recurrence_type": "once",
                "delivery_method": "call",
                "reply_uz": "Albatta, bugun soat 15:00 ga eslatma qo'shdim.",
            }
        )
        self.assertEqual(parsed.intent, "create_reminder")
        self.assertEqual(parsed.time, "15:00")

        call_reply = CallVoiceReplyAction.model_validate(
            {
                "command": "snooze_1h",
                "reply_uz": "Kelishdik, bir soatdan keyin qayta eslataman.",
            }
        )
        self.assertEqual(call_reply.command, "snooze_1h")

    @unittest.skipUnless(HAS_AIOGRAM, "aiogram not installed in minimal env")
    def test_allowed_user_whitelist(self) -> None:
        from handlers.auth_middleware import is_authorized_user

        self.assertTrue(is_authorized_user(123456789, 123456789))
        self.assertFalse(is_authorized_user(987654321, 123456789))
        self.assertFalse(is_authorized_user(None, 123456789))


if __name__ == "__main__":
    unittest.main()
