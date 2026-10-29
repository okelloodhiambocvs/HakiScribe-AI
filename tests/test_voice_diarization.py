"""DIARIZATION alignment: turns parser, request shape, api log, migration.

Offline: monkeypatched requests.post, tmp databases, forced mock. Never
touches data/hakiscribe.db or the real storage/ folders.
"""

import json
import wave
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import backend.core.config as config
from backend.core.config import META_VOICE_MODEL
from backend.integrations.meta.voice_transcribe import (
    NO_TURNS_WARNING,
    TranscriptionError,
    parse_transcription_response,
    transcribe_audio_file,
)
from backend.repositories import api_calls_repo
from backend.services import ingestion_service
from backend.services.ingestion_service import validate_and_store_upload
from backend.services.transcription_service import transcribe_recording
from database.db import get_connection
from database.schema import SCHEMA_SQL, SCHEMA_VERSION, TRIGGERS_SQL, init_db
from frontend.views import transcribe_view

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "frontend" / "app.py"

SEED_KEYWORDS = [
    "Penal Code",
    "plea",
    "bail",
    "mention",
    "ruling",
    "adjourned",
    "prosecution",
    "complainant",
    "accused",
    "advocate",
    "magistrate",
    "charge sheet",
    "section 268",
]

_TURNS_FIXTURE = {
    "sessionId": "session-1",
    "transcript": "Full combined transcript here.",
    "audioDurationMs": 20000,
    "turns": [
        {"turnId": 2, "startMs": 8300, "endMs": 12500,
         "transcript": "Second speaker speaks.", "speaker": "B"},
        {"turnId": 0, "startMs": 400, "endMs": 4200,
         "transcript": "Court is now in session.", "speaker": "A"},
        {"turnId": 1, "startMs": 4500, "endMs": 8100,
         "transcript": "We must attend attend the mention.", "speaker": "A"},
    ],
}


def _make_wav(path, rate=44100, channels=2, seconds=0.5):
    frames = b"\x00" * int(rate * seconds) * channels * 2
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(frames)
    return path


