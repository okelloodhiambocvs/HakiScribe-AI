"""Meta realtime transcription client (async websocket, DIARIZATION).

Protocol (Meta quickstart): connect to
wss://api.meta.ai/v1/asr/realtime?sessionId=<uuid> (no auth header — it
is ignored), send the JSON config frame first, await the {"sessionId"}
reply, then stream 80 ms binary PCM frames (24 kHz mono int16, 3840
bytes). After the last frame, send {"type":"endStream"} and keep
receiving until the server closes normally (code 1000). A completion
timeout, server error, or abnormal close raises instead. No mid-session
reconnect: received turns are kept by the caller. The API key never
appears in messages or logs.
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
COMPLETION_TIMEOUT_SECONDS = 60.0
AUDIO_ENCODING = "PCM_24KHZ"
END_STREAM_MESSAGE = '{"type":"endStream"}'


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


def _close_code(exc: ConnectionClosed) -> int:
    """Close code without the deprecated ConnectionClosed.code property."""
    rcvd = getattr(exc, "rcvd", None)
    if rcvd is not None and rcvd.code is not None:
        return int(rcvd.code)
    sent = getattr(exc, "sent", None)
    if sent is not None and sent.code is not None:
        return int(sent.code)
    return 1006


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
        completion_timeout: float = COMPLETION_TIMEOUT_SECONDS,
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
        self._completion_timeout = completion_timeout

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
        """Run one session: handshake, stream, endStream, await close.

        frame_source is an async iterable of bytes; stop_event is a
        threading.Event checked between frames and polls. After the
        source is exhausted the client sends {"type":"endStream"} and
        keeps receiving until the server closes normally (code 1000).
        Returns the session summary with completed/close_code. Raises
        RealtimeError on connect, handshake, protocol, completion
        timeout, or abnormal socket closure.
        """
        uri = (
            f"{self._base}{REALTIME_PATH}"
            f"?sessionId={self._client_session_id}"
        )
        try:
            ws = await asyncio.wait_for(
                websockets.connect(uri), timeout=self._handshake_timeout
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
            sender_done_at: float | None = None
            endstream_sent = False
            completed = False
            close_code: int | None = None
            last_activity = time.monotonic()

            async def _send_frames() -> None:
                nonlocal frames_sent, audio_bytes
                nonlocal sender_done, sender_done_at, endstream_sent
                try:
                    async for chunk in frame_source:
                        if stop_event is not None and stop_event.is_set():
                            break
                        await ws.send(chunk)
                        frames_sent += 1
                        audio_bytes += len(chunk)
                    if stop_event is None or not stop_event.is_set():
                        await ws.send(END_STREAM_MESSAGE)
                        endstream_sent = True
                finally:
                    sender_done = True
                    sender_done_at = time.monotonic()

            async def _receive_loop() -> None:
                nonlocal completed, close_code, last_activity
                while True:
                    if stop_event is not None and stop_event.is_set():
                        return
                    if sender_done:
                        base = max(
                            sender_done_at or 0.0, last_activity
                        )
                        if time.monotonic() - base >= self._completion_timeout:
                            raise RealtimeError(
                                "realtime completion timed out: the server "
                                "did not close the session",
                                error_code="COMPLETION_TIMEOUT",
                            )
                    try:
                        message = await asyncio.wait_for(
                            ws.recv(), timeout=RECEIVE_POLL_SECONDS
                        )
                    except TimeoutError:
                        continue
                    except ConnectionClosed as exc:
                        if stop_event is not None and stop_event.is_set():
                            return
                        code = _close_code(exc)
                        if code == 1000 and endstream_sent:
                            completed = True
                            close_code = code
                            return
                        if code == 1000:
                            raise RealtimeError(
                                "realtime connection closed before all "
                                "audio was sent (code 1000)",
                                error_code="CONNECTION_DROPPED",
                            ) from exc
                        raise RealtimeError(
                            self._scrub(
                                "realtime connection closed abnormally "
                                f"(code {code})"
                            ),
                            error_code="CONNECTION_DROPPED",
                        ) from exc
                    last_activity = time.monotonic()
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

            loop = asyncio.get_running_loop()
            sender = loop.create_task(
                _send_frames(), name="hakiscribe-realtime-sender"
            )
            receiver = loop.create_task(
                _receive_loop(), name="hakiscribe-realtime-receiver"
            )
            receiver_error = None
            try:
                await receiver
            except RealtimeError as exc:
                receiver_error = exc
            finally:
                for task in (receiver, sender):
                    if not task.done():
                        task.cancel()
                results = None
                try:
                    results = await asyncio.gather(
                        receiver, sender, return_exceptions=True
                    )
                except asyncio.CancelledError:
                    results = None
                if results is not None:
                    sender_result = results[1]
                    if (
                        receiver_error is None
                        and not completed
                        and isinstance(sender_result, Exception)
                        and not isinstance(
                            sender_result, asyncio.CancelledError
                        )
                        and not (
                            stop_event is not None and stop_event.is_set()
                        )
                    ):
                        receiver_error = RealtimeError(
                            self._scrub(
                                f"realtime send failed: {sender_result}"
                            ),
                            error_code="SEND_FAILED",
                        )
            if receiver_error is not None:
                raise receiver_error
            return {
                "server_session_id": server_session_id,
                "handshake_latency_ms": latency_ms,
                "frames_sent": frames_sent,
                "audio_bytes": audio_bytes,
                "completed": completed,
                "close_code": close_code,
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
                    "realtime handshake failed: connection closed "
                    f"({_close_code(exc)})",
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
