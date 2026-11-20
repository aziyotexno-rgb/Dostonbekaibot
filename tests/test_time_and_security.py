"""Tests for timezone parsing, quiet hours, recurrence calculations, and secret masking."""

from __future__ import annotations

import logging
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from utils.logging_setup import SecretMaskingFilter
from utils.time_utils import (
    compute_next_occurrence,
    format_recurrence_uz,
    is_in_quiet_hours,
    next_allowed_after_quiet_hours,
    parse_quiet_range,
    parse_user_date,
    parse_user_time,
)


class TimeAndSecurityTests(unittest.TestCase):
    def test_parse_user_date_uzbek_keywords(self) -> None:
        today = parse_user_date("bugun", "Asia/Tashkent")
        tomorrow = parse_user_date("ertaga", "Asia/Tashkent")
        explicit = parse_user_date("25.11.2026", "Asia/Tashkent")

        self.assertIsNotNone(today)
        self.assertIsNotNone(tomorrow)
        self.assertEqual((tomorrow - today).days, 1)
        self.assertEqual(explicit.isoformat(), "2026-11-25")

    def test_parse_user_time(self) -> None:
        t1 = parse_user_time("08:30")
        t2 = parse_user_time("15.45")
        bad = parse_user_time("25:99")

        self.assertIsNotNone(t1)
        self.assertEqual((t1.hour, t1.minute), (8, 30))
        self.assertIsNotNone(t2)
        self.assertEqual((t2.hour, t2.minute), (15, 45))
        self.assertIsNone(bad)

    def test_quiet_hours_overnight_and_reschedule(self) -> None:
        self.assertEqual(parse_quiet_range("23:00-07:00"), ("23:00", "07:00"))
        self.assertEqual(parse_quiet_range("22.30 – 06.45"), ("22:30", "06:45"))
        self.assertIsNone(parse_quiet_range("notonggi"))

        tz = ZoneInfo("Asia/Tashkent")
        late_night = datetime(2026, 11, 20, 23, 30, tzinfo=tz)
        early_morning = datetime(2026, 11, 21, 5, 15, tzinfo=tz)
        daytime = datetime(2026, 11, 21, 14, 0, tzinfo=tz)

        self.assertTrue(is_in_quiet_hours(late_night, "23:00", "07:00", "Asia/Tashkent"))
        self.assertTrue(is_in_quiet_hours(early_morning, "23:00", "07:00", "Asia/Tashkent"))
        self.assertFalse(is_in_quiet_hours(daytime, "23:00", "07:00", "Asia/Tashkent"))

        shifted_late = next_allowed_after_quiet_hours(late_night, "23:00", "07:00", "Asia/Tashkent")
        self.assertEqual(shifted_late.strftime("%Y-%m-%d %H:%M"), "2026-11-21 07:01")

        shifted_early = next_allowed_after_quiet_hours(early_morning, "23:00", "07:00", "Asia/Tashkent")
        self.assertEqual(shifted_early.strftime("%Y-%m-%d %H:%M"), "2026-11-21 07:01")

        self.assertEqual(
            next_allowed_after_quiet_hours(daytime, "23:00", "07:00", "Asia/Tashkent"),
            daytime,
        )

    def test_compute_next_occurrence_all_modes(self) -> None:
        tz = ZoneInfo("Asia/Tashkent")
        base = datetime(2026, 11, 20, 8, 0, tzinfo=tz)  # Friday (weekday=4)
        ref = datetime(2026, 11, 20, 8, 5, tzinfo=tz)

        self.assertIsNone(compute_next_occurrence(base, "once", reference_now=ref))

        daily = compute_next_occurrence(base, "daily", reference_now=ref)
        self.assertEqual(daily.date().isoformat(), "2026-11-21")

        weekly = compute_next_occurrence(base, "weekly", reference_now=ref)
        self.assertEqual(weekly.date().isoformat(), "2026-11-27")

        monthly = compute_next_occurrence(base, "monthly", reference_now=ref)
        self.assertEqual(monthly.date().isoformat(), "2026-12-20")

        # Mon (0), Wed (2) -> next after Friday Nov 20 is Monday Nov 23
        custom = compute_next_occurrence(
            base, "custom_days", recurrence_days="0,2", reference_now=ref
        )
        self.assertIsNotNone(custom)
        self.assertEqual(custom.date().isoformat(), "2026-11-23")
        self.assertIn("Du", format_recurrence_uz("custom_days", "0,2"))

    def test_secret_masking_filter_redacts_tokens(self) -> None:
        secret_filter = SecretMaskingFilter(["super_secret_session_string_xyz"])
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Bot token 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg and session super_secret_session_string_xyz",
            args=(),
            exc_info=None,
        )
        secret_filter.filter(record)
        self.assertNotIn("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg", record.msg)
        self.assertNotIn("super_secret_session_string_xyz", record.msg)
        self.assertIn("[REDACTED_BOT_TOKEN]", record.msg)
        self.assertIn("[REDACTED]", record.msg)


if __name__ == "__main__":
    unittest.main()
