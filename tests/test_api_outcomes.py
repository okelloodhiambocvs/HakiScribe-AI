"""API outcome semantics: usable results, failures, retries, evidence.

Offline: monkeypatched requests.post, tmp databases, isolated ledgers.
ok=1 means a validated, usable result — never bare HTTP success.
"""

import importlib.util
import json
import sqlite3
import wave
from pathlib import Path

import pytest

from backend.integrations.meta import voice_transcribe
from backend.integrations.meta.spark_client import SparkError
from backend.integrations.meta.voice_transcribe import TranscriptionError
from backend.repositories import (
    ai_runs_repo,
    api_calls_repo,
    recordings_repo,
    segments_repo,
)
from backend.services import ingestion_service
from backend.services.review_service import run_review
from backend.services.transcription_service import (
    retranscribe_recording,
    transcribe_recording,
)

ROOT = Path(__file__).resolve().parent.parent
FAKE_KEY = "outcome-fake-key-456"


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


def _make_wav(path, seconds=0.5):
    frames = int(24000 * seconds)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(b"\x00\x01" * frames)
    return path


def _wav_recording_id(tmp_path):
    wav_path = _make_wav(tmp_path / "hearing.wav")
    return ingestion_service.validate_and_store_upload(
        "hearing.wav",
        wav_path.read_bytes(),
        "Reviewer Amina",
        upload_dir=tmp_path / "uploads",
        db_path=tmp_path / "t.db",
    )["id"]


def _real_voice(monkeypatch, post):
    monkeypatch.setattr(
        "backend.integrations.meta.voice_transcribe.requests.post", post
    )
    monkeypatch.setattr(
        "backend.integrations.meta.voice_transcribe.config.is_configured",
        lambda: True,
    )


def _real_spark(monkeypatch, post):
    monkeypatch.setattr(
        "backend.integrations.meta.spark_client.requests.post", post
    )
    monkeypatch.setattr(
        "backend.integrations.meta.spark_client.config.is_configured",
        lambda: True,
    )


def _recording_with_segments(tmp_path):
    recording = ingestion_service.validate_and_store_upload(
        "hearing.mp3",
        b"synthetic-audio",
        "Reviewer Amina",
        upload_dir=tmp_path / "uploads",
        db_path=tmp_path / "t.db",
    )
    db = tmp_path / "t.db"
    segments_repo.create_segments(
        recording["id"],
        [
            {
                "idx": 0,
                "start_sec": 0.0,
                "end_sec": 4.0,
                "speaker": "Speaker A",
                "speaker_label": "A",
                "text_original": "Court is now in session.",
            }
        ],
        db_path=db,
    )
    return recording["id"], db


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_batch_malformed_json_records_parse_error(tmp_path, monkeypatch):
    recording_id = _wav_recording_id(tmp_path)
    db = tmp_path / "t.db"

    def fake_post(url, **kwargs):
        return _FakeResponse(200, None, body="<html>not json</html>")

    _real_voice(monkeypatch, fake_post)
    with pytest.raises(TranscriptionError, match="not valid JSON"):
        transcribe_recording(recording_id, db_path=db)
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert len(rows) == 1
    assert rows[0]["http_status"] == 200
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "PARSE_ERROR"
    assert segments_repo.list_segments(recording_id, db_path=db) == []


def test_batch_missing_fields_records_invalid_response(tmp_path, monkeypatch):
    recording_id = _wav_recording_id(tmp_path)
    db = tmp_path / "t.db"
    _real_voice(
        monkeypatch, lambda url, **kwargs: _FakeResponse(200, {})
    )
    with pytest.raises(TranscriptionError, match="top-level keys"):
        transcribe_recording(recording_id, db_path=db)
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert len(rows) == 1
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "INVALID_RESPONSE"


