"""V2 transcription tests: mock Voice Transcribe through the service layer.

Isolated tmp_path uploads folder and SQLite file per test. The real
data/hakiscribe.db and storage/uploads are never touched here.
"""

import importlib.util
import json
import threading
import wave
from pathlib import Path

import pytest

from backend.core.config import META_VOICE_MODEL
from backend.integrations.meta.audio_prep import (
    AudioPrepError,
    prepare_wav,
    wav_duration_sec,
)
from backend.integrations.meta.voice_transcribe import (
    TranscriptionError,
    normalize_speaker,
    transcribe_audio_file,
)
from backend.repositories import corrections_repo, flags_repo
from backend.repositories import recordings_repo, segments_repo
from backend.repositories.segments_repo import TranscriptionLockedError
from backend.services.ingestion_service import validate_and_store_upload
from backend.services.transcription_service import (
    TranscriptionInProgressError,
    retranscribe_recording,
    transcribe_recording,
)


def _recording_id(tmp_path):
    recording = validate_and_store_upload(
        "hearing.mp3",
        b"synthetic-audio",
        "Reviewer Amina",
        upload_dir=tmp_path / "uploads",
        db_path=tmp_path / "t.db",
    )
    return recording["id"]


def test_mock_transcription_persists_segments_with_timestamps(tmp_path):
    db = tmp_path / "t.db"
    result = transcribe_recording(_recording_id(tmp_path), force_mock=True, db_path=db)
    assert result["status"] == "mock-no-key"
    assert result["segment_count"] == 5
    assert len(result["segments"]) == 5
    first = result["segments"][0]
    assert first["start_sec"] == 0.4
    assert first["end_sec"] == 4.2
    assert first["speaker"] == "MAGISTRATE"
    for segment in result["segments"]:
        assert segment["text_original"]
        assert segment["text_current"] == segment["text_original"]


def test_mixed_language_is_preserved(tmp_path):
    db = tmp_path / "t.db"
    result = transcribe_recording(_recording_id(tmp_path), force_mock=True, db_path=db)
    complainant = next(
        s for s in result["segments"] if s["speaker"] == "COMPLAINANT"
    )
    assert complainant["text_original"] == (
        "Mheshimiwa, nilifika nyumbani saa mbili, and then I saw the accused."
    )
    assert complainant["language"] == "mixed"


def test_transcription_does_not_duplicate_segments(tmp_path):
    db = tmp_path / "t.db"
    recording_id = _recording_id(tmp_path)
    first = transcribe_recording(recording_id, force_mock=True, db_path=db)
    assert first["segment_count"] == 5
    second = transcribe_recording(recording_id, force_mock=True, db_path=db)
    assert second["status"] == "already_transcribed"
    assert second["segment_count"] == 5
    assert len(second["segments"]) == 5


def test_unknown_speaker_is_not_guessed():
    assert normalize_speaker("Random Person?") == "UNKNOWN"
    assert normalize_speaker("Witness") == "WITNESS_PW1"
    assert normalize_speaker("Magistrate") == "MAGISTRATE"


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


def test_prepare_wav_converts_to_16k_mono(tmp_path):
    src = _make_wav(tmp_path / "in.wav")
    dst = prepare_wav(src, tmp_path / "out.wav")
    assert dst == tmp_path / "out.wav"
    with wave.open(str(dst), "rb") as wav_file:
        assert wav_file.getframerate() == 16000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
    assert wav_duration_sec(dst) == pytest.approx(0.5, abs=0.05)


def test_prepare_wav_rejects_over_length_audio(tmp_path):
    src = _make_wav(tmp_path / "long.wav", rate=16000, channels=1, seconds=601)
    with pytest.raises(AudioPrepError):
        prepare_wav(src, tmp_path / "out.wav")


