"""Reminder formatting, interactive Uzbek call scripts, and evening briefings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.time_utils import format_uz_datetime, to_tz

if TYPE_CHECKING:
    from database.models import Reminder

UZBEK_ORDINALS = [
    "Birinchi",
    "Ikkinchi",
    "Uchinchi",
    "To'rtinchi",
    "Beshinchi",
    "Oltinchi",
    "Yettinchi",
    "Sakkizinchi",
    "To'qqizinchi",
    "O'ninchi",
]


def build_morning_briefing_text(
    user_name: str,
    reminders: list[Reminder],
    tz_name: str = "Asia/Tashkent",
) -> str:
    """Build natural, respectful Uzbek spoken briefing for morning VoIP call."""
    pending = [r for r in reminders if r.status == "pending"]
    if not pending:
        return (
            f"Assalomu alaykum, {user_name}! Xayrli tong. "
            "Bugun uchun belgilangan vazifalar hozircha mavjud emas. "
            "Yangi reja qo'shish uchun menga yozing. Kuningiz xayrli va samarali o'tsin!"
        )

    count = len(pending)
    lines = [
        f"Assalomu alaykum, {user_name}! Xayrli tong. "
        f"Bugun sizni {count} ta muhim vazifa kutmoqda."
    ]
    for idx, rem in enumerate(pending[:10]):
        local_dt = to_tz(rem.scheduled_at, tz_name)
        ordinal = UZBEK_ORDINALS[idx] if idx < len(UZBEK_ORDINALS) else f"{idx + 1}-"
        time_str = local_dt.strftime("%H:%M")
        lines.append(f"{ordinal} vazifangiz soat {time_str} da {rem.title}.")

    lines.append(
        "Vazifalarni bajarganingizni aytishingiz yoki bugungi rejalarni qayta eshitishni so'rashingiz mumkin."
    )
    return " ".join(lines)


def build_interactive_reminder_prompt(
    user_name: str,
    rem: Reminder,
    tz_name: str = "Asia/Tashkent",
) -> str:
    """Natural Uzbek greeting + question waiting for user's spoken confirmation."""
    local_dt = to_tz(rem.scheduled_at, tz_name)
    time_str = local_dt.strftime("%H:%M")
    return (
        f"Assalomu alaykum, {user_name}! Bugun soat {time_str} da muhim vazifangiz bor: "
        f"{rem.title}. "
        "Shu vazifani bajardingizmi yoki keyinroq yana eslatishimni xohlaysizmi?"
    )


def build_repeat_prompt(user_name: str, rem: Reminder) -> str:
    return (
        f"Kechirasiz, {user_name}, javobingiz eshitilmadi. "
        f"Eslatib o'taman: {rem.title}. "
        "Bajardingizmi yoki keyinroq eslataymi?"
    )


def format_reminder_card(rem: Reminder, tz_name: str = "Asia/Tashkent") -> str:
    status_labels = {
        "completed": "✅ Bajarildi",
        "cancelled": "🚫 Bekor qilindi",
        "pending": "⏳ Kutilmoqda",
    }
    method_labels = {
        "text": "Matnli",
        "voice": "Ovozli",
        "call": "Qo‘ng‘iroq",
    }
    policy_labels = {
        "once": "Bir marta",
        "wait_response": "Javob kutish",
        "retry_no_answer": "Javobsizda qayta qo‘ng‘iroq",
        "until_completed": "Bajarilmaguncha eslatish",
    }
    status_text = status_labels.get(rem.status, rem.status)
    method_label = method_labels.get(rem.delivery_method, rem.delivery_method)
    policy_label = policy_labels.get(getattr(rem, "reminder_policy", "until_completed"), "")
    dt_str = format_uz_datetime(rem.scheduled_at, tz_name)
    desc = f"\n   📝 {rem.description}" if rem.description else ""
    policy_line = f" · 🔁 {policy_label}" if policy_label else ""
    return (
        f"{status_text} · <b>#{rem.id} — {rem.title}</b>\n"
        f"   🕒 {dt_str} · 🔔 {method_label}{policy_line}{desc}"
    )
