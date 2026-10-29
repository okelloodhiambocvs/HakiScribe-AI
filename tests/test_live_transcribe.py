"""Offline live-microphone tests: fake websocket server, paced files, guards.

No network beyond localhost, no microphone needed. Every test uses an
isolated tmp database and upload folder; the fake key never leaves the
test process.
"""

import asyncio
import hashlib
import json
import socket
import sys
import threading
import time
import wave
from pathlib import Path

import pytest
import websockets

from backend.core.errors import AudioCaptureError, RealtimeError
from backend.integrations.audio_capture import (
    BLOCK_BYTES,
    FileSource,
    SoundDeviceSource,
    list_input_devices,
)
from backend.integrations.meta.realtime_transcribe import (
    RealtimeClient,
    RealtimeEvent,
)
from backend.repositories import (
    api_calls_repo,
    corrections_repo,
    recordings_repo,
    segments_repo,
)
from backend.repositories.segments_repo import TranscriptionLockedError
from backend.services import live_session_service
from database.db import get_connection
from database.schema import SCHEMA_VERSION, init_db

FAKE_KEY = "fake-live-key-123"
APP_PATH = Path(__file__).resolve().parent.parent / "frontend" / "app.py"

_FULL_TURN_SCRIPT = [
    "audio",
    {"type": "speechStart", "turnId": 3},
    "audio",
    {"type": "transcript", "turnId": 3, "transcript": "Mheshimiwa, kesi"},
    "audio",
    {"type": "speaker", "turnId": 3, "speaker": "A"},
    {"type": "speechEnd", "turnId": 3},
    {"type": "speechComplete", "turnId": 3,
     "transcript": "Mheshimiwa, kesi namba tano."},
]


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _write_wav(path, seconds=0.5, rate=24000, channels=1, width=2):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(width)
        wav_file.setframerate(rate)
        if width == 2:
            wav_file.writeframes(b"\x00\x01" * frames * channels)
        else:
            wav_file.writeframes(b"\x90" * frames * channels)


def _run(coro):
    """Run one coroutine to completion (tests stay sync)."""
    return asyncio.run(coro)


class _FakeRealtimeServer:
    """Scripted fake: records the first frame, replays scripted events."""

    def __init__(self, script):
        self.script = script
        self.first_frame = None
        self.binary_frames = []

    async def handler(self, websocket):
        self.first_frame = await websocket.recv()
        await websocket.send(json.dumps({"sessionId": "fake-session-1"}))
        for step in self.script:
            if step == "audio":
                message = await websocket.recv()
                self.binary_frames.append(message)
            else:
                await websocket.send(json.dumps(step))
        async for message in websocket:
            if isinstance(message, bytes):
                self.binary_frames.append(message)


async def _with_fake_server(script, client_factory):
    """Serve the script on localhost while the client runs."""
    server = _FakeRealtimeServer(script)
    port = _free_port()
    async with websockets.serve(server.handler, "127.0.0.1", port):
        result = await client_factory(f"ws://127.0.0.1:{port}")
    return server, result


def _serve_in_thread(script):
    """Run the fake server on a thread; return (server, url, stopper)."""
    server = _FakeRealtimeServer(script)
    port = _free_port()
    ready = threading.Event()
    holder = {}

    def _main():
        async def _serve():
            async with websockets.serve(server.handler, "127.0.0.1", port):
                ready.set()
                await holder["stop"].wait()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        holder["stop"] = asyncio.Event()
        holder["loop"] = loop
        try:
            loop.run_until_complete(_serve())
        finally:
            loop.close()

    thread = threading.Thread(target=_main, daemon=True)
    thread.start()
    assert ready.wait(timeout=10), "fake server did not start"

    def _stop():
        holder["loop"].call_soon_threadsafe(holder["stop"].set)
        thread.join(timeout=10)

    return server, f"ws://127.0.0.1:{port}", _stop


def _start_kwargs(monkeypatch, tmp_path, url, wav_seconds=0.5):
    """Patch the key; build isolated start kwargs with a paced file."""
    monkeypatch.setattr("backend.core.config.get_meta_key", lambda: FAKE_KEY)
    wav_path = tmp_path / "live-input.wav"
    _write_wav(wav_path, seconds=wav_seconds)
    return {
        "db_path": tmp_path / "live.db",
        "upload_dir": tmp_path / "uploads",
        "url": url,
        "audio_source": FileSource(wav_path, realtime=False),
    }