class _FakeResponse:
    def __init__(self, status_code, payload=None, headers=None, body=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = body

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON here")
        return self._payload


def _real_path(monkeypatch, post):
    monkeypatch.setattr(
        "backend.integrations.meta.voice_transcribe.requests.post", post
    )
    monkeypatch.setattr(
        "backend.integrations.meta.voice_transcribe.config.is_configured",
        lambda: True,
    )


def _wav_recording_id(tmp_path):
    wav_path = _make_wav(tmp_path / "hearing.wav")
    return validate_and_store_upload(
        "hearing.wav",
        wav_path.read_bytes(),
        "Reviewer Amina",
        upload_dir=tmp_path / "uploads",
        db_path=tmp_path / "t.db",
    )["id"]


def _visible_text(app: AppTest) -> str:
    chunks = []
    for name in ("markdown", "caption", "info", "success", "warning", "text"):
        try:
            items = list(getattr(app, name))
        except Exception:
            continue
        for element in items:
            try:
                chunks.append(str(element.value))
            except Exception:
                pass
    return "\n".join(chunks)


def test_request_defaults_to_diarization_without_bias_or_keywords(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "META_VOICE_MODE", "")
    monkeypatch.setattr(config, "META_LANGUAGE_BIAS", "")
    monkeypatch.setattr(config, "get_keywords", lambda path=None: [])
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(json.loads(kwargs["files"]["request"][1]))
        return _FakeResponse(200, {"turns": [
            {"turnId": 0, "startMs": 0, "endMs": 1000,
             "transcript": "Hi.", "speaker": "A"},
        ]})

    _real_path(monkeypatch, fake_post)
    transcribe_audio_file(_make_wav(tmp_path / "in.wav"))
    assert captured == {
        "mode": "DIARIZATION",
        "model": META_VOICE_MODEL,
        "audioEncoding": "WAV",
    }


def test_request_includes_bias_and_keywords_when_configured(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "META_VOICE_MODE", "DIARIZATION")
    monkeypatch.setattr(config, "META_LANGUAGE_BIAS", "English, Kiswahili")
    monkeypatch.setattr(config, "get_keywords", lambda path=None: ["plea", "bail"])
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(json.loads(kwargs["files"]["request"][1]))
        return _FakeResponse(200, {"turns": [
            {"turnId": 0, "startMs": 0, "endMs": 1000,
             "transcript": "Hi.", "speaker": "A"},
        ]})

    _real_path(monkeypatch, fake_post)
    transcribe_audio_file(_make_wav(tmp_path / "in.wav"))
    assert captured["mode"] == "DIARIZATION"
    assert captured["languageBias"] == ["English", "Kiswahili"]
    assert captured["keywords"] == ["plea", "bail"]


def test_seed_keywords_file_has_court_terms():
    assert config.get_keywords() == SEED_KEYWORDS


def test_keywords_capped_dropped_and_missing(tmp_path):
    lines = ["# court terms", "", "x" * 41] + [f"term-{i}" for i in range(60)]
    keywords_file = tmp_path / "keywords.txt"
    keywords_file.write_text("\n".join(lines), encoding="utf-8")
    terms = config.get_keywords(keywords_file)
    assert len(terms) == 50
    assert terms[0] == "term-0"
    assert all(len(term) <= 40 for term in terms)
    assert config.get_keywords(tmp_path / "absent.txt") == []


def test_parser_maps_turns_to_segments():
    segments, warning = parse_transcription_response(_TURNS_FIXTURE)
    assert warning is None
    assert [s["idx"] for s in segments] == [0, 1, 2]
    assert [s["start_sec"] for s in segments] == [0.4, 4.5, 8.3]
    assert [s["end_sec"] for s in segments] == [4.2, 8.1, 12.5]
    assert [s["speaker"] for s in segments] == [
        "Speaker A", "Speaker A", "Speaker B",
    ]
    assert [s["speaker_label"] for s in segments] == ["A", "A", "B"]
    assert all(s["confidence"] is None for s in segments)
    assert segments[1]["text_original"] == "We must attend attend the mention."


def test_parser_empty_turns_yields_unknown_segment_with_warning():
    segments, warning = parse_transcription_response(
        {"transcript": "Hello there.", "audioDurationMs": 5000, "turns": []}
    )
    assert warning == NO_TURNS_WARNING
    assert len(segments) == 1
    only = segments[0]
    assert only["speaker"] == "UNKNOWN"
    assert only["speaker_label"] is None
    assert only["start_sec"] == 0.0
    assert only["end_sec"] == 5.0
    assert only["text_original"] == "Hello there."
    assert only["confidence"] is None


def test_parser_empty_everything_raises():
    with pytest.raises(TranscriptionError) as exc_info:
        parse_transcription_response({"turns": [], "transcript": ""})
    assert "top-level keys" in str(exc_info.value)
    with pytest.raises(TranscriptionError):
        parse_transcription_response({})
    with pytest.raises(TranscriptionError):
        parse_transcription_response("not an object")


def test_service_persists_turns_verbatim_with_labels(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    recording_id = _wav_recording_id(tmp_path)

    def fake_post(url, **kwargs):
        return _FakeResponse(200, _TURNS_FIXTURE)

    _real_path(monkeypatch, fake_post)
    result = transcribe_recording(recording_id, force_mock=False, db_path=db)
    assert result["status"] == "real"
    assert result["warning"] is None
    assert result["segment_count"] == 3
    saved = {s["idx"]: s for s in result["segments"]}
    assert saved[1]["text_original"] == "We must attend attend the mention."
    assert saved[1]["text_current"] == "We must attend attend the mention."
    assert saved[2]["speaker"] == "Speaker B"
    assert saved[2]["speaker_label"] == "B"
    assert all(s["confidence"] is None for s in result["segments"])


def _api_key_free(rows, fake_key):
    blob = json.dumps(rows, ensure_ascii=False, default=str)
    assert fake_key not in blob


def test_api_call_logged_on_success(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    recording_id = _wav_recording_id(tmp_path)
    monkeypatch.setattr(config, "META_VOICE_MODE", "DIARIZATION")
    fake_key = "fake-key-abc-999"
    monkeypatch.setattr(
        "backend.integrations.meta.voice_transcribe.config.get_meta_key",
        lambda: fake_key,
    )

    def fake_post(url, **kwargs):
        return _FakeResponse(
            200, _TURNS_FIXTURE, headers={"x-request-id": "req-9"}
        )

    _real_path(monkeypatch, fake_post)
    transcribe_recording(recording_id, force_mock=False, db_path=db)
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "meta"
    assert row["model"] == META_VOICE_MODEL
    assert row["endpoint_path"] == "/asr/transcribe"
    assert row["mode"] == "DIARIZATION"
    assert row["recording_id"] == recording_id
    assert row["http_status"] == 200
    assert row["ok"] == 1
    assert row["latency_ms"] is not None and row["latency_ms"] >= 0
    assert row["audio_bytes"] > 0
    assert abs(row["audio_ms"] - 500) <= 5
    assert row["request_id"] == "req-9"
    assert row["error_code"] is None
    _api_key_free(rows, fake_key)


def test_api_calls_logged_for_429_then_success(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    recording_id = _wav_recording_id(tmp_path)
    monkeypatch.setattr(config, "META_VOICE_MODE", "DIARIZATION")
    responses = [
        _FakeResponse(429, headers={"Retry-After": "0"}, body="slow down"),
        _FakeResponse(200, _TURNS_FIXTURE),
    ]
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return responses[len(calls) - 1]

    _real_path(monkeypatch, fake_post)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    result = transcribe_recording(recording_id, force_mock=False, db_path=db)
    assert result["status"] == "real"
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert len(rows) == 2
    newest, oldest = rows
    assert oldest["http_status"] == 429
    assert oldest["ok"] == 0
    assert oldest["error_code"] == "HTTP_429"
    assert newest["http_status"] == 200
    assert newest["ok"] == 1
    assert newest["error_code"] is None
    assert all(row["recording_id"] == recording_id for row in rows)


def test_api_call_logged_for_400_without_key_leak(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    recording_id = _wav_recording_id(tmp_path)
    monkeypatch.setattr(config, "META_VOICE_MODE", "DIARIZATION")
    fake_key = "fake-key-abc-999"
    monkeypatch.setattr(
        "backend.integrations.meta.voice_transcribe.config.get_meta_key",
        lambda: fake_key,
    )

    def fake_post(url, **kwargs):
        return _FakeResponse(400, body=f"rejected {fake_key} here")

    _real_path(monkeypatch, fake_post)
    with pytest.raises(TranscriptionError) as exc_info:
        transcribe_recording(recording_id, force_mock=False, db_path=db)
    assert fake_key not in str(exc_info.value)
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert len(rows) == 1
    assert rows[0]["http_status"] == 400
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "HTTP_400"
    assert rows[0]["recording_id"] == recording_id
    _api_key_free(rows, fake_key)


def _make_v2_database(db):
    """Build a schema-version-2 database with triggers and one transcript."""
    conn = get_connection(db)
    try:
        conn.executescript(SCHEMA_SQL)
        for column in (
            "transcription_source",
            "transcription_model",
            "transcription_raw_json",
            "transcribed_at",
        ):
            conn.execute(f"ALTER TABLE recordings ADD COLUMN {column} TEXT")
        conn.executescript(TRIGGERS_SQL)
        cur = conn.execute(
            """INSERT INTO recordings
               (filename, stored_path, sha256, size_bytes, uploaded_by,
                transcription_source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("v2.mp3", "storage/uploads/v2.mp3", "v2-sha", 64,
             "Reviewer Amina", "mock"),
        )
        rec_id = cur.lastrowid
        conn.execute(
            """INSERT INTO segments
               (recording_id, idx, start_sec, end_sec, speaker, text_original,
                text_current)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rec_id, 0, 0.0, 1.0, "MAGISTRATE", "Kept verbatim.", "Kept verbatim."),
        )
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
    finally:
        conn.close()
    return rec_id


def test_migration_v2_to_latest_keeps_data(tmp_path):
    db = tmp_path / "v2.db"
    rec_id = _make_v2_database(db)
    init_db(db)
    conn = get_connection(db)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
        flag_cols = {row[1] for row in conn.execute("PRAGMA table_info(flags)")}
        assert {
            "suggestion",
            "related_segment_id",
            "prompt_version",
            "evidence_verified",
        } <= flag_cols
        (runs,) = conn.execute("SELECT COUNT(*) FROM ai_runs").fetchone()
        assert runs == 0
        rec = conn.execute(
            "SELECT * FROM recordings WHERE id = ?", (rec_id,)
        ).fetchone()
        assert rec["filename"] == "v2.mp3"
        assert rec["transcription_source"] == "mock"
        seg = conn.execute(
            "SELECT * FROM segments WHERE recording_id = ?", (rec_id,)
        ).fetchone()
        assert seg["text_original"] == "Kept verbatim."
        assert seg["speaker_label"] is None
        (calls,) = conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()
        assert calls == 0
    finally:
        conn.close()


def test_voice_mode_validation(monkeypatch):
    monkeypatch.setattr(config, "META_VOICE_MODE", "")
    assert config.get_voice_mode() == "DIARIZATION"
    monkeypatch.setattr(config, "META_VOICE_MODE", "push_to_talk")
    assert config.get_voice_mode() == "PUSH_TO_TALK"
    monkeypatch.setattr(config, "META_VOICE_MODE", "BOGUS")
    with pytest.raises(ValueError, match="META_VOICE_MODE"):
        config.get_voice_mode()


def test_apptest_renders_speaker_a_badges(tmp_path, monkeypatch):
    db_path = tmp_path / "hakiscribe.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("HAKISCRIBE_DB_PATH", str(db_path))
    monkeypatch.setenv("HAKISCRIBE_UPLOAD_DIR", str(upload_dir))
    demo_wav = tmp_path / "demo.wav"
    demo_wav.write_bytes(b"synthetic-demo-audio")
    monkeypatch.setattr(ingestion_service, "DEMO_RECORDING_PATH", demo_wav)
    monkeypatch.setattr(transcribe_view, "is_configured", lambda: False)

    app = AppTest.from_file(str(APP_PATH))
    app.run()
    assert not app.exception
    app.text_input(key="reviewer_name").set_value("Reviewer Amina")
    app.run()
    assert not app.exception
    app.button(key="load_demo_recording").click()
    app.run()
    assert not app.exception
    app.button(key="transcribe_recording").click()
    app.run()
    app.run()
    assert not app.exception
    blob = _visible_text(app)
    assert "Speaker A" in blob
    assert "Show low confidence only" not in blob
