"""Meta realtime transcription client (async websocket, DIARIZATION).

Protocol (Meta quickstart): connect to
wss://api.meta.ai/v1/asr/realtime?sessionId=<uuid> (no auth header — it
is ignored), send the JSON config frame first, await the {"sessionId"}
reply, then stream 80 ms binary PCM frames (24 kHz mono int16, 3840
bytes). Server events are JSON text frames. No mid-session reconnect:
a dropped socket ends the session with an error; received turns are
kept by the caller. The API key never appears in messages or logs.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from backend.core.errors import RealtimeError

REALTIME_PATH = "/asr/realtime"
DEFAULT_BASE_URL = "wss://api.meta.ai/v1"
HANDSHAKE_TIMEOUT_SECONDS = 10.0
RECEIVE_POLL_SECONDS = 0.5
POST_AUDIO_DRAIN_SECONDS = 3.0
AUDIO_ENCODING = "PCM_24KHZ"


@dataclass(frozen=True)
class RealtimeEvent:
    """One typed realtime event (server message or session marker)."""

    type: str
    turn_id: Any = None
    text: str | None = None
    speaker: str | None = None
    session_id: str | None = None
    latency_ms: float | None = None
    raw: dict | None = None


def _first_present(payload: dict, *names):
    """Return the first non-None value among alias field names."""
    for name in names:
        if payload.get(name) is not None:
            return payload.get(name)
    return None


def parse_event(payload: object) -> RealtimeEvent:
    """Parse one server JSON message into a typed event."""
    if not isinstance(payload, dict):
        raise RealtimeError(f"realtime event is not a JSON object: {payload!r}")
    return RealtimeEvent(
        type=str(payload.get("type") or "unknown"),
        turn_id=_first_present(payload, "turnId", "turn_id"),
        text=_first_present(payload, "transcript", "text"),
        speaker=_first_present(payload, "speaker", "label"),
        raw=payload,
    )


class RealtimeClient:
    """Async realtime transcription session over one websocket."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        mode: str = "DIARIZATION",
        language_bias: list[str] | None = None,
        keywords: list[str] | None = None,
        on_event,
        url: str | None = None,
        session_id: str | None = None,
        handshake_timeout: float = HANDSHAKE_TIMEOUT_SECONDS,
    ):
        if not api_key:
            raise RealtimeError("realtime transcription needs an API key")
        self._api_key = api_key
        self._model = model
        self._mode = mode
        self._language_bias = list(language_bias or [])
        self._keywords = list(keywords or [])
        self._on_event = on_event
        self._base = (url or DEFAULT_BASE_URL).rstrip("/")
        self._client_session_id = session_id or str(uuid.uuid4())
        self._handshake_timeout = handshake_timeout

    def _config_frame(self) -> str:
        """Build the first-frame JSON (the only place the key is sent)."""
        frame = {
            "authorization": {"accessToken": f"Bearer {self._api_key}"},
            "audioEncoding": AUDIO_ENCODING,
            "model": self._model,
            "mode": self._mode,
            "partialMode": "CUMULATIVE",
            "emitAudioProgress": False,
        }
        if self._language_bias:
            frame["languageBias"] = list(self._language_bias)
        if self._keywords:
            frame["keywords"] = list(self._keywords)
        return json.dumps(frame)

    def _scrub(self, text: str) -> str:
        """Remove the API key from any message text."""
        if self._api_key:
            text = text.replace(self._api_key, "[REDACTED]")
        return text

    async def _emit(self, event: RealtimeEvent) -> None:
        """Deliver one event; supports sync or async callbacks."""
        result = self._on_event(event)
        if asyncio.iscoroutine(result):
            await result

    def _parse_message(self, message: object) -> RealtimeEvent | None:
        """Parse one socket message; None means ignorable (binary)."""
        if not isinstance(message, str):
            return None
        try:
            payload = json.loads(message)
        except ValueError as exc:
            raise RealtimeError(
                f"realtime event is not valid JSON: {message[:200]}"
            ) from exc
        return parse_event(payload)

    async def run(self, frame_source, stop_event=None) -> dict:
        """Stream frames until the source ends, stop is set, or an error.

        frame_source is an async iterable of bytes; stop_event is a
        threading.Event checked between frames and polls. Returns the
        handshake/session summary. Raises RealtimeError on connect,
        handshake, protocol, or socket failure.
        """
        uri = (
            f"{self._base}{REALTIME_PATH}"
            f"?sessionId={self._client_session_id}"
        )
        try:
            ws = await asyncio.wait_for(
                websockets.connect(uri), timeout=HANDSHAKE_TIMEOUT_SECONDS
            )
        except (TimeoutError, OSError) as exc:
            raise RealtimeError(
                f"realtime connection failed: {exc}",
                error_code="CONNECTION_ERROR",
            ) from exc
        except Exception as exc:
            raise RealtimeError(
                self._scrub(f"realtime connection failed: {exc}"),
                error_code="CONNECTION_ERROR",
            ) from exc
        frames_sent = 0
        audio_bytes = 0
        try:
            await ws.send(self._config_frame())
            server_session_id, latency_ms = await self._handshake(ws)
            await self._emit(
                RealtimeEvent(
                    type="session",
                    session_id=server_session_id,
                    latency_ms=latency_ms,
                    raw={"sessionId": server_session_id},
                )
            )
            sender_done = False

            async def _send_frames() -> None:
                nonlocal frames_sent, audio_bytes, sender_done
                try:
                    async for chunk in frame_source:
                        if stop_event is not None and stop_event.is_set():
                            break
                        await ws.send(chunk)
                        frames_sent += 1
                        audio_bytes += len(chunk)
                finally:
                    sender_done = True

            async def _receive_loop() -> None:
                quiet = 0.0
                while True:
                    if stop_event is not None and stop_event.is_set():
                        return
                    try:
                        message = await asyncio.wait_for(
                            ws.recv(), timeout=RECEIVE_POLL_SECONDS
                        )
                    except TimeoutError:
                        if sender_done:
                            quiet += RECEIVE_POLL_SECONDS
                            if quiet >= POST_AUDIO_DRAIN_SECONDS:
                                return
                        continue
                    except ConnectionClosed as exc:
                        if stop_event is not None and stop_event.is_set():
                            return
                        raise RealtimeError(
                            f"realtime connection dropped: {exc}",
                            error_code="CONNECTION_DROPPED",
                        ) from exc
                    quiet = 0.0
                    event = self._parse_message(message)
                    if event is None:
                        continue
                    if event.type == "error":
                        detail = event.text or event.raw
                        raise RealtimeError(
                            self._scrub(f"realtime server error: {detail}"),
                            error_code="SERVER_ERROR",
                        )
                    await self._emit(event)

            sender = asyncio.ensure_future(_send_frames())
            receiver = asyncio.ensure_future(_receive_loop())
            receiver_error = None
            try:
                await receiver
            except RealtimeError as exc:
                receiver_error = exc
            finally:
                if not sender.done():
                    sender.cancel()
                try:
                    await sender
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    if receiver_error is None and not (
                        stop_event is not None and stop_event.is_set()
                    ):
                        receiver_error = RealtimeError(
                            self._scrub(f"realtime send failed: {exc}"),
                            error_code="SEND_FAILED",
                        )
            if receiver_error is not None:
                raise receiver_error
            return {
                "server_session_id": server_session_id,
                "handshake_latency_ms": latency_ms,
                "frames_sent": frames_sent,
                "audio_bytes": audio_bytes,
            }
        finally:
            try:
                await ws.close()
            except Exception:
                pass

    async def _handshake(self, ws) -> tuple[str, float]:
        """Send config (already sent) and await the sessionId reply."""
        started = time.monotonic()
        deadline = started + self._handshake_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RealtimeError(
                    "realtime handshake timed out after "
                    f"{self._handshake_timeout:g} s",
                    error_code="HANDSHAKE_TIMEOUT",
                )
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except TimeoutError as exc:
                raise RealtimeError(
                    "realtime handshake timed out after "
                    f"{self._handshake_timeout:g} s",
                    error_code="HANDSHAKE_TIMEOUT",
                ) from exc
            except ConnectionClosed as exc:
                raise RealtimeError(
                    f"realtime handshake failed: connection closed ({exc.code})",
                    error_code="HANDSHAKE_CLOSED",
                ) from exc
            event = self._parse_message(message)
            if event is None:
                continue
            if event.type == "error":
                detail = event.text or event.raw
                raise RealtimeError(
                    self._scrub(f"realtime handshake rejected: {detail}"),
                    error_code="HANDSHAKE_REJECTED",
                )
            server_session_id = (event.raw or {}).get("sessionId")
            if server_session_id:
                latency_ms = (time.monotonic() - started) * 1000
                return str(server_session_id), latency_ms
