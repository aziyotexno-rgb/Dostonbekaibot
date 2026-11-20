"""Uzbek neural Text-to-Speech synthesizer with ffmpeg transcoding for Telegram & VoIP."""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import edge_tts

logger = logging.getLogger("dostonbek.voice.tts")

# Strictly verified Uzbek Neural voices supported by Edge TTS
SUPPORTED_UZBEK_VOICES: dict[str, str] = {
    "uz-UZ-SardorNeural": "Sardor (Erkak, tabiiy o'zbek ovozi)",
    "uz-UZ-MadinaNeural": "Madina (Ayol, tabiiy o'zbek ovozi)",
}

SUPPORTED_VOICE_RATES: dict[str, str] = {
    "-15%": "Sekin (-15%)",
    "+0%": "Normal (0%)",
    "+15%": "Tez (+15%)",
    "+25%": "Juda tez (+25%)",
}


@dataclass
class SynthesizedAudio:
    mp3_path: Path
    ogg_path: Optional[Path]
    pcm_path: Optional[Path]
    duration_seconds: float


async def _run_ffmpeg(args: list[str]) -> bool:
    if not shutil.which("ffmpeg"):
        logger.warning("ffmpeg topilmadi — audio konvertatsiyasi o'tkazib yuborildi.")
        return False

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error("ffmpeg xatoligi: %s", stderr.decode(errors="ignore"))
        return False
    return True


async def _probe_duration(file_path: Path) -> float:
    if not shutil.which("ffprobe"):
        # Conservative estimate if ffprobe is absent (~13 chars/sec in Uzbek speech)
        return 6.0
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return max(1.0, float(stdout.decode().strip()))
    except Exception:
        return 6.0


async def synthesize_uzbek_speech(
    text: str,
    output_dir: Path,
    voice_name: str = "uz-UZ-SardorNeural",
    voice_rate: str = "+0%",
    for_voip_pcm: bool = False,
) -> SynthesizedAudio:
    """Synthesize Uzbek text into MP3, OGG/Opus (Telegram voice), and optionally 48kHz PCM (VoIP)."""
    if voice_name not in SUPPORTED_UZBEK_VOICES:
        raise ValueError(
            f"Qo'llab-quvvatlanmaydigan ovoz turi: {voice_name}. "
            f"Mavjud ovozlar: {', '.join(SUPPORTED_UZBEK_VOICES.keys())}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    uid = uuid.uuid4().hex[:12]
    mp3_path = output_dir / f"tts_{uid}.mp3"
    ogg_path = output_dir / f"tts_{uid}.ogg"
    pcm_path = output_dir / f"tts_{uid}.pcm" if for_voip_pcm else None

    communicate = edge_tts.Communicate(text=text, voice=voice_name, rate=voice_rate)
    await communicate.save(str(mp3_path))

    duration = await _probe_duration(mp3_path)

    ogg_ok = await _run_ffmpeg(
        ["-i", str(mp3_path), "-c:a", "libopus", "-b:a", "48k", str(ogg_path)]
    )
    final_ogg = ogg_path if ogg_ok and ogg_path.exists() else None

    final_pcm: Optional[Path] = None
    if for_voip_pcm and pcm_path is not None:
        pcm_ok = await _run_ffmpeg(
            [
                "-i",
                str(mp3_path),
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "48000",
                "-ac",
                "1",
                str(pcm_path),
            ]
        )
        if pcm_ok and pcm_path.exists():
            final_pcm = pcm_path

    return SynthesizedAudio(
        mp3_path=mp3_path,
        ogg_path=final_ogg,
        pcm_path=final_pcm,
        duration_seconds=duration,
    )


def cleanup_audio_files(audio: SynthesizedAudio) -> None:
    for p in (audio.mp3_path, audio.ogg_path, audio.pcm_path):
        if p and p.exists():
            try:
                p.unlink()
            except OSError:
                pass
