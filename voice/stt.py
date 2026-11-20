"""Uzbek Speech-to-Text wrapper backed by Gemini multimodal audio recognition."""

from __future__ import annotations

from pathlib import Path

from ai.gemini_client import GeminiSecretary


async def transcribe_voice_file(
    gemini: GeminiSecretary,
    file_path: Path,
    mime_type: str = "audio/ogg",
) -> str:
    audio_bytes = file_path.read_bytes()
    return await gemini.transcribe_uzbek_audio(audio_bytes, mime_type=mime_type)
