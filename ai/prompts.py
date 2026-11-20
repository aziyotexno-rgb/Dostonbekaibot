"""System prompts, response schemas, and Uzbek voice command classifiers."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AICommandAction(BaseModel):
    intent: Literal[
        "create_reminder",
        "update_morning_call",
        "update_evening_report",
        "request_delete_reminder",
        "list_today_tasks",
        "mark_completed",
        "general_chat",
    ]
    title: Optional[str] = Field(default=None, description="Vazifa nomi")
    description: Optional[str] = Field(default="", description="Qo'shimcha izoh")
    date: Optional[str] = Field(
        default=None, description="YYYY-MM-DD formatidagi sana (Asia/Tashkent)"
    )
    time: Optional[str] = Field(default=None, description="HH:MM formatidagi vaqt")
    recurrence_type: Literal["once", "daily", "weekly", "monthly", "custom_days"] = "once"
    recurrence_days: Optional[str] = Field(
        default=None, description="Vergul bilan ajratilgan hafta kunlari 0=Du..6=Ya"
    )
    delivery_method: Literal["text", "voice", "call"] = "voice"
    search_query: Optional[str] = Field(
        default=None, description="O'chirish yoki bajarildi deb belgilash uchun qidiruv so'zi"
    )
    target_hour: Optional[int] = Field(
        default=None, description="Qidirilayotgan eslatma soati (0-23)"
    )
    reply_uz: str = Field(
        description="Foydalanuvchiga sof o'zbek tilida tabiiy va hurmatli javob matni"
    )


class CallVoiceReplyAction(BaseModel):
    """Structured classification of user's spoken reply during a live VoIP call."""

    command: Literal[
        "done",
        "not_done",
        "snooze_later",
        "snooze_1h",
        "cancel_reminder",
        "list_today",
        "unknown",
    ]
    reply_uz: str = Field(
        description="Qo'ng'iroq davomida foydalanuvchiga aytiladigan qisqa, samimiy o'zbekcha javob"
    )


STYLE_INSTRUCTIONS = {
    "formal": "Siz rasmiy, hurmatli va tartibli shaxsiy kotibsiz. 'Siz' deb murojaat qiling, chet el so'zlarini ishlatmang.",
    "friendly": "Siz samimiy, iliq va hurmat bilan gapiradigan shaxsiy kotibsiz. Sof o'zbek tilida yordam bering.",
    "concise": "Siz juda qisqa, lo'nda va aniq gapiradigan shaxsiy kotibsiz. Faqat sof o'zbek tilida javob bering.",
}


from voice.commands import classify_call_voice_phrase as _classify_phrase


def classify_call_voice_phrase(transcript: str) -> Optional[CallVoiceReplyAction]:
    """Fast deterministic Uzbek phrase matcher for standard in-call voice commands."""
    matched = _classify_phrase(transcript)
    if matched is None:
        return None
    return CallVoiceReplyAction(command=matched.command, reply_uz=matched.reply_uz)


def build_secretary_system_prompt(
    today_iso: str,
    now_time: str,
    tz_name: str,
    ai_style: str,
    upcoming_summary: str,
) -> str:
    style_desc = STYLE_INSTRUCTIONS.get(ai_style, STYLE_INSTRUCTIONS["friendly"])
    return (
        f"Siz Dostonbekning shaxsiy AI kotibisiz (Dostonbek AI Bot). {style_desc}\n"
        f"Hozirgi vaqt zonasi: {tz_name}. Bugungi sana: {today_iso}. Hozirgi soat: {now_time}.\n\n"
        "MUHIM TIL QOIDASI: Faqat sof, tabiiy va hurmatli o'zbek tilida javob bering. "
        "Inglizcha yoki ruscha so'zlarni keraksiz ishlatmang.\n\n"
        "Foydalanuvchining o'zbek tilidagi buyruqlarini tahlil qilib, faqat JSON formatida javob qaytaring.\n"
        "Qoidalar:\n"
        "1. Agar foydalanuvchi yangi eslatma yoki vazifa qo'shmoqchi bo'lsa -> intent='create_reminder'. "
        "'bugun' -> bugungi sana, 'ertaga' -> ertangi sana qilib YYYY-MM-DD hisoblang.\n"
        "2. Agar 'Har kuni ertalab soat 8 da kunlik rejalarimni ayt' kabi ertalabki qo'ng'iroq vaqtini o'zgartirsa -> "
        "intent='update_morning_call' va time='08:00'.\n"
        "3. Agar kechki hisobot vaqtini o'zgartirsa -> intent='update_evening_report'.\n"
        "4. Agar eslatmani o'chirishni so'rasa -> intent='request_delete_reminder' (tasdiqsiz o'chirmaslik uchun qidiruv mezonlarini chiqaring).\n"
        "5. Agar 'Bugun qanday ishlarim bor?' desa -> intent='list_today_tasks'.\n"
        "6. Agar vazifani bajarganini aytsa -> intent='mark_completed'.\n"
        "7. Oddiy savol yoki suhbat bo'lsa -> intent='general_chat'.\n\n"
        f"Foydalanuvchining joriy yaqin vazifalari konteksti:\n{upcoming_summary}"
    )
