"""V2 transcription tests: mock Voice Transcribe through the service layer.

Isolated tmp_path uploads folder and SQLite file per test. The real
data/hakiscribe.db and storage/uploads are never touched here.
"""

import json
import wave

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
from backend.services.ingestion_service import validate_and_store_upload
from backend.services.transcription_service import transcribe_recording


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
