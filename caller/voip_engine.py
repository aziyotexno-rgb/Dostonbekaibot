"""Interactive Bidirectional 1:1 Telegram MTProto VoIP Call Engine (Pyrogram + NTgCalls).

Technical Architecture & Transparency:
- Telegram Bot API cannot initiate 1:1 voice calls.
- A secondary user account (@Yordamchiaidosa) places real encrypted 1:1 P2P VoIP calls
  to @D_admin_aka using Pyrogram + NTgCalls + ffmpeg.
- Full call lifecycle:
  1) 2048-bit Diffie-Hellman key exchange (`messages.GetDhConfig`, `phone.RequestCall`, `phone.ConfirmCall`)
  2) WebRTC/UDP reflector signaling (`phone.SendSignalingData` <-> `UpdatePhoneCallSignalingData`)
  3) Outgoing Uzbek TTS greeting + task statement (48kHz mono s16le PCM)
  4) Incoming speaker audio capture during `response_wait_seconds` -> WAV -> Gemini STT ->
     Uzbek command classification -> live spoken Uzbek reply over the same call
  5) Red-button hangup (`PhoneCallDiscarded`) is explicitly separated from task completion:
     ending a call NEVER marks a task completed; it records `declined` or `hung_up_unconfirmed`
     so retry rules can take over safely.
- Honest Guard: If `pyrogram`, `ntgcalls`, `ffmpeg`, or `TELEGRAM_SESSION_STRING` is missing,
  this module returns `status="unavailable"` with exact diagnostics and NEVER fabricates a call.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import random
import shutil
import struct
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("dostonbek.caller.voip")


@dataclass
class VoIPCapabilities:
    supported: bool
    has_pyrogram: bool
    has_ntgcalls: bool
    has_ffmpeg: bool
    has_credentials: bool
    missing_components: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class CallOutcome:
    # completed | answered | no_response | hung_up_unconfirmed | missed | declined | failed | unavailable
    status: str
    duration_seconds: int = 0
    user_transcript: Optional[str] = None
    detected_intent: Optional[str] = None
    error_detail: Optional[str] = None
    used_fallback: bool = False


def inspect_voip_capabilities(
    api_id: int,
    api_hash: str,
    session_string: str,
) -> VoIPCapabilities:
    missing: list[str] = []

    try:
        import pyrogram  # noqa: F401
        has_pyrogram = True
    except ImportError:
        has_pyrogram = False
        missing.append("pyrogram")

    try:
        import ntgcalls  # noqa: F401
        has_ntgcalls = True
    except ImportError:
        has_ntgcalls = False
        missing.append("ntgcalls")

    has_ffmpeg = shutil.which("ffmpeg") is not None
    if not has_ffmpeg:
        missing.append("ffmpeg")

    has_credentials = bool(api_id and api_hash and session_string)
    if not api_id:
        missing.append("TELEGRAM_API_ID")
    if not api_hash:
        missing.append("TELEGRAM_API_HASH")
    if not session_string:
        missing.append("TELEGRAM_SESSION_STRING")

    supported = has_pyrogram and has_ntgcalls and has_ffmpeg and has_credentials
    note = (
        "1:1 MTProto interaktiv VoIP qo'ng'iroq dvigateli tayyor (Pyrogram + NTgCalls + ffmpeg)."
        if supported
        else f"Haqiqiy VoIP qo'ng'iroq uchun yetishmayotgan qismlar: {', '.join(missing)}"
    )
    return VoIPCapabilities(
        supported=supported,
        has_pyrogram=has_pyrogram,
        has_ntgcalls=has_ntgcalls,
        has_ffmpeg=has_ffmpeg,
        has_credentials=has_credentials,
        missing_components=missing,
        note=note,
    )


def pcm_has_speech(pcm_bytes: bytes, rms_threshold: int = 260) -> bool:
    """Check whether 16-bit PCM buffer contains non-silent speech energy."""
    if len(pcm_bytes) < 3200:
        return False
    sample_count = len(pcm_bytes) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm_bytes[: sample_count * 2])
    step = max(1, sample_count // 2000)
    sampled = samples[::step]
    mean_sq = sum(s * s for s in sampled) / max(1, len(sampled))
    rms = mean_sq ** 0.5
    return rms >= rms_threshold


def pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = 48000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


class TelegramVoIPCaller:
    """Manages MTProto userbot connection and bidirectional 1:1 P2P VoIP calls."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_string: str,
        caller_username: str = "@Yordamchiaidosa",
        callee_username: str = "@D_admin_aka",
    ) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_string = session_string
        self.caller_username = caller_username
        self.callee_username = callee_username
        self._client: Any = None
        self._ntg: Any = None
        self._lock = asyncio.Lock()

    def get_capabilities(self) -> VoIPCapabilities:
        return inspect_voip_capabilities(
            self.api_id, self.api_hash, self.session_string
        )

    async def start(self) -> bool:
        caps = self.get_capabilities()
        if not caps.supported:
            logger.warning("VoIP dvigateli ishga tushmadi: %s", caps.note)
            return False

        from pyrogram import Client
        import ntgcalls

        if self._client is None:
            self._client = Client(
                name="dostonbek_voip_caller",
                api_id=self.api_id,
                api_hash=self.api_hash,
                session_string=self.session_string,
                in_memory=True,
                no_updates=False,
            )
            await self._client.start()
            me = await self._client.get_me()
            logger.info(
                "MTProto VoIP akkaunti ulandi: @%s (id=%s)",
                me.username or "noma'lum",
                me.id,
            )

        if self._ntg is None:
            self._ntg = ntgcalls.NTgCalls()
        return True

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await self._client.stop()
            except Exception as exc:
                logger.debug("VoIP mijozini to'xtatishda ogohlantirish: %s", exc)
            finally:
                self._client = None

    async def place_interactive_call(
        self,
        greeting_pcm_path: Optional[Path],
        greeting_duration_seconds: float,
        repeat_pcm_path: Optional[Path] = None,
        repeat_duration_seconds: float = 0.0,
        response_wait_seconds: int = 15,
        target_username: Optional[str] = None,
        ring_timeout_seconds: int = 35,
        transcribe_fn: Optional[Callable[[bytes], Awaitable[str]]] = None,
        handle_reply_fn: Optional[
            Callable[[str], Awaitable[tuple[str, Optional[Path], float]]]
        ] = None,
    ) -> CallOutcome:
        """Place a real 1:1 VoIP call, speak greeting, listen for Uzbek voice reply, and respond."""
        caps = self.get_capabilities()
        if not caps.supported:
            return CallOutcome(
                status="unavailable",
                duration_seconds=0,
                error_detail=caps.note,
            )

        if greeting_pcm_path is None or not greeting_pcm_path.exists():
            return CallOutcome(
                status="failed",
                duration_seconds=0,
                error_detail="Qo'ng'iroq uchun 48kHz PCM ovoz fayli tayyorlanmadi.",
            )

        async with self._lock:
            try:
                started = await self.start()
                if not started or self._client is None or self._ntg is None:
                    return CallOutcome(
                        status="unavailable",
                        error_detail="MTProto foydalanuvchi sessiyasi ulanmadi.",
                    )

                return await self._execute_interactive_p2p(
                    greeting_path=greeting_pcm_path,
                    greeting_duration=greeting_duration_seconds,
                    repeat_path=repeat_pcm_path,
                    repeat_duration=repeat_duration_seconds,
                    response_wait=response_wait_seconds,
                    target=target_username or self.callee_username,
                    ring_timeout=ring_timeout_seconds,
                    transcribe_fn=transcribe_fn,
                    handle_reply_fn=handle_reply_fn,
                )
            except Exception as exc:
                logger.exception("Interaktiv 1:1 VoIP qo'ng'iroq jarayonida xatolik")
                return CallOutcome(
                    status="failed",
                    duration_seconds=0,
                    error_detail=str(exc),
                )

    async def _execute_interactive_p2p(
        self,
        greeting_path: Path,
        greeting_duration: float,
        repeat_path: Optional[Path],
        repeat_duration: float,
        response_wait: int,
        target: str,
        ring_timeout: int,
        transcribe_fn: Optional[Callable[[bytes], Awaitable[str]]],
        handle_reply_fn: Optional[
            Callable[[str], Awaitable[tuple[str, Optional[Path], float]]]
        ],
    ) -> CallOutcome:
        import ntgcalls
        from pyrogram.handlers import RawUpdateHandler
        from pyrogram.raw import functions, types

        client = self._client
        ntg = self._ntg

        peer_resolved = await client.resolve_peer(target)
        if not isinstance(peer_resolved, types.InputPeerUser):
            return CallOutcome(
                status="failed",
                error_detail=f"{target} oddiy Telegram foydalanuvchisi emas.",
            )

        input_user = types.InputUser(
            user_id=peer_resolved.user_id,
            access_hash=peer_resolved.access_hash,
        )

        # 1. Diffie-Hellman setup
        dh_cfg = await client.invoke(
            functions.messages.GetDhConfig(version=0, random_length=256)
        )
        p = int.from_bytes(dh_cfg.p, "big")
        g = dh_cfg.g
        a_int = int.from_bytes(os.urandom(256), "big")
        g_a = pow(g, a_int, p).to_bytes(256, "big")
        g_a_hash = hashlib.sha256(g_a).digest()

        protocol = types.PhoneCallProtocol(
            min_layer=92,
            max_layer=92,
            udp_p2p=True,
            udp_reflector=True,
            library_versions=["5.0.0", "4.0.0"],
        )

        call_state: dict[str, Any] = {
            "call_id": None,
            "accepted_event": asyncio.Event(),
            "ended_event": asyncio.Event(),
            "end_reason": None,
            "phone_call": None,
        }
        captured_pcm = bytearray()
        capturing_enabled = False

        async def _raw_handler(_client: Any, update: Any, _users: Any, _chats: Any) -> None:
            if isinstance(update, types.UpdatePhoneCall):
                pc = update.phone_call
                if call_state["call_id"] and getattr(pc, "id", None) != call_state["call_id"]:
                    return
                if isinstance(pc, types.PhoneCallAccepted):
                    call_state["phone_call"] = pc
                    call_state["accepted_event"].set()
                elif isinstance(pc, types.PhoneCallDiscarded):
                    call_state["end_reason"] = (
                        type(pc.reason).__name__ if pc.reason else "discarded"
                    )
                    call_state["ended_event"].set()
            elif isinstance(update, types.UpdatePhoneCallSignalingData):
                if call_state["call_id"] and update.phone_call_id == call_state["call_id"]:
                    try:
                        await ntg.send_signaling_data(peer_resolved.user_id, update.data)
                    except Exception as sig_exc:
                        logger.debug("Signaling qabul qilish xatoligi: %s", sig_exc)

        handler = RawUpdateHandler(_raw_handler)
        client.add_handler(handler)
        call_started_ts: Optional[float] = None

        try:
            # 2. Request outgoing 1:1 call
            req_res = await client.invoke(
                functions.phone.RequestCall(
                    user_id=input_user,
                    random_id=random.randint(1, 0x7FFFFFFF),
                    g_a_hash=g_a_hash,
                    protocol=protocol,
                    video=False,
                )
            )
            call_obj = req_res.phone_call
            call_state["call_id"] = call_obj.id
            input_call = types.InputPhoneCall(
                id=call_obj.id, access_hash=call_obj.access_hash
            )

            # 3. Ringing phase — wait for callee accept or red-button reject
            await asyncio.wait(
                [
                    asyncio.create_task(call_state["accepted_event"].wait()),
                    asyncio.create_task(call_state["ended_event"].wait()),
                ],
                timeout=ring_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if call_state["ended_event"].is_set():
                reason = call_state["end_reason"] or "declined"
                status = (
                    "declined"
                    if "Busy" in reason or "Disconnect" in reason or "Hangup" in reason
                    else "missed"
                )
                return CallOutcome(status=status, duration_seconds=0)

            if not call_state["accepted_event"].is_set():
                await client.invoke(
                    functions.phone.DiscardCall(
                        peer=input_call,
                        duration=0,
                        reason=types.PhoneCallDiscardReasonMissed(),
                        connection_id=0,
                    )
                )
                return CallOutcome(status="missed", duration_seconds=0)

            # 4. Confirm encrypted DH session
            accepted_pc: types.PhoneCallAccepted = call_state["phone_call"]
            auth_key = pow(
                int.from_bytes(accepted_pc.g_b, "big"), a_int, p
            ).to_bytes(256, "big")
            key_fingerprint = int.from_bytes(
                hashlib.sha1(auth_key).digest()[-8:], "little", signed=True
            )

            confirm_res = await client.invoke(
                functions.phone.ConfirmCall(
                    peer=input_call,
                    g_a=g_a,
                    key_fingerprint=key_fingerprint,
                    protocol=protocol,
                )
            )
            active_call = confirm_res.phone_call
            call_started_ts = asyncio.get_running_loop().time()

            # 5. Wire NTgCalls P2P audio stream + incoming voice frame capture
            loop = asyncio.get_running_loop()

            @ntg.on_signaling
            def _on_ntg_signaling(chat_id: int, data: bytes) -> None:
                if chat_id == peer_resolved.user_id:
                    asyncio.run_coroutine_threadsafe(
                        client.invoke(
                            functions.phone.SendSignalingData(peer=input_call, data=data)
                        ),
                        loop,
                    )

            if hasattr(ntg, "on_frames"):
                @ntg.on_frames
                def _on_incoming_frames(
                    chat_id: int,
                    _mode: Any,
                    _device: Any,
                    frames: list[Any],
                ) -> None:
                    if not capturing_enabled or chat_id != peer_resolved.user_id:
                        return
                    for frame in frames:
                        data = getattr(frame, "data", None)
                        if isinstance(data, (bytes, bytearray)):
                            captured_pcm.extend(data)

            async def _play_pcm(pcm_file: Path, duration: float) -> bool:
                media_desc = ntgcalls.MediaDescription(
                    microphone=ntgcalls.AudioDescription(
                        media_source=ntgcalls.MediaSource.FILE,
                        path=str(pcm_file),
                        sample_rate=48000,
                        bits_per_sample=16,
                        channel_count=1,
                    )
                )
                await ntg.set_stream_sources(
                    peer_resolved.user_id,
                    ntgcalls.StreamMode.CAPTURE,
                    media_desc,
                )
                try:
                    await asyncio.wait_for(
                        call_state["ended_event"].wait(), timeout=max(1.5, duration + 1.0)
                    )
                    return False  # Call ended early by user (red button)
                except asyncio.TimeoutError:
                    return True

            await ntg.create_p2p_call(peer_resolved.user_id)

            rtc_servers = [
                ntgcalls.RTCServer(
                    id=conn.id,
                    ipv4=conn.ip,
                    ipv6=conn.ipv6,
                    port=conn.port,
                    username=getattr(conn, "username", None),
                    password=getattr(conn, "password", None),
                    turn=isinstance(conn, types.PhoneConnectionWebrtc) and conn.turn,
                    stun=isinstance(conn, types.PhoneConnectionWebrtc) and conn.stun,
                    tcp=getattr(conn, "tcp", False),
                    peer_tag=getattr(conn, "peer_tag", None),
                )
                for conn in getattr(active_call, "connections", [])
            ]

            await ntg.connect_p2p(
                peer_resolved.user_id,
                rtc_servers,
                active_call.protocol.library_versions,
                active_call.p2p_allowed,
                auth_key,
                True,
            )

            # 6. Play greeting + today's task
            still_connected = await _play_pcm(greeting_path, greeting_duration)
            if not still_connected:
                elapsed = int(max(1, asyncio.get_running_loop().time() - call_started_ts))
                return CallOutcome(status="hung_up_unconfirmed", duration_seconds=elapsed)

            # 7. Listen for user's spoken Uzbek reply
            user_transcript: Optional[str] = None
            detected_intent: Optional[str] = None
            final_status = "no_response"

            async def _listen_and_transcribe() -> Optional[str]:
                nonlocal capturing_enabled
                captured_pcm.clear()
                capturing_enabled = True
                try:
                    await asyncio.wait_for(
                        call_state["ended_event"].wait(),
                        timeout=max(4, response_wait),
                    )
                    return None
                except asyncio.TimeoutError:
                    pass
                finally:
                    capturing_enabled = False

                if not pcm_has_speech(bytes(captured_pcm)):
                    return None
                if transcribe_fn is None:
                    return None
                wav_bytes = pcm_to_wav_bytes(bytes(captured_pcm))
                return (await transcribe_fn(wav_bytes)).strip() or None

            user_transcript = await _listen_and_transcribe()

            # If no response on first listen and repeat prompt exists, remind once more
            if (
                user_transcript is None
                and not call_state["ended_event"].is_set()
                and repeat_path is not None
                and repeat_path.exists()
            ):
                still_connected = await _play_pcm(repeat_path, repeat_duration)
                if not still_connected:
                    elapsed = int(max(1, asyncio.get_running_loop().time() - call_started_ts))
                    return CallOutcome(status="hung_up_unconfirmed", duration_seconds=elapsed)
                user_transcript = await _listen_and_transcribe()

            if call_state["ended_event"].is_set() and user_transcript is None:
                elapsed = int(max(1, asyncio.get_running_loop().time() - call_started_ts))
                return CallOutcome(status="hung_up_unconfirmed", duration_seconds=elapsed)

            if user_transcript and handle_reply_fn is not None:
                detected_intent, reply_pcm, reply_duration = await handle_reply_fn(
                    user_transcript
                )
                final_status = "completed"
                if reply_pcm is not None and reply_pcm.exists() and not call_state["ended_event"].is_set():
                    await _play_pcm(reply_pcm, reply_duration)

            elapsed = int(max(1, asyncio.get_running_loop().time() - call_started_ts))

            try:
                await ntg.stop(peer_resolved.user_id)
            except Exception:
                pass

            if not call_state["ended_event"].is_set():
                await client.invoke(
                    functions.phone.DiscardCall(
                        peer=input_call,
                        duration=elapsed,
                        reason=types.PhoneCallDiscardReasonHangup(),
                        connection_id=0,
                    )
                )

            return CallOutcome(
                status=final_status,
                duration_seconds=elapsed,
                user_transcript=user_transcript,
                detected_intent=detected_intent,
            )
        finally:
            client.remove_handler(handler)