def test_real_path_posts_asr_multipart(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "in.wav")
    calls = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return _FakeResponse(200, {"segments": [
            {"start": 0.0, "end": 1.0, "speaker": "MAGISTRATE",
             "confidence": 0.9, "text": "Hello."},
        ]})

    _real_path(monkeypatch, fake_post)
    result = transcribe_audio_file(src)
    assert calls["url"].endswith("/asr/transcribe")
    auth = calls["kwargs"]["headers"]["Authorization"]
    assert auth.startswith("Bearer ") and len(auth) > len("Bearer ")
    files = calls["kwargs"]["files"]
    assert files["request"][2] == "application/json"
    assert json.loads(files["request"][1]) == {
        "mode": "PUSH_TO_TALK",
        "model": META_VOICE_MODEL,
        "audioEncoding": "WAV",
    }
    assert files["audio"][2] == "audio/wav"
    assert files["audio"][1][:4] == b"RIFF"
    assert result["status"] == "real"
    assert len(result["segments"]) == 1


def test_429_is_retried_with_backoff(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "in.wav")
    attempts = []
    sleeps = []
    responses = [
        _FakeResponse(429, headers={"Retry-After": "2"}, body="slow down"),
        _FakeResponse(429, body="slow down"),
        _FakeResponse(200, {"segments": [
            {"start": 0.0, "end": 1.0, "text": "Hi."},
        ]}),
    ]

    def fake_post(url, **kwargs):
        attempts.append(url)
        return responses[len(attempts) - 1]

    _real_path(monkeypatch, fake_post)
    monkeypatch.setattr("time.sleep", sleeps.append)
    result = transcribe_audio_file(src)
    assert len(attempts) == 3
    assert sleeps == [2.0, 2.0]
    assert result["status"] == "real"


def test_http_400_raises_transcription_error_with_body(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "in.wav")

    def fake_post(url, **kwargs):
        return _FakeResponse(400, body="bad audio encoding xyz")

    _real_path(monkeypatch, fake_post)
    with pytest.raises(TranscriptionError) as exc_info:
        transcribe_audio_file(src)
    assert "400" in str(exc_info.value)
    assert "bad audio encoding xyz" in str(exc_info.value)


def test_mock_path_still_works():
    result = transcribe_audio_file("nonexistent-file.mp3", force_mock=True)
    assert result["status"] == "mock-no-key"
    assert len(result["segments"]) == 5


def _fake_segments(prefix="Take"):
    return [
        {
            "idx": i,
            "start_sec": float(i),
            "end_sec": float(i + 1),
            "speaker": "MAGISTRATE",
            "confidence": 0.9,
            "language": "en-KE",
            "text_original": f"{prefix} segment {i}.",
        }
        for i in range(3)
    ]


def test_second_transcribe_reports_already_transcribed_with_source(tmp_path):
    db = tmp_path / "t.db"
    recording_id = _recording_id(tmp_path)
    first = transcribe_recording(recording_id, force_mock=True, db_path=db)
    assert first["segment_count"] == 5
    assert first["source"] == "mock"
    second = transcribe_recording(recording_id, force_mock=True, db_path=db)
    assert second["status"] == "already_transcribed"
    assert second["segment_count"] == 5
    assert second["source"] == "mock"
    assert len(segments_repo.list_segments(recording_id, db_path=db)) == 5


def test_legacy_transcript_without_source_reports_mock(tmp_path):
    db = tmp_path / "t.db"
    recording_id = _recording_id(tmp_path)
    segments_repo.create_segments(recording_id, _fake_segments(), db_path=db)
    result = transcribe_recording(recording_id, force_mock=True, db_path=db)
    assert result["status"] == "already_transcribed"
    assert result["source"] == "mock"