def test_batch_bad_turn_shape_hides_transcript(tmp_path, monkeypatch):
    recording_id = _wav_recording_id(tmp_path)
    db = tmp_path / "t.db"
    payload = {"turns": ["SecretStringTurn"], "transcript": ""}
    _real_voice(
        monkeypatch, lambda url, **kwargs: _FakeResponse(200, payload)
    )
    with pytest.raises(TranscriptionError) as exc_info:
        transcribe_recording(recording_id, db_path=db)
    assert "SecretStringTurn" not in str(exc_info.value)
    assert "expected an object" in str(exc_info.value)
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "INVALID_RESPONSE"


def test_batch_timeout_records_timeout_row(tmp_path, monkeypatch):
    recording_id = _wav_recording_id(tmp_path)
    db = tmp_path / "t.db"

    def fake_post(url, **kwargs):
        raise voice_transcribe.requests.Timeout("too slow")

    _real_voice(monkeypatch, fake_post)
    with pytest.raises(TranscriptionError, match="timed out"):
        transcribe_recording(recording_id, db_path=db)
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert len(rows) == 1
    assert rows[0]["http_status"] is None
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "TIMEOUT"


def test_retranscribe_records_attempt(tmp_path, monkeypatch):
    recording_id = _wav_recording_id(tmp_path)
    db = tmp_path / "t.db"
    payload = {
        "transcript": "Fresh transcript.",
        "audioDurationMs": 500,
        "turns": [],
    }
    _real_voice(
        monkeypatch, lambda url, **kwargs: _FakeResponse(200, payload)
    )
    transcribe_recording(recording_id, db_path=db)
    assert len(api_calls_repo.list_recent_api_calls(db_path=db)) == 1
    result = retranscribe_recording(recording_id, db_path=db)
    assert result["source"] == "real"
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert len(rows) == 2
    assert all(row["ok"] == 1 for row in rows)
    assert all(row["error_code"] is None for row in rows)
    assert all(row["recording_id"] == recording_id for row in rows)


def test_spark_invalid_reply_structure_records_invalid_response(
    tmp_path, monkeypatch
):
    recording_id, db = _recording_with_segments(tmp_path)

    def fake_post(url, **kwargs):
        return _FakeResponse(200, {"choices": []})

    _real_spark(monkeypatch, fake_post)
    with pytest.raises(SparkError, match="no choices/message/content"):
        run_review(recording_id, force_mock=False, db_path=db)
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert len(rows) == 1
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "INVALID_RESPONSE"


def test_spark_non_json_reply_corrects_row(tmp_path, monkeypatch):
    recording_id, db = _recording_with_segments(tmp_path)

    def fake_post(url, **kwargs):
        return _FakeResponse(
            200, {"choices": [{"message": {"content": "Just some words."}}]}
        )

    _real_spark(monkeypatch, fake_post)
    with pytest.raises(SparkError):
        run_review(recording_id, force_mock=False, db_path=db)
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert len(rows) == 1
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "INVALID_RESPONSE"


def test_spark_malformed_json_records_parse_error(tmp_path, monkeypatch):
    recording_id, db = _recording_with_segments(tmp_path)
    _real_spark(
        monkeypatch,
        lambda url, **kwargs: _FakeResponse(200, None, body="nope"),
    )
    with pytest.raises(SparkError, match="not valid JSON"):
        run_review(recording_id, force_mock=False, db_path=db)
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "PARSE_ERROR"


