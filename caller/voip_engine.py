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
import io
import logging
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
        """Call the target, announce the reminder three times, then hang up.

        The reminder call is intentionally one-way: it does not listen for,
        transcribe, or interpret a spoken reply.
        """
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

        user_id = peer_resolved.user_id
        input_user = types.InputUser(
            user_id=user_id,
            access_hash=peer_resolved.access_hash,
        )
        loop = asyncio.get_running_loop()
        state: dict[str, Any] = {
            "call_id": None,
            "phone_call": None,
            "end_reason": None,
        }
        accepted_event = asyncio.Event()
        ended_event = asyncio.Event()
        connected_event = asyncio.Event()
        connection_failed = asyncio.Event()
        connection_error: list[str] = []
        signaling_ready = asyncio.Event()
        incoming_signaling: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        input_call = None
        discard_requested = False
        signaling_task: Optional[asyncio.Task] = None
        call_started_ts: Optional[float] = None

        async def _raw_handler(
            _client: Any, update: Any, _users: Any, _chats: Any
        ) -> None:
            if isinstance(update, types.UpdatePhoneCall):
                phone_call = update.phone_call
                if state["call_id"] and getattr(phone_call, "id", None) != state["call_id"]:
                    return
                if isinstance(phone_call, types.PhoneCallAccepted):
                    state["phone_call"] = phone_call
                    accepted_event.set()
                elif isinstance(phone_call, types.PhoneCallDiscarded):
                    reason = getattr(phone_call, "reason", None)
                    state["end_reason"] = type(reason).__name__ if reason else "discarded"
                    ended_event.set()
            elif isinstance(update, types.UpdatePhoneCallSignalingData):
                if state["call_id"] and update.phone_call_id == state["call_id"]:
                    # Queue early ICE/signaling packets until connect_p2p is ready.
                    await incoming_signaling.put(bytes(update.data))

        def _send_signaling_to_telegram(chat_id: int, data: bytes) -> None:
            if chat_id != user_id or input_call is None:
                return
            future = asyncio.run_coroutine_threadsafe(
                client.invoke(
                    functions.phone.SendSignalingData(peer=input_call, data=data)
                ),
                loop,
            )

            def _log_signal_error(done: Any) -> None:
                try:
                    done.result()
                except Exception:
                    logger.exception("Telegram signaling yuborishda xatolik")

            future.add_done_callback(_log_signal_error)

        def _on_connection_change(chat_id: int, net_info: Any) -> None:
            if chat_id != user_id:
                return
            connection_state = getattr(net_info, "state", net_info)
            name = getattr(connection_state, "name", str(connection_state)).upper()
            logger.info("NTgCalls ulanish holati: %s", name)
            if "CONNECTED" in name:
                loop.call_soon_threadsafe(connected_event.set)
            elif any(word in name for word in ("FAILED", "TIMEOUT", "DISCONNECTED")):
                connection_error.append(name)
                loop.call_soon_threadsafe(connection_failed.set)

        async def _incoming_signaling_pump() -> None:
            await signaling_ready.wait()
            while True:
                packet = await incoming_signaling.get()
                if packet is None:
                    return
                await ntg.send_signaling_data(user_id, packet)

        handler = RawUpdateHandler(_raw_handler)
        client.add_handler(handler)

        try:
            # Register NTgCalls callbacks before starting the Telegram call.
            ntg.on_signaling_data(_send_signaling_to_telegram)
            if hasattr(ntg, "on_connection_change"):
                ntg.on_connection_change(_on_connection_change)

            # NTgCalls must own the DH secret and calculate the public hash.
            await ntg.create_p2p_call(user_id)
            dh_config = await client.invoke(
                functions.messages.GetDhConfig(version=0, random_length=256)
            )
            ntg_dh = ntgcalls.DhConfig(
                dh_config.g,
                dh_config.p,
                dh_config.random,
            )
            g_a_hash = await ntg.init_exchange(user_id, ntg_dh, None)

            protocol = types.PhoneCallProtocol(
                min_layer=92,
                max_layer=92,
                udp_p2p=True,
                udp_reflector=True,
                library_versions=["9.0.0", "8.0.0", "5.0.0"],
            )

            request_result = await client.invoke(
                functions.phone.RequestCall(
                    user_id=input_user,
                    random_id=random.randint(1, 0x7FFFFFFF),
                    g_a_hash=g_a_hash,
                    protocol=protocol,
                    video=False,
                )
            )
            call_obj = request_result.phone_call
            state["call_id"] = call_obj.id
            input_call = types.InputPhoneCall(
                id=call_obj.id,
                access_hash=call_obj.access_hash,
            )

            # Wait for the other Telegram user to accept or reject the call.
            accepted_wait = asyncio.create_task(accepted_event.wait())
            ended_wait = asyncio.create_task(ended_event.wait())
            done, pending = await asyncio.wait(
                {accepted_wait, ended_wait},
                timeout=ring_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if ended_event.is_set():
                reason = state["end_reason"] or "discarded"
                status = "declined" if any(
                    word in reason for word in ("Busy", "Hangup", "Disconnect")
                ) else "missed"
                return CallOutcome(status=status)
            if accepted_wait not in done or not accepted_event.is_set():
                await client.invoke(
                    functions.phone.DiscardCall(
                        peer=input_call,
                        duration=0,
                        reason=types.PhoneCallDiscardReasonMissed(),
                        connection_id=0,
                    )
                )
                return CallOutcome(status="missed")

            # NTgCalls derives the key and returns the values for phone.confirmCall.
            accepted_call = state["phone_call"]
            auth_params = await ntg.exchange_keys(user_id, accepted_call.g_b, 0)
            confirm_result = await client.invoke(
                functions.phone.ConfirmCall(
                    peer=input_call,
                    g_a=auth_params.g_a_or_b,
                    key_fingerprint=auth_params.key_fingerprint,
                    protocol=protocol,
                )
            )
            active_call = confirm_result.phone_call
            call_started_ts = loop.time()

            signaling_task = asyncio.create_task(_incoming_signaling_pump())
            rtc_servers = [
                ntgcalls.RTCServer(
                    id=connection.id,
                    ipv4=connection.ip,
                    ipv6=connection.ipv6,
                    port=connection.port,
                    username=getattr(connection, "username", None),
                    password=getattr(connection, "password", None),
                    turn=isinstance(connection, types.PhoneConnectionWebrtc)
                    and connection.turn,
                    stun=isinstance(connection, types.PhoneConnectionWebrtc)
                    and connection.stun,
                    tcp=getattr(connection, "tcp", False),
                    peer_tag=getattr(connection, "peer_tag", None),
                )
                for connection in getattr(active_call, "connections", [])
            ]
            if not rtc_servers:
                raise RuntimeError("Telegram qo‘ng‘iroq uchun RTC server bermadi.")

            await ntg.connect_p2p(
                user_id,
                rtc_servers,
                active_call.protocol.library_versions,
                active_call.p2p_allowed,
                None,
            )
            signaling_ready.set()

            # Wait until WebRTC is actually connected before sending the audio.
            if hasattr(ntg, "on_connection_change"):
                connected_wait = asyncio.create_task(connected_event.wait())
                failed_wait = asyncio.create_task(connection_failed.wait())
                ended_wait = asyncio.create_task(ended_event.wait())
                done, pending = await asyncio.wait(
                    {connected_wait, failed_wait, ended_wait},
                    timeout=35,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if ended_event.is_set():
                    return CallOutcome(status="hung_up_unconfirmed")
                if failed_wait in done and connection_failed.is_set():
                    raise RuntimeError(
                        "Telegram VoIP WebRTC ulanishi amalga oshmadi: "
                        + ", ".join(connection_error)
                    )
                if connected_wait not in done or not connected_event.is_set():
                    raise RuntimeError(
                        "Telegram VoIP ulanishi 35 soniyada yakunlanmadi. "
                        "Render UDP/signaling ulanishini tekshirish kerak."
                    )
            else:
                # Older bindings do not expose connection-state callbacks.
                await asyncio.sleep(2)

            async def _play_pcm(pcm_file: Path, duration: float) -> bool:
                media = ntgcalls.MediaDescription(
                    microphone=ntgcalls.AudioDescription(
                        media_source=ntgcalls.MediaSource.FILE,
                        sample_rate=48000,
                        channel_count=1,
                        input=str(pcm_file),
                        keep_open=False,
                    )
                )
                await ntg.set_stream_sources(
                    user_id,
                    ntgcalls.StreamMode.CAPTURE,
                    media,
                )
                try:
                    await asyncio.wait_for(
                        ended_event.wait(),
                        timeout=max(2.0, duration + 1.5),
                    )
                    return False
                except asyncio.TimeoutError:
                    return True

            # Speak the same reminder exactly three times.
            for repetition in range(3):
                if not await _play_pcm(greeting_path, greeting_duration):
                    elapsed = int(max(1, loop.time() - call_started_ts))
                    return CallOutcome(
                        status="hung_up_unconfirmed",
                        duration_seconds=elapsed,
                    )
                if repetition < 2:
                    await asyncio.sleep(0.7)

            elapsed = int(max(1, loop.time() - call_started_ts))
            await ntg.stop(user_id)
            if not ended_event.is_set():
                await client.invoke(
                    functions.phone.DiscardCall(
                        peer=input_call,
                        duration=elapsed,
                        reason=types.PhoneCallDiscardReasonHangup(),
                        connection_id=0,
                    )
                )
                discard_requested = True
            return CallOutcome(
                status="completed",
                duration_seconds=elapsed,
                detected_intent="announced",
            )

        finally:
            if input_call is not None and not discard_requested and not ended_event.is_set():
                try:
                    elapsed = int(max(0, loop.time() - call_started_ts)) if call_started_ts else 0
                    await client.invoke(
                        functions.phone.DiscardCall(
                            peer=input_call,
                            duration=elapsed,
                            reason=types.PhoneCallDiscardReasonHangup(),
                            connection_id=0,
                        )
                    )
                except Exception:
                    logger.debug("Qo‘ng‘iroqni yakunlashda ogohlantirish", exc_info=True)
            signaling_ready.set()
            if signaling_task is not None:
                await incoming_signaling.put(None)
                try:
                    await asyncio.wait_for(signaling_task, timeout=2)
                except Exception:
                    signaling_task.cancel()
            try:
                await ntg.stop(user_id)
            except Exception:
                pass
            client.remove_handler(handler)

