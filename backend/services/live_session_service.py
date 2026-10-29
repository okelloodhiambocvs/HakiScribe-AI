"""Live microphone sessions: realtime transcription in a background thread.

One session at a time, capped at 10 minutes. Audio streams to Meta's
realtime endpoint while captured PCM is also written to a local WAV;
on stop, a recording row (capture_source 'live') and the completed
turns persist as approximate segments. "Finalise with batch pass" runs
the normal guarded replace on the saved WAV. Consent is required:
consent_attested=True means all speakers have consented and this is a
synthetic or consented session. Failures record the exact error and no
text is ever invented.
"""

import asyncio
import hashlib
import json
import struct
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.core import config
from backend.core.errors import AudioCaptureError, RealtimeError
from backend.integrations.audio_capture import (
    SAMPLE_RATE,
    SoundDeviceSource,
    list_input_devices,
)
from backend.integrations.meta.realtime_transcribe import RealtimeClient
from backend.repositories import api_calls_repo, recordings_repo, segments_repo
from backend.services import transcription_service

LIVE_SESSION_MAX_SECONDS = 600
BYTES_PER_SECOND = SAMPLE_RATE * 2  # int16 mono


class _StreamingWavWriter:
    """Append-only WAV writer: header first, sizes patched on close."""

    def __init__(self, path: Path, samplerate: int = SAMPLE_RATE):
        self.path = path
        self.samplerate = samplerate
        self.data_bytes = 0
        self._handle = open(path, "wb")
        self._handle.write(
            struct.pack(
                "<4sI4s4sIHHIIHH4sI",
                b"RIFF",
                36,
                b"WAVE",
                b"fmt ",
                16,
                1,
                1,
                samplerate,
                samplerate * 2,
                2,
                16,
                b"data",
                0,
            )
        )

    def write(self, chunk: bytes) -> None:
        self._handle.write(chunk)
        self.data_bytes += len(chunk)

    def close(self) -> None:
        try:
            self._handle.seek(4)
            self._handle.write(struct.pack("<I", 36 + self.data_bytes))
            self._handle.seek(40)
            self._handle.write(struct.pack("<I", self.data_bytes))
        finally:
            self._handle.close()


