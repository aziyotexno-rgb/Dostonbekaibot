"""Pure-Python Uzbek voice & chat command classifier (zero third-party dependencies)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VoiceCommandResult:
    command: str  # done | not_done | snooze_later | snooze_1h | cancel_reminder | list_today
    reply_uz: str


def classify_call_voice_phrase(transcript: str) -> Optional[VoiceCommandResult]:
    """Deterministic Uzbek phrase matcher for the 6 supported voice commands."""
    text = (transcript or "").strip().lower()
    if not text:
        return None

    # 1. Eslatmani bekor qil
    if any(p in text for p in ("bekor qil", "o'chir", "o‘chir", "ochir", "kerak emas", "to'xtat", "to‘xtat")):
        return VoiceCommandResult(
            command="cancel_reminder",
            reply_uz="Tushunarli, ushbu eslatma bekor qilindi. Yana yordam kerak bo‘lsa xabar bering!",
        )

    # 2. Bugungi rejalarimni ayt
    if any(p in text for p in ("bugungi reja", "bugungi ish", "rejalarimni ayt", "nima ishlar")):
        return VoiceCommandResult(
            command="list_today",
            reply_uz="Xo‘p bo‘ladi, hozir bugungi rejalaringizni o‘qib beraman.",
        )

    # 3. Bir soatdan keyin eslat
    if any(p in text for p in ("bir soat", "1 soat", "soatdan keyin")):
        return VoiceCommandResult(
            command="snooze_1h",
            reply_uz="Kelishdik, bir soatdan keyin qayta eslataman.",
        )

    # 4. Keyinroq eslat
    if any(p in text for p in ("keyinroq", "birozdan keyin", "sal turib", "keyin eslat")):
        return VoiceCommandResult(
            command="snooze_later",
            reply_uz="Xo‘p bo‘ladi, birozdan keyin yana eslataman.",
        )

    # 5. Hali bajarmadim
    if any(p in text for p in ("hali bajarmadim", "bajarmadim", "qilmadim", "ulgurmadim", "yo'q", "yo‘q")):
        return VoiceCommandResult(
            command="not_done",
            reply_uz="Tushunarli, vazifa bajarilmaguncha belgilangan oraliqda eslatib turaman.",
        )

    # 6. Ha, bajardim
    if any(
        p in text
        for p in (
            "bajardim",
            "ha, bajardim",
            "tugatdim",
            "qildim",
            "ha, esladim",
            "esladim",
            "bo'ldi",
            "bo‘ldi",
            "bajarildi",
        )
    ):
        return VoiceCommandResult(
            command="done",
            reply_uz="Yaxshi, barakalla! Vazifa bajarildi deb belgilandi, ishingizga omad!",
        )

    return None