class _ConnWrapper:
    """sqlite3.Connection stand-in that records close() calls."""

    def __init__(self, conn, execute):
        self._conn = conn
        self._execute = execute
        self.closed = False

    def execute(self, *args, **kwargs):
        return self._execute(*args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def close(self):
        self.closed = True
        return self._conn.close()


def test_create_api_call_closes_connection_on_error(tmp_path, monkeypatch):
    from database.db import get_connection
    from database.schema import init_db

    db = tmp_path / "t.db"
    init_db(db)

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("boom")

    wrapper = _ConnWrapper(get_connection(db), boom)
    monkeypatch.setattr(api_calls_repo, "get_connection", lambda db_path=None: wrapper)
    with pytest.raises(sqlite3.OperationalError):
        api_calls_repo.create_api_call("meta", "m", "/x", "y", db_path=db)
    assert wrapper.closed


def test_create_api_call_closes_connection_on_success(tmp_path, monkeypatch):
    from database.db import get_connection
    from database.schema import init_db

    db = tmp_path / "t.db"
    init_db(db)
    real_conn = get_connection(db)
    wrapper = _ConnWrapper(real_conn, real_conn.execute)
    monkeypatch.setattr(api_calls_repo, "get_connection", lambda db_path=None: wrapper)
    call_id = api_calls_repo.create_api_call("meta", "m", "/x", "y", db_path=db)
    assert call_id > 0
    assert wrapper.closed


def test_update_api_call_outcome_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    call_id = api_calls_repo.create_api_call(
        "meta", "m", "/x", "y", http_status=200, ok=True, db_path=db
    )
    assert api_calls_repo.update_api_call_outcome(
        call_id, False, "INVALID_RESPONSE", db_path=db
    )
    rows = api_calls_repo.list_recent_api_calls(db_path=db)
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "INVALID_RESPONSE"
    assert not api_calls_repo.update_api_call_outcome(
        None, False, "X", db_path=db
    )
    assert not api_calls_repo.update_api_call_outcome(
        9999, False, "X", db_path=db
    )


def _seed_mixed_ledger(db):
    api_calls_repo.create_api_call(
        "meta", "mv", "/asr/transcribe", "DIARIZATION",
        http_status=429, ok=False, error_code="HTTP_429",
        latency_ms=10.0, db_path=db,
    )
    api_calls_repo.create_api_call(
        "meta", "mv", "/asr/transcribe", "DIARIZATION",
        http_status=None, ok=False, error_code="TIMEOUT",
        latency_ms=20.0, db_path=db,
    )
    api_calls_repo.create_api_call(
        "meta", "mv", "/asr/transcribe", "DIARIZATION",
        http_status=200, ok=True, error_code=None,
        latency_ms=40.0, db_path=db,
    )
    api_calls_repo.create_api_call(
        "meta", "mv", "/asr/transcribe", "DIARIZATION",
        http_status=200, ok=False, error_code="INVALID_RESPONSE",
        latency_ms=30.0, db_path=db,
    )
    api_calls_repo.create_api_call(
        "meta", "mv", "/asr/realtime", "DIARIZATION",
        http_status=101, ok=False, error_code=None,
        latency_ms=50.0, db_path=db,
    )
    api_calls_repo.create_api_call(
        "meta", "mv", "/asr/realtime", "DIARIZATION",
        http_status=101, ok=True, error_code=None,
        latency_ms=60.0, db_path=db,
    )


def test_evidence_distinguishes_outcomes(tmp_path):
    evidence = _load_script("generate_api_evidence")
    db = tmp_path / "ev.db"
    _seed_mixed_ledger(db)
    rec_id = recordings_repo.create_recording(
        "a.wav", "p", "s", 8, 1.0, "R", db_path=db
    )
    segments_repo.save_transcription(
        rec_id,
        [{"idx": 0, "start_sec": 0.0, "end_sec": 1.0, "text_original": "hi"}],
        source="mock",
        model="m",
        raw_json=None,
        db_path=db,
    )
    ai_runs_repo.create_ai_run(rec_id, "mm", "v1", "mock", db_path=db)
    out = tmp_path / "API-EVIDENCE.md"
    assert (
        evidence.main(
            ["generate_api_evidence.py", "--db", str(db), "--out", str(out)]
        )
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert "Recorded attempts: 4 (2 HTTP-successful, 1 usable results)" in text
    assert "usable result" in text
    assert "failed (INVALID_RESPONSE)" in text
    assert "429 responses: 1" in text
    assert "invalid responses: 1" in text
    assert "Recorded sessions: 2 (2 handshakes, 1 completed sessions)" in text
    assert "Latest completed session:" in text
    assert "No calls recorded yet — no provider evidence." in text
    assert "Mock-mode transcripts persisted: 1" in text
    assert "Mock review runs ledgered: 1 (real runs: 0)" in text
    assert "What this report does not prove" in text


def test_evidence_empty_ledger_is_honest(tmp_path):
    evidence = _load_script("generate_api_evidence")
    db = tmp_path / "ev.db"
    out = tmp_path / "API-EVIDENCE.md"
    assert (
        evidence.main(
            ["generate_api_evidence.py", "--db", str(db), "--out", str(out)]
        )
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert text.count("No calls recorded yet — no provider evidence.") == 3
    assert "Recorded attempts:" not in text
    assert "Recorded sessions:" not in text
    assert "What this report does not prove" in text


def test_evidence_header_sentence_spacing(tmp_path):
    evidence = _load_script("generate_api_evidence")
    db = tmp_path / "ev.db"
    out = tmp_path / "API-EVIDENCE.md"
    assert (
        evidence.main(
            ["generate_api_evidence.py", "--db", str(db), "--out", str(out)]
        )
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert "Rows record attempts made by this app" in text


def test_evidence_section_order_with_empty_ledger(tmp_path):
    evidence = _load_script("generate_api_evidence")
    db = tmp_path / "ev.db"
    out = tmp_path / "API-EVIDENCE.md"
    assert (
        evidence.main(
            ["generate_api_evidence.py", "--db", str(db), "--out", str(out)]
        )
        == 0
    )
    text = out.read_text(encoding="utf-8")
    headings = [
        "## Voice batch (`/asr/transcribe`)",
        "## Voice realtime (`/asr/realtime`)",
        "## Spark (chat / messages / responses style endpoint)",
        "## Mock executions (not provider evidence)",
        "## What this report does not prove",
    ]
    positions = []
    for heading in headings:
        assert text.count(heading) == 1, f"heading missing or duplicated: {heading}"
        positions.append(text.index(heading))
    assert positions == sorted(positions)


def test_evidence_writes_no_transcript_or_secrets(tmp_path):
    evidence = _load_script("generate_api_evidence")
    db = tmp_path / "ev.db"
    secret_transcript = "ConfidentialCourtHearingTranscriptText"
    secret_key = "SecretApiKey-aaa111BBB222"
    secret_session = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    api_calls_repo.create_api_call(
        "meta", "mv", "/asr/transcribe", "DIARIZATION",
        http_status=200, ok=True, error_code=None,
        latency_ms=40.0, db_path=db,
    )
    rec_id = recordings_repo.create_recording(
        "a.wav", "p", "s", 8, 1.0, "R", db_path=db
    )
    segments_repo.save_transcription(
        rec_id,
        [{"idx": 0, "start_sec": 0.0, "end_sec": 1.0, "text_original": "hi"}],
        source="real",
        model="m",
        raw_json=json.dumps(
            {
                "sessionId": secret_session,
                "transcript": secret_transcript,
                "note": f"Bearer {secret_key}",
            }
        ),
        db_path=db,
    )
    ai_runs_repo.create_ai_run(
        rec_id, "mm", "v1", "real",
        raw_json=json.dumps({"accessToken": secret_key}),
        db_path=db,
    )
    out = tmp_path / "API-EVIDENCE.md"
    assert (
        evidence.main(
            ["generate_api_evidence.py", "--db", str(db), "--out", str(out)]
        )
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert secret_transcript not in text
    assert secret_key not in text
    assert secret_session not in text
    assert "aaaaaaaa" not in text
    assert "excerpt" not in text.lower()
    assert "Recorded attempts: 1 (1 HTTP-successful, 1 usable results)" in text


def test_integrations_readme_lists_all_live_bullets():
    text = (
        ROOT / "backend" / "integrations" / "meta" / "README.md"
    ).read_text(encoding="utf-8")
    assert '{"type":"endStream"}alidated' not in text
    assert "Muse Voice Transcribe (batch)" in text
    assert '{"type":"endStream"}' in text
    assert "code 1000" in text
    assert "Muse Spark review" in text
    assert "review_prompt.py" in text
    assert "never modifies the transcript" in text
    assert "audio_prep.py" in text
    assert "audio_capture.py" in text