def _wait_for(predicate, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = live_session_service.get_live_state()
        if predicate(state):
            return state
        time.sleep(0.02)
    return live_session_service.get_live_state()


def test_client_sends_exact_first_frame_and_pcm_frames():
    stop = threading.Event()

    async def go(url):
        events = []
        client = RealtimeClient(
            api_key=FAKE_KEY,
            model="muse-voice-transcribe-1.0",
            mode="DIARIZATION",
            language_bias=["English"],
            keywords=["bail"],
            on_event=events.append,
            url=url,
        )

        async def frames():
            yield b"\x01\x02" * (BLOCK_BYTES // 2)
            stop.set()

        summary = await client.run(frames(), stop_event=stop)
        return summary, events

    server, (summary, events) = _run(_with_fake_server(["audio"], go))
    first = json.loads(server.first_frame)
    assert first["authorization"] == {"accessToken": f"Bearer {FAKE_KEY}"}
    assert first["audioEncoding"] == "PCM_24KHZ"
    assert first["model"] == "muse-voice-transcribe-1.0"
    assert first["mode"] == "DIARIZATION"
    assert first["partialMode"] == "CUMULATIVE"
    assert first["emitAudioProgress"] is False
    assert first["languageBias"] == ["English"]
    assert first["keywords"] == ["bail"]
    assert BLOCK_BYTES == 3840
    assert server.binary_frames
    assert all(len(frame) == 3840 for frame in server.binary_frames)
    assert summary["server_session_id"] == "fake-session-1"
    assert summary["frames_sent"] == 1
    assert summary["audio_bytes"] == BLOCK_BYTES
    assert FAKE_KEY not in json.dumps(events, default=str)


def test_client_emits_partials_complete_and_speaker():
    stop = threading.Event()
    script = [
        "audio",
        {"type": "speechStart", "turnId": 7},
        {"type": "transcript", "turnId": 7, "transcript": "Mheshimiwa"},
        {"type": "speaker", "turnId": 7, "speaker": "B"},
        {"type": "speechEnd", "turnId": 7},
        {"type": "speechComplete", "turnId": 7,
         "transcript": "Mheshimiwa, kesi namba tano."},
    ]

    async def go(url):
        events = []

        def on_event(event):
            events.append(event)
            if event.type == "speechComplete":
                stop.set()

        client = RealtimeClient(
            api_key=FAKE_KEY,
            model="muse-voice-transcribe-1.0",
            on_event=on_event,
            url=url,
        )

        async def frames():
            while not stop.is_set():
                yield b"\x00" * BLOCK_BYTES
                await asyncio.sleep(0.01)

        summary = await client.run(frames(), stop_event=stop)
        return summary, events

    server, (summary, events) = _run(_with_fake_server(script, go))
    first = json.loads(server.first_frame)
    assert "languageBias" not in first
    assert "keywords" not in first
    kinds = [event.type for event in events]
    assert kinds[0] == "session"
    assert "speechStart" in kinds and "speechComplete" in kinds
    partials = [item for item in events if item.type == "transcript"]
    assert partials and partials[0].text == "Mheshimiwa"
    complete = [item for item in events if item.type == "speechComplete"][0]
    assert complete.turn_id == 7
    assert complete.text == "Mheshimiwa, kesi namba tano."
    speaker = [item for item in events if item.type == "speaker"][0]
    assert speaker.speaker == "B"
    assert summary["server_session_id"] == "fake-session-1"


def test_client_error_event_raises_and_keeps_received():
    script = [
        "audio",
        {"type": "transcript", "turnId": 1, "transcript": "half a turn"},
        {"type": "error", "transcript": "audio too noisy"},
    ]

    async def go(url):
        events = []
        client = RealtimeClient(
            api_key=FAKE_KEY,
            model="muse-voice-transcribe-1.0",
            on_event=events.append,
            url=url,
        )

        async def frames():
            yield b"\x00" * BLOCK_BYTES

        with pytest.raises(RealtimeError, match="audio too noisy") as exc_info:
            await client.run(frames())
        assert exc_info.value.error_code == "SERVER_ERROR"
        return events

    _server, events = _run(_with_fake_server(script, go))
    kinds = [event.type for event in events]
    assert kinds[0] == "session"
    assert "transcript" in kinds


async def _expect_handshake_failure(handler):
    port = _free_port()
    async with websockets.serve(handler, "127.0.0.1", port):
        client = RealtimeClient(
            api_key=FAKE_KEY,
            model="m",
            on_event=lambda event: None,
            url=f"ws://127.0.0.1:{port}",
            handshake_timeout=0.2,
        )

        async def frames():
            yield b"\x00" * BLOCK_BYTES

        with pytest.raises(RealtimeError, match="timed out"):
            await client.run(frames())


def test_client_handshake_timeout_and_missing_session_id():
    async def silent(websocket):
        await websocket.recv()
        await asyncio.sleep(30)

    async def no_session(websocket):
        await websocket.recv()
        await websocket.send(json.dumps({"status": "ok"}))
        await asyncio.sleep(30)

    async def both():
        await _expect_handshake_failure(silent)
        await _expect_handshake_failure(no_session)

    _run(both())


def test_handle_event_tracks_partial_then_completed_turn():
    context = {"bytes": 0, "open": {}, "auto_turns": 0, "connected": False}
    context["bytes"] = 4800
    live_session_service._handle_event(
        RealtimeEvent(type="speechStart", turn_id=1), context
    )
    live_session_service._handle_event(
        RealtimeEvent(type="transcript", turn_id=1, text="half a turn"),
        context,
    )
    assert live_session_service.get_live_state()["partial"] == "half a turn"
    context["bytes"] = 9600
    live_session_service._handle_event(
        RealtimeEvent(type="speechEnd", turn_id=1), context
    )
    live_session_service._handle_event(
        RealtimeEvent(type="speechComplete", turn_id=1, text="full turn"),
        context,
    )
    state = live_session_service.get_live_state()
    assert state["partial"] == ""
    turn = state["turns"][-1]
    assert turn["text"] == "full turn"
    assert turn["speaker"] == "UNKNOWN"
    assert turn["speaker_label"] is None
    assert turn["start_s"] == pytest.approx(0.1)
    assert turn["end_s"] == pytest.approx(0.2)


def test_sounddevice_missing_error_is_friendly(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    source = SoundDeviceSource(device=0)
    with pytest.raises(AudioCaptureError, match="sounddevice is not installed"):
        source.start()
    with pytest.raises(AudioCaptureError, match="sounddevice is not installed"):
        list_input_devices()


def test_sounddevice_missing_device_error_is_friendly(monkeypatch):
    class _FakeSD:
        def InputStream(self, **kwargs):
            raise RuntimeError("no such device")

    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSD())
    source = SoundDeviceSource(device=99)

    async def go():
        source.start()

    with pytest.raises(AudioCaptureError, match="cannot open microphone"):
        _run(go())


def test_list_input_devices_filters(monkeypatch):
    class _FakeSD:
        def query_devices(self):
            return [
                {"name": "Mic", "max_input_channels": 2},
                {"name": "Speakers", "max_input_channels": 0},
            ]

    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSD())
    assert list_input_devices() == [{"index": 0, "name": "Mic"}]


def test_file_source_blocks_are_wire_format(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, seconds=0.5, rate=16000)
    source = FileSource(wav_path, realtime=False)
    source.start()

    async def collect():
        return [chunk async for chunk in source.frames()]

    blocks = _run(collect())
    assert len(blocks) == 7  # 0.5 s -> 12000 samples -> 6.25 blocks
    assert all(len(block) == BLOCK_BYTES for block in blocks)
    assert any(block != b"\x00" * BLOCK_BYTES for block in blocks)


def test_file_source_resamples_8bit_stereo(tmp_path):
    wav_path = tmp_path / "clip8.wav"
    _write_wav(wav_path, seconds=0.24, rate=8000, channels=2, width=1)
    source = FileSource(wav_path, realtime=False)
    source.start()

    async def collect():
        return [chunk async for chunk in source.frames()]

    blocks = _run(collect())
    assert len(blocks) == 3  # 1920 samples -> 5760 @24k -> 3 blocks
    assert all(len(block) == BLOCK_BYTES for block in blocks)


def test_file_source_paces_in_real_time(tmp_path):
    wav_path = tmp_path / "pace.wav"
    _write_wav(wav_path, seconds=0.16)  # 3840 samples -> 2 blocks
    source = FileSource(wav_path, realtime=True)
    source.start()

    async def collect():
        started = time.monotonic()
        blocks = [chunk async for chunk in source.frames()]
        return blocks, time.monotonic() - started

    blocks, elapsed = _run(collect())
    assert len(blocks) == 2
    assert elapsed >= 0.1


def test_file_source_missing_file(tmp_path):
    source = FileSource(tmp_path / "nope.wav")
    with pytest.raises(AudioCaptureError, match="not found"):
        source.start()


def test_migrate_v6_to_v7_keeps_data(tmp_path):
    db_path = tmp_path / "v6.db"
    conn = get_connection(db_path)
    try:
        conn.executescript("""
        CREATE TABLE recordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            duration_sec REAL,
            uploaded_by TEXT NOT NULL,
            synthetic_attestation INTEGER NOT NULL DEFAULT 1,
            transcription_source TEXT,
            transcription_model TEXT,
            transcription_raw_json TEXT,
            transcribed_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id INTEGER NOT NULL REFERENCES recordings(id)
                ON DELETE CASCADE,
            idx INTEGER NOT NULL,
            start_sec REAL NOT NULL,
            end_sec REAL NOT NULL,
            speaker TEXT NOT NULL DEFAULT 'UNKNOWN',
            speaker_label TEXT,
            confidence REAL,
            language TEXT NOT NULL DEFAULT 'mixed',
            text_original TEXT NOT NULL,
            text_current TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT,
            UNIQUE(recording_id, idx)
        );
        """)
        conn.execute(
            "INSERT INTO recordings (filename, stored_path, sha256,"
            " size_bytes, uploaded_by) VALUES (?, ?, ?, ?, ?)",
            ("a.wav", "p", "s", 8, "R"),
        )
        conn.execute(
            "INSERT INTO segments (recording_id, idx, start_sec, end_sec,"
            " text_original, text_current) VALUES (1, 0, 0.0, 1.0, ?, ?)",
            ("hi", "hi"),
        )
        conn.execute("PRAGMA user_version = 6")
        conn.commit()
    finally:
        conn.close()
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
        recording = conn.execute("SELECT * FROM recordings").fetchone()
        assert recording["filename"] == "a.wav"
        assert recording["capture_source"] == "upload"
        segment = conn.execute("SELECT * FROM segments").fetchone()
        assert segment["text_original"] == "hi"
        assert segment["is_approximate"] == 0
    finally:
        conn.close()


def test_stop_persists_wav_recording_and_approximate_segments(
    monkeypatch, tmp_path
):
    server, url, stop_server = _serve_in_thread(_FULL_TURN_SCRIPT)
    try:
        kwargs = _start_kwargs(monkeypatch, tmp_path, url)
        live_session_service.start_live_session("Reviewer Amina", True, **kwargs)
        state = _wait_for(lambda s: s["turn_count"] >= 1)
        assert state["turn_count"] == 1
        assert state["status"] == "live"
        state = live_session_service.stop_live_session()
        assert state["status"] == "ended"
        assert state["recording_id"] is not None
        assert FAKE_KEY not in json.dumps(state, default=str)

        recording = recordings_repo.get_recording(
            state["recording_id"], db_path=kwargs["db_path"]
        )
        assert recording["capture_source"] == "live"
        assert recording["synthetic_attestation"] == 1
        assert recording["uploaded_by"] == "Reviewer Amina"
        assert recording["transcription_source"] == "real"
        wav_path = Path(recording["stored_path"])
        assert wav_path.is_file()
        assert wav_path.read_bytes()[:4] == b"RIFF"
        with wave.open(str(wav_path), "rb") as wav_file:
            assert wav_file.getframerate() == 24000
            assert wav_file.getnchannels() == 1
            assert wav_file.getsampwidth() == 2
        assert recording["sha256"] == hashlib.sha256(
            wav_path.read_bytes()
        ).hexdigest()

        segments = segments_repo.list_segments(
            state["recording_id"], db_path=kwargs["db_path"]
        )
        assert len(segments) == 1
        segment = segments[0]
        assert segment["text_original"] == "Mheshimiwa, kesi namba tano."
        assert segment["speaker"] == "Speaker A"
        assert segment["speaker_label"] == "A"
        assert segment["confidence"] is None
        assert segment["is_approximate"] == 1
        assert segment["end_sec"] >= segment["start_sec"] >= 0

        calls = api_calls_repo.list_recent_api_calls(
            limit=5, db_path=kwargs["db_path"]
        )
        assert calls and calls[0]["endpoint_path"] == "/asr/realtime"
        assert calls[0]["ok"] == 1
        assert calls[0]["recording_id"] == state["recording_id"]
        assert FAKE_KEY not in json.dumps(calls, default=str)
    finally:
        live_session_service.stop_live_session()
        stop_server()


def test_error_event_ends_session_with_error_and_no_text(
    monkeypatch, tmp_path
):
    script = [
        "audio",
        {"type": "error", "transcript": "audio too noisy"},
    ]
    server, url, stop_server = _serve_in_thread(script)
    try:
        kwargs = _start_kwargs(monkeypatch, tmp_path, url)
        live_session_service.start_live_session("Reviewer Amina", True, **kwargs)
        state = _wait_for(lambda s: s["status"] in ("ended", "error"))
        assert state["status"] == "error"
        assert "audio too noisy" in state["last_error"]
        assert state["turns"] == []
        assert state["partial"] == ""
        live_session_service.stop_live_session()
        segments = segments_repo.list_segments(
            state["recording_id"], db_path=kwargs["db_path"]
        )
        assert segments == []
    finally:
        live_session_service.stop_live_session()
        stop_server()


def test_start_requires_consent_and_reviewer(tmp_path):
    with pytest.raises(ValueError, match="consent is required"):
        live_session_service.start_live_session(
            "Reviewer Amina", False, db_path=tmp_path / "x.db"
        )
    with pytest.raises(ValueError, match="reviewer name is required"):
        live_session_service.start_live_session(
            "  ", True, db_path=tmp_path / "x.db"
        )


def test_session_cap_ends_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(live_session_service, "LIVE_SESSION_MAX_SECONDS", 0.2)
    server, url, stop_server = _serve_in_thread([])
    try:
        kwargs = _start_kwargs(monkeypatch, tmp_path, url)
        live_session_service.start_live_session("Reviewer Amina", True, **kwargs)
        state = _wait_for(lambda s: s["status"] == "ended", timeout=10)
        assert state["status"] == "ended"
        assert "cap" in (state["note"] or "")
        assert state["recording_id"] is not None
    finally:
        live_session_service.stop_live_session()
        stop_server()


def test_finalise_refuses_when_corrections_exist(monkeypatch, tmp_path):
    server, url, stop_server = _serve_in_thread(_FULL_TURN_SCRIPT)
    try:
        kwargs = _start_kwargs(monkeypatch, tmp_path, url)
        live_session_service.start_live_session("Reviewer Amina", True, **kwargs)
        _wait_for(lambda s: s["turn_count"] >= 1)
        live_session_service.stop_live_session()
        recording_id = live_session_service.get_live_state()["recording_id"]
        segments = segments_repo.list_segments(
            recording_id, db_path=kwargs["db_path"]
        )
        corrections_repo.create_correction(
            segments[0]["id"],
            None,
            "before",
            "after",
            "Reviewer Amina",
            "EDIT_TEXT",
            reason="why",
            db_path=kwargs["db_path"],
        )
        with pytest.raises(TranscriptionLockedError):
            live_session_service.finalise_live_session(
                recording_id, force_mock=True, db_path=kwargs["db_path"]
            )
    finally:
        live_session_service.stop_live_session()
        stop_server()


def test_live_view_idle_renders():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(APP_PATH))
    app.session_state["current_step"] = "live"
    app.run()
    assert not app.exception
