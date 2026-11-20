"""Google Gemini API client for Uzbek NLU, voice call reply parsing, and STT."""

from __future__ import annotations

import logging
from typing import Optional

from google import genai
from google.genai import types

from ai.prompts import (
    AICommandAction,
    CallVoiceReplyAction,
    build_secretary_system_prompt,
    classify_call_voice_phrase,
)
from utils.time_utils import now_in_tz

logger = logging.getLogger("dostonbek.ai")


class GeminiSecretary:
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash") -> None:
        self.api_key = api_key.strip()
        self.model_name = model_name
        self._client: Optional[genai.Client] = (
            genai.Client(api_key=self.api_key) if self.api_key else None
        )

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    async def parse_user_command(
        self,
        user_text: str,
        tz_name: str = "Asia/Tashkent",
        ai_style: str = "friendly",
        upcoming_summary: str = "Mavjud emas",
    ) -> AICommandAction:
        if not self._client:
            raise RuntimeError(
                "GEMINI_API_KEY sozlanmagan. Sun'iy intellekt buyruqlari uchun kalitni kiriting."
            )

        now = now_in_tz(tz_name)
        system_instruction = build_secretary_system_prompt(
            today_iso=now.date().isoformat(),
            now_time=now.strftime("%H:%M"),
            tz_name=tz_name,
            ai_style=ai_style,
            upcoming_summary=upcoming_summary,
        )

        response = await self._client.aio.models.generate_content(
            model=self.model_name,
            contents=user_text,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=AICommandAction,
            ),
        )

        raw_json = (response.text or "").strip()
        if not raw_json:
            return AICommandAction(
                intent="general_chat",
                reply_uz="Kechirasiz, buyrug'ingizni tushunishda muammo yuz berdi. Qayta urinib ko'ring.",
            )
        return AICommandAction.model_validate_json(raw_json)

    async def parse_call_voice_reply(self, transcript: str, task_title: str) -> CallVoiceReplyAction:
        """Classify user's spoken reply during a VoIP call into one of the 6 Uzbek commands."""
        quick = classify_call_voice_phrase(transcript)
        if quick is not None:
            return quick

        if not self._client:
            return CallVoiceReplyAction(
                command="unknown",
                reply_uz="Kechirasiz, javobingizni aniq eshitolmadim. Vazifani keyinroq yana eslataman.",
            )

        sys_prompt = (
            "Siz Dostonbekka telefon qo'ng'irog'i qilayotgan o'zbekcha shaxsiy kotibsiz. "
            f"Muhokama qilinayotgan vazifa: '{task_title}'. "
            "Foydalanuvchi qo'ng'iroq paytida aytgan gapini quyidagi 7 toifadan biriga ajrating:\n"
            "- done ('Ha, bajardim', 'Ha, esladim', 'Tugatdim')\n"
            "- not_done ('Hali bajarmadim', 'Ulgurmadim')\n"
            "- snooze_later ('Keyinroq eslat', 'Birozdan keyin')\n"
            "- snooze_1h ('Bir soatdan keyin eslat')\n"
            "- cancel_reminder ('Eslatmani bekor qil')\n"
            "- list_today ('Bugungi rejalarimni ayt')\n"
            "- unknown (boshqa tushunarsiz javob)\n"
            "Javob matni sof, samimiy o'zbek tilida bo'lsin."
        )
        response = await self._client.aio.models.generate_content(
            model=self.model_name,
            contents=transcript,
            config=types.GenerateContentConfig(
                system_instruction=sys_prompt,
                response_mime_type="application/json",
                response_schema=CallVoiceReplyAction,
            ),
        )
        raw_json = (response.text or "").strip()
        if not raw_json:
            return CallVoiceReplyAction(
                command="unknown",
                reply_uz="Kechirasiz, javobingiz aniq bo'lmadi. Keyinroq yana eslataman.",
            )
        return CallVoiceReplyAction.model_validate_json(raw_json)

    async def transcribe_uzbek_audio(
        self, audio_bytes: bytes, mime_type: str = "audio/ogg"
    ) -> str:
        """Transcribe Uzbek voice messages or recorded VoIP call replies using Gemini STT."""
        if not self._client:
            raise RuntimeError("GEMINI_API_KEY sozlanmagan.")

        response = await self._client.aio.models.generate_content(
            model=self.model_name,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                (
                    "Ushbu o'zbek tilidagi ovozli javobni so'zma-so'z, to'g'ri imlo bilan "
                    "lotin alifbosida matnga aylantiring. Agar nutq bo'lmasa yoki faqat shovqin bo'lsa, "
                    "bo'sh satr qaytaring. Faqat transkripsiya matnini qaytaring."
                ),
            ],
        )
        return (response.text or "").strip()