def test_concurrent_transcribe_single_winner(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    recording_id = _recording_id(tmp_path)
    entered = threading.Barrier(2)
    release = threading.Event()
    calls = []
    payload = {
        "model": "muse-voice-transcribe-mock",
        "status": "mock-no-key",
        "needs_human_review": True,
        "segments": _fake_segments(),
    }

    def gated_meta_call(audio_path, force_mock=False):
        calls.append(audio_path)
        entered.wait(timeout=30)
        assert release.wait(timeout=30)
        return payload

    monkeypatch.setattr(
        "backend.integrations.meta.voice_transcribe.transcribe_audio_file",
        gated_meta_call,
    )
    errors = []

    def worker():
        try:
            transcribe_recording(recording_id, force_mock=True, db_path=db)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    entered.wait(timeout=30)
    with pytest.raises(TranscriptionInProgressError):
        transcribe_recording(recording_id, force_mock=True, db_path=db)
    release.set()
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert errors == []
    assert len(calls) == 1
    assert len(segments_repo.list_segments(recording_id, db_path=db)) == 3


def test_mock_transcription_stores_source_and_null_raw(tmp_path):
    db = tmp_path / "t.db"
    recording_id = _recording_id(tmp_path)
    result = transcribe_recording(recording_id, force_mock=True, db_path=db)
    assert result["source"] == "mock"
    recording = recordings_repo.get_recording(recording_id, db_path=db)
    assert recording["transcription_source"] == "mock"
    assert recording["transcription_raw_json"] is None
    assert recording["transcription_model"] == "muse-voice-transcribe-mock"
    assert recording["transcribed_at"] is not None


def test_real_transcription_stores_source_and_raw_json(tmp_path, monkeypatch):
    wav_path = _make_wav(tmp_path / "real.wav")
    recording = validate_and_store_upload(
        "hearing.wav",
        wav_path.read_bytes(),
        "Reviewer Amina",
        upload_dir=tmp_path / "uploads",
        db_path=tmp_path / "t.db",
    )
    db = tmp_path / "t.db"
    payload = {"segments": [
        {"start": 0.0, "end": 1.0, "speaker": "MAGISTRATE",
         "confidence": 0.9, "text": "Hello."},
    ]}

    def fake_post(url, **kwargs):
        return _FakeResponse(200, payload)

    _real_path(monkeypatch, fake_post)
    result = transcribe_recording(recording["id"], force_mock=False, db_path=db)
    assert result["status"] == "real"
    assert result["source"] == "real"
    assert result["segment_count"] == 1
    stored = recordings_repo.get_recording(recording["id"], db_path=db)
    assert stored["transcription_source"] == "real"
    assert json.loads(stored["transcription_raw_json"]) == payload
    assert stored["transcription_model"] == META_VOICE_MODEL
    assert stored["transcribed_at"] is not None


def test_retranscribe_replaces_until_locked(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    recording_id = _recording_id(tmp_path)
    transcribe_recording(recording_id, force_mock=True, db_path=db)

    take_two = {
        "model": "muse-voice-transcribe-mock",
        "status": "mock-no-key",
        "needs_human_review": True,
        "segments": _fake_segments(prefix="Take two"),
    }
    monkeypatch.setattr(
        "backend.integrations.meta.voice_transcribe.transcribe_audio_file",
        lambda audio_path, force_mock=False: take_two,
    )
    replaced = retranscribe_recording(recording_id, force_mock=True, db_path=db)
    assert replaced["status"] == "mock-no-key"
    assert replaced["source"] == "mock"
    assert replaced["segment_count"] == 3
    assert [s["text_current"] for s in replaced["segments"]] == [
        f"Take two segment {i}." for i in range(3)
    ]

    seg_id = replaced["segments"][0]["id"]
    corrections_repo.create_correction(
        seg_id, None, "Take two segment 0.", "Edited.", "Reviewer Amina",
        "EDIT_TEXT", db_path=db,
    )
    with pytest.raises(TranscriptionLockedError):
        retranscribe_recording(recording_id, force_mock=True, db_path=db)
    assert len(segments_repo.list_segments(recording_id, db_path=db)) == 3

    other_id = validate_and_store_upload(
        "second.mp3", b"synthetic-audio", "Reviewer Amina",
        upload_dir=tmp_path / "uploads", db_path=db,
    )["id"]
    transcribe_recording(other_id, force_mock=True, db_path=db)
    other_seg = segments_repo.list_segments(other_id, db_path=db)[0]["id"]
    flags_repo.create_flag(
        other_seg, "LOW_CONFIDENCE", "HIGH", "Check.", db_path=db
    )
    with pytest.raises(TranscriptionLockedError):
        retranscribe_recording(other_id, force_mock=True, db_path=db)


_HTML_500_BODY = (
    "<html><head><title>Bad Gateway</title></head>"
    "<body><h1>502 Bad Gateway</h1><p>upstream exploded</p></body></html>"
)


@pytest.mark.parametrize("headers", [{"Content-Type": "text/html"}, {}])
def test_html_500_error_shows_title_only(tmp_path, monkeypatch, headers):
    def fake_post(url, **kwargs):
        return _FakeResponse(500, headers=dict(headers), body=_HTML_500_BODY)

    _real_path(monkeypatch, fake_post)
    src = _make_wav(tmp_path / "in.wav")
    with pytest.raises(TranscriptionError) as exc_info:
        transcribe_audio_file(src, force_mock=False)
    message = str(exc_info.value)
    assert "Bad Gateway" in message
    assert "check META_API_BASE" in message
    assert "<html" not in message
    assert "<title>" not in message
    assert len(message) < 200


def test_json_400_error_still_includes_json_text(tmp_path, monkeypatch):
    payload = {"error": {"message": "bad audio encoding"}}
    body = json.dumps(payload)

    def fake_post(url, **kwargs):
        return _FakeResponse(
            400, headers={"Content-Type": "application/json"}, body=body
        )

    _real_path(monkeypatch, fake_post)
    src = _make_wav(tmp_path / "in.wav")
    with pytest.raises(TranscriptionError) as exc_info:
        transcribe_audio_file(src, force_mock=False)
    message = str(exc_info.value)
    assert "bad audio encoding" in message
    assert "400" in message


def test_error_message_never_contains_api_key(tmp_path, monkeypatch):
    fake_key = "test-fake-key-xyz-123"
    monkeypatch.setattr(
        "backend.integrations.meta.voice_transcribe.config.get_meta_key",
        lambda: fake_key,
    )

    def fake_post(url, **kwargs):
        return _FakeResponse(400, body=f"rejected key {fake_key} for this call")

    _real_path(monkeypatch, fake_post)
    src = _make_wav(tmp_path / "in.wav")
    with pytest.raises(TranscriptionError) as exc_info:
        transcribe_audio_file(src, force_mock=False)
    message = str(exc_info.value)
    assert fake_key not in message
    assert "[REDACTED]" in message


class _ProbeHtmlResponse:
    def __init__(self):
        self.status_code = 500
        self.headers = {"Content-Type": "text/html", "x-request-id": "req-1"}
        self.text = _HTML_500_BODY
        self.ok = False

    def json(self):
        raise ValueError("no JSON here")


def _load_probe_module():
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "probe_voice_api", root / "scripts" / "probe_voice_api.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_html_output_has_no_raw_tags(tmp_path, monkeypatch, capsys):
    probe = _load_probe_module()
    fake_key = "test-fake-key-xyz-123"
    monkeypatch.setattr(probe, "get_meta_key", lambda: fake_key)
    monkeypatch.setattr(probe, "is_configured", lambda: True)
    monkeypatch.setattr(
        probe.requests, "post", lambda url, **kwargs: _ProbeHtmlResponse()
    )
    src = _make_wav(tmp_path / "in.wav")
    assert probe.main(["probe_voice_api.py", str(src)]) == 1
    out = capsys.readouterr().out
    assert "request URL:" in out
    assert "/asr/transcribe" in out
    assert "HTTP status: 500" in out
    assert "Content-Type: text/html" in out
    assert "x-request-id: req-1" in out
    assert "Bad Gateway" in out
    assert "check META_API_BASE" in out
    assert "<html" not in out
    assert fake_key not in out