class _LiveState:
    """Mutable session state; every access holds _LOCK."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.status = "idle"
        self.started_monotonic = None
        self.ended_monotonic = None
        self.partial = ""
        self.turns = []
        self.last_error = None
        self.note = None
        self.recording_id = None
        self.wav_path = None
        self.bytes_sent = 0
        self.server_session_id = None
        self.handshake_latency_ms = None
        self.finalized = False

    def snapshot(self) -> dict:
        started = self.started_monotonic
        if started is None:
            elapsed = 0.0
        else:
            end = self.ended_monotonic or time.monotonic()
            elapsed = max(0.0, end - started)
        return {
            "status": self.status,
            "elapsed_s": elapsed,
            "partial": self.partial,
            "turns": [dict(turn) for turn in self.turns],
            "turn_count": len(self.turns),
            "last_error": self.last_error,
            "note": self.note,
            "recording_id": self.recording_id,
            "wav_path": self.wav_path,
            "bytes_sent": self.bytes_sent,
            "server_session_id": self.server_session_id,
            "handshake_latency_ms": self.handshake_latency_ms,
        }


_LOCK = threading.Lock()
_STATE = _LiveState()
_THREAD: threading.Thread | None = None
_STOP_EVENT: threading.Event | None = None


def get_live_state() -> dict:
    """Return a copy of the current live session state."""
    with _LOCK:
        return _STATE.snapshot()


def list_microphones() -> list[dict]:
    """List microphone devices as [{index, name}]."""
    return list_input_devices()


def start_live_session(
    reviewer,
    consent_attested,
    device=None,
    db_path=None,
    upload_dir="storage/uploads",
    url=None,
    audio_source=None,
) -> dict:
    """Start one live session in a background thread; return its state.

    Raises ValueError when the reviewer name is empty, consent is not
    attested, or a session is already running. url/audio_source are
    extension points (probes and tests use a local server/file).
    """
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise ValueError("reviewer name is required")
    if not consent_attested:
        raise ValueError(
            "consent is required: confirm all speakers have consented; "
            "this is a synthetic or consented session"
        )
    global _STOP_EVENT, _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            raise ValueError("a live session is already running")
        _STATE.reset()
        _STATE.status = "connecting"
        _STATE.started_monotonic = time.monotonic()
        stop_event = threading.Event()
        _STOP_EVENT = stop_event
        _THREAD = threading.Thread(
            target=_thread_main,
            args=(
                reviewer,
                device,
                db_path,
                upload_dir,
                url,
                audio_source,
                stop_event,
            ),
            daemon=True,
        )
        _THREAD.start()
        return _STATE.snapshot()


def stop_live_session() -> dict:
    """Stop the running session (no-op when idle); return its state."""
    with _LOCK:
        stop_event = _STOP_EVENT
        thread = _THREAD
    if stop_event is not None:
        stop_event.set()
    if thread is not None:
        thread.join(timeout=20)
    with _LOCK:
        return _STATE.snapshot()


def finalise_live_session(recording_id, force_mock=False, db_path=None) -> dict:
    """Run the guarded batch pass over the saved live WAV.

    Refuses while a session runs; the guarded replace inside refuses
    once flags or corrections exist (TranscriptionLockedError).
    """
    with _LOCK:
        running = _THREAD is not None and _THREAD.is_alive()
    if running:
        raise ValueError("stop the live session before finalising")
    return transcription_service.retranscribe_recording(
        recording_id, force_mock=force_mock, db_path=db_path
    )


def _thread_main(
    reviewer, device, db_path, upload_dir, url, audio_source, stop_event
) -> None:
    """Thread entry: run the session coroutine, never leak exceptions."""
    try:
        asyncio.run(
            _session_coro(
                reviewer, device, db_path, upload_dir, url, audio_source,
                stop_event,
            )
        )
    except Exception as exc:  # last-resort guard; finalize already ran
        with _LOCK:
            prefix = f"{_STATE.last_error}; " if _STATE.last_error else ""
            _STATE.last_error = f"{prefix}session failed: {exc}"
            if _STATE.status in ("connecting", "live"):
                _STATE.status = "error"
            _STATE.ended_monotonic = _STATE.ended_monotonic or time.monotonic()


async def _session_coro(
    reviewer, device, db_path, upload_dir, url, audio_source, stop_event
) -> None:
    """Stream one session; finalize (persist) exactly once on every path."""
    upload_path = Path(upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    wav_path = upload_path / f"live_{stamp}_{uuid.uuid4().hex[:8]}.wav"
    if audio_source is not None:
        source = audio_source
    else:
        source = SoundDeviceSource(device=device)
    writer = _StreamingWavWriter(wav_path)
    context = {
        "bytes": 0,
        "open": {},
        "auto_turns": 0,
        "wav_path": str(wav_path),
        "reviewer": reviewer,
        "db_path": db_path,
        "error_code": None,
        "connected": False,
        "outcome": None,
    }
    with _LOCK:
        _STATE.wav_path = str(wav_path)

    def on_event(event) -> None:
        _handle_event(event, context)

    try:
        try:
            client = RealtimeClient(
                api_key=config.get_meta_key(),
                model=config.META_VOICE_MODEL,
                mode="DIARIZATION",
                language_bias=config.get_language_bias(),
                keywords=config.get_keywords(),
                on_event=on_event,
                url=url,
            )
        except RealtimeError as exc:
            with _LOCK:
                _STATE.last_error = str(exc)
            context["error_code"] = exc.error_code or "CONFIG_ERROR"
            context["outcome"] = "error"
            return
        try:
            source.start()
        except AudioCaptureError as exc:
            with _LOCK:
                _STATE.last_error = str(exc)
            context["error_code"] = "AUDIO_CAPTURE_ERROR"
            context["outcome"] = "error"
            return
        try:
            await asyncio.wait_for(
                _run_client(client, source, writer, context, stop_event),
                timeout=LIVE_SESSION_MAX_SECONDS,
            )
        except asyncio.TimeoutError:
            with _LOCK:
                _STATE.note = "10-minute session cap reached."
            context["outcome"] = "ended"
        except (RealtimeError, AudioCaptureError) as exc:
            with _LOCK:
                _STATE.last_error = str(exc)
            context["outcome"] = "error"
            context["error_code"] = (
                getattr(exc, "error_code", None) or "SESSION_ERROR"
            )
        else:
            with _LOCK:
                if stop_event.is_set() and _STATE.note is None:
                    _STATE.note = "Stopped."
            context["outcome"] = "ended"
    finally:
        try:
            source.stop()
        except Exception:
            pass
        try:
            writer.close()
        except Exception as exc:
            with _LOCK:
                prefix = f"{_STATE.last_error}; " if _STATE.last_error else ""
                _STATE.last_error = f"{prefix}wav write failed: {exc}"
        _finalize(context)


async def _run_client(client, source, writer, context, stop_event):
    """Bridge source frames to the client, counting bytes for our clock."""

    async def counted_frames():
        async for chunk in source.frames():
            if stop_event.is_set():
                break
            writer.write(chunk)
            context["bytes"] += len(chunk)
            with _LOCK:
                _STATE.bytes_sent = context["bytes"]
            yield chunk

    return await client.run(counted_frames(), stop_event=stop_event)


def _handle_event(event, context) -> None:
    """Fold one realtime event into state (holds _LOCK throughout)."""
    clock = context["bytes"] / BYTES_PER_SECOND
    with _LOCK:
        if event.type == "session":
            _STATE.status = "live"
            _STATE.server_session_id = event.session_id
            _STATE.handshake_latency_ms = event.latency_ms
            context["connected"] = True
        elif event.type == "speechStart":
            if event.turn_id is not None:
                turn_id = event.turn_id
            else:
                context["auto_turns"] += 1
                turn_id = f"auto-{context['auto_turns']}"
            context["open"][turn_id] = {
                "start": clock,
                "end": None,
                "speaker": None,
            }
            _STATE.partial = ""
        elif event.type == "transcript":
            if event.text:
                _STATE.partial = event.text
        elif event.type == "speaker":
            _apply_speaker(event, context)
        elif event.type == "speechEnd":
            if event.turn_id is not None:
                turn_id = event.turn_id
            elif context["open"]:
                turn_id = next(reversed(context["open"]))
            else:
                context["auto_turns"] += 1
                turn_id = f"auto-{context['auto_turns']}"
            entry = context["open"].setdefault(
                turn_id, {"start": None, "end": None, "speaker": None}
            )
            entry["end"] = clock
        elif event.type == "speechComplete":
            _complete_turn(event, context, clock)
            _STATE.partial = ""


def _apply_speaker(event, context) -> None:
    """Attach a DIARIZATION label to its span (caller holds _LOCK)."""
    label = event.speaker
    if not label:
        return
    if event.turn_id is not None and event.turn_id in context["open"]:
        context["open"][event.turn_id]["speaker"] = label
        return
    for turn in reversed(_STATE.turns):
        if turn["turn_id"] == event.turn_id:
            turn["speaker"] = f"Speaker {label}"
            turn["speaker_label"] = label
            return
    if context["open"]:
        last_id = next(reversed(context["open"]))
        context["open"][last_id]["speaker"] = label
    elif _STATE.turns:
        _STATE.turns[-1]["speaker"] = f"Speaker {label}"
        _STATE.turns[-1]["speaker_label"] = label


def _complete_turn(event, context, clock: float) -> None:
    """Append one completed turn (caller holds _LOCK)."""
    turn_id = event.turn_id
    entry = None
    if turn_id is not None:
        entry = context["open"].pop(turn_id, None)
    elif context["open"]:
        turn_id = next(reversed(context["open"]))
        entry = context["open"].pop(turn_id)
    if turn_id is None:
        context["auto_turns"] += 1
        turn_id = f"auto-{context['auto_turns']}"
    entry = entry or {}
    start = entry.get("start")
    end = entry.get("end")
    if start is None:
        start = clock
    if end is None or end < start:
        end = clock
    label = entry.get("speaker") or event.speaker
    speaker = f"Speaker {label}" if label else "UNKNOWN"
    _STATE.turns.append(
        {
            "turn_id": turn_id,
            "text": event.text or "",
            "speaker": speaker,
            "speaker_label": label,
            "start_s": start,
            "end_s": end,
            "approximate": True,
        }
    )


def _finalize(context) -> None:
    """Persist WAV/recording/segments/api row exactly once (sync)."""
    with _LOCK:
        if _STATE.finalized:
            return
        _STATE.finalized = True
        turns = [dict(turn) for turn in _STATE.turns]
        audio_bytes = context["bytes"]
        wav_path = Path(context["wav_path"])
        reviewer = context["reviewer"]
        db_path = context["db_path"]
        connected = context["connected"]
        error_code = context["error_code"]
        latency_ms = _STATE.handshake_latency_ms
        server_session_id = _STATE.server_session_id
    recording_id = None
    try:
        data = wav_path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        duration = audio_bytes / BYTES_PER_SECOND
        recording_id = recordings_repo.create_recording(
            filename=wav_path.name,
            stored_path=str(wav_path),
            sha256=digest,
            size_bytes=len(data),
            duration_sec=duration,
            uploaded_by=reviewer,
            synthetic_attestation=True,
            capture_source="live",
            db_path=db_path,
        )
        if turns:
            segments_repo.save_transcription(
                recording_id,
                [
                    {
                        "idx": index,
                        "start_sec": turn["start_s"],
                        "end_sec": turn["end_s"],
                        "speaker": turn["speaker"],
                        "speaker_label": turn["speaker_label"],
                        "confidence": None,
                        "text_original": turn["text"],
                        "is_approximate": 1,
                    }
                    for index, turn in enumerate(turns)
                ],
                source="real",
                model=config.META_VOICE_MODEL,
                raw_json=json.dumps(turns),
                db_path=db_path,
            )
    except Exception as exc:
        with _LOCK:
            prefix = f"{_STATE.last_error}; " if _STATE.last_error else ""
            _STATE.last_error = f"{prefix}finalize failed: {exc}"
        error_code = error_code or "FINALIZE_ERROR"
    try:
        api_calls_repo.create_api_call(
            provider="meta",
            model=config.META_VOICE_MODEL,
            endpoint_path="/asr/realtime",
            mode="DIARIZATION",
            recording_id=recording_id,
            http_status=101 if connected else None,
            ok=bool(connected and error_code is None),
            latency_ms=latency_ms,
            audio_bytes=audio_bytes,
            audio_ms=int(audio_bytes / (BYTES_PER_SECOND / 1000)),
            request_id=server_session_id,
            error_code=error_code,
            db_path=db_path,
        )
    except Exception:
        pass
    with _LOCK:
        _STATE.recording_id = recording_id
        if _STATE.status in ("connecting", "live"):
            _STATE.status = context.get("outcome") or "ended"
        _STATE.ended_monotonic = _STATE.ended_monotonic or time.monotonic()
