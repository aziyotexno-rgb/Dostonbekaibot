"""Tests for VoIP capability reporting, PCM audio helpers, and 6 Uzbek voice commands."""

from __future__ import annotations

import struct
import unittest
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from caller.voip_engine import inspect_voip_capabilities, pcm_has_speech, pcm_to_wav_bytes
from services.reminder_service import (
    build_interactive_reminder_prompt,
    build_morning_briefing_text,
    build_repeat_prompt,
)
from voice.commands import classify_call_voice_phrase


class VoIPAndVoiceTests(unittest.TestCase):
    def test_voip_capabilities_reports_missing_honestly(self) -> None:
        caps = inspect_voip_capabilities(api_id=0, api_hash="", session_string="")
        self.assertFalse(caps.supported)
        self.assertIn("TELEGRAM_API_ID", caps.missing_components)
        self.assertIn("TELEGRAM_SESSION_STRING", caps.missing_components)

    def test_pcm_speech_detection_and_wav_encoding(self) -> None:
        silence = b"\x00\x00" * 4800
        self.assertFalse(pcm_has_speech(silence))

        # 4800 samples of audible 16-bit amplitude (1500)
        loud_samples = struct.pack("<4800h", *([1500, -1500] * 2400))
        self.assertTrue(pcm_has_speech(loud_samples))

        wav_bytes = pcm_to_wav_bytes(loud_samples, sample_rate=48000, channels=1)
        self.assertTrue(wav_bytes.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav_bytes[:16])
        self.assertGreater(len(wav_bytes), len(loud_samples))

    def test_six_uzbek_voice_commands_classification(self) -> None:
        cases = [
            ("Ha, bajardim.", "done"),
            ("Hali bajarmadim, ozgina vaqt kerak.", "not_done"),
            ("Keyinroq eslat.", "snooze_later"),
            ("Bir soatdan keyin eslat.", "snooze_1h"),
            ("Eslatmani bekor qil.", "cancel_reminder"),
            ("Bugungi rejalarimni ayt.", "list_today"),
        ]
        for phrase, expected_cmd in cases:
            res = classify_call_voice_phrase(phrase)
            self.assertIsNotNone(res, f"Failed to match: {phrase}")
            self.assertEqual(res.command, expected_cmd)
            self.assertTrue(len(res.reply_uz) > 10)

        self.assertIsNone(classify_call_voice_phrase(""))

    def test_interactive_and_morning_uzbek_prompts(self) -> None:
        tz = ZoneInfo("Asia/Tashkent")
        fake_tasks = [
            SimpleNamespace(
                id=1,
                title="ilmiy tadqiqot ustida ishlash",
                scheduled_at=datetime(2026, 11, 20, 9, 0, tzinfo=tz),
                status="pending",
            ),
            SimpleNamespace(
                id=2,
                title="mijoz bilan uchrashish",
                scheduled_at=datetime(2026, 11, 20, 11, 0, tzinfo=tz),
                status="pending",
            ),
        ]
        script = build_morning_briefing_text("Dostonbek", fake_tasks, "Asia/Tashkent")
        self.assertIn("Assalomu alaykum, Dostonbek", script)
        self.assertIn("09:00 da ilmiy tadqiqot ustida ishlash", script)
        self.assertIn("11:00 da mijoz bilan uchrashish", script)

        interactive = build_interactive_reminder_prompt("Dostonbek", fake_tasks[1], "Asia/Tashkent")
        self.assertIn("Assalomu alaykum, Dostonbek", interactive)
        self.assertIn("11:00 da", interactive)
        self.assertIn("bajardingizmi", interactive)

        repeat = build_repeat_prompt("Dostonbek", fake_tasks[1])
        self.assertIn("mijoz bilan uchrashish", repeat)

    def test_morning_briefing_text_empty(self) -> None:
        script = build_morning_briefing_text("Dostonbek", [], "Asia/Tashkent")
        self.assertIn("mavjud emas", script)


if __name__ == "__main__":
    unittest.main()
