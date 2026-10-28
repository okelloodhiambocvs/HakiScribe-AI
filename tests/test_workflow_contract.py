"""Frontend/backend contract: facade, snapshot, errors, health, AppTest flows.

Offline: isolated tmp database via HAKISCRIBE_DB_PATH, tmp uploads, forced
mock. Never touches data/hakiscribe.db or the real storage/ folders.
"""

import dataclasses
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from backend.core import config
from backend.core.errors import HakiScribeError, UploadValidationError
from backend.integrations.meta.audio_prep import AudioPrepError
from backend.integrations.meta.voice_transcribe import TranscriptionError
from backend.repositories.segments_repo import (
    AlreadyTranscribedError,
    TranscriptionLockedError,
)
from backend.services import health_service, ingestion_service, workflow_service
from backend.services.transcription_service import TranscriptionInProgressError
from frontend.views import transcribe_view

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "frontend" / "app.py"

_TEXT_ELEMENTS = (
    "markdown",
    "caption",
    "info",
    "success",
    "warning",
    "text",
    "header",
    "subheader",
)


@pytest.fixture()
def isolated_storage(tmp_path, monkeypatch):
    """Point the database and uploads at tmp_path via environment."""
    db_path = tmp_path / "hakiscribe.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("HAKISCRIBE_DB_PATH", str(db_path))
    monkeypatch.setenv("HAKISCRIBE_UPLOAD_DIR", str(upload_dir))
    return db_path, upload_dir


def _visible_text(app: AppTest) -> str:
    """Join every text-bearing element value in an AppTest tree."""
    chunks = []
    for name in _TEXT_ELEMENTS:
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


def test_contract_upload_snapshot_transcribe_snapshot(isolated_storage):
    db_path, upload_dir = isolated_storage
    recording = workflow_service.upload_recording(
        "CR 123 hearing.mp3",
        b"synthetic-audio-bytes",
        "Reviewer Amina",
        True,
    )
    assert recording["uploaded_by"] == "Reviewer Amina"
    assert Path(recording["stored_path"]).parent == upload_dir
    assert Path(recording["stored_path"]).is_file()
    assert db_path.is_file()

    fresh = workflow_service.get_snapshot(recording["id"])
    assert fresh is not None
    assert fresh.transcript_status == "none"
    assert fresh.source is None
    assert fresh.segment_count == 0
    assert fresh.can_transcribe is True
    assert fresh.can_review is False
    assert fresh.can_export is False

    result = workflow_service.transcribe(recording["id"], force_mock=True)
    assert result["status"] == "mock-no-key"
    assert result["segment_count"] == 5

    done = workflow_service.get_snapshot(recording["id"])
    assert done is not None
    assert done.segment_count == 5
    assert len(done.segments) == 5
    assert done.source == "mock"
    assert done.transcript_status == "present"
    assert done.can_review is True
    assert done.can_export is True
    assert "MAGISTRATE" in done.speakers
    assert done.low_confidence_count == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        done.can_review = False

    again = workflow_service.transcribe(recording["id"], force_mock=True)
    assert again["status"] == "already_transcribed"
    assert workflow_service.get_snapshot(recording["id"]).segment_count == 5


def test_snapshot_none_for_missing_or_unset_recording(isolated_storage):
    assert workflow_service.get_snapshot(None) is None
    assert workflow_service.get_snapshot(999999) is None


def test_apptest_demo_to_mock_transcript(isolated_storage, tmp_path, monkeypatch):
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
    assert app.session_state["current_step"] == "transcribe"
    assert app.session_state["recording_id"] is not None

    app.button(key="transcribe_recording").click()
    app.run()
    app.run()
    assert not app.exception

    blob = _visible_text(app)
    assert "MOCK: demo only" in blob
    assert "Showing 5 of 5 segments" in blob
    assert "Court is now in session" in blob


def test_stale_recording_resets_to_upload(isolated_storage):
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["recording_id"] = 999999
    app.session_state["current_step"] = "transcribe"
    app.run()
    assert not app.exception
    assert app.session_state["recording_id"] is None
    assert app.session_state["current_step"] == "upload"
    assert any(
        "no longer available" in str(element.value) for element in app.info
    )


@pytest.mark.parametrize(
    "exc_cls",
    [
        TranscriptionError,
        AudioPrepError,
        AlreadyTranscribedError,
        TranscriptionLockedError,
        TranscriptionInProgressError,
        UploadValidationError,
    ],
)
def test_error_contract(exc_cls):
    assert issubclass(exc_cls, HakiScribeError)
    err = exc_cls("boom")
    assert err.code and isinstance(err.code, str)
    assert err.user_message and isinstance(err.user_message, str)
    assert "Traceback" not in err.code
    assert "Traceback" not in err.user_message
    assert "Traceback" not in str(err)


def test_validation_errors_stay_value_errors():
    for exc_cls in (
        AlreadyTranscribedError,
        TranscriptionLockedError,
        TranscriptionInProgressError,
        UploadValidationError,
    ):
        assert issubclass(exc_cls, ValueError)


def _check_map(checks):
    return {check.name: check for check in checks}


def test_health_dev_base_warns_and_mock_without_key(
    isolated_storage, monkeypatch
):
    db_path, _upload_dir = isolated_storage
    monkeypatch.setattr(config, "is_configured", lambda: False)
    monkeypatch.setattr(config, "META_API_BASE", "https://dev.meta.ai/docs")
    monkeypatch.setattr(config, "META_VOICE_MODEL", "muse-voice-transcribe")
    monkeypatch.setenv("META_API_KEY", "FAKE-KEY-abc123")
    checks = health_service.check_system()
    by_name = _check_map(checks)
    assert by_name["api_base"].status == "WARN"
    assert "developer website" in by_name["api_base"].message
    assert by_name["voice_model"].status == "WARN"
    assert by_name["mode"].message == "mode: mock (synthetic demo, no API calls)"
    assert by_name["database"].status == "OK"
    assert not db_path.exists()
    assert "FAKE-KEY-abc123" not in "\n".join(
        check.message for check in checks
    )


def test_health_real_mode_with_valid_config(isolated_storage, monkeypatch):
    monkeypatch.setattr(config, "is_configured", lambda: True)
    monkeypatch.setattr(config, "META_API_BASE", "https://api.meta.ai/v1")
    monkeypatch.setattr(config, "META_VOICE_MODEL", "muse-voice-transcribe-1.0")
    monkeypatch.setenv("META_API_KEY", "FAKE-KEY-abc123")
    checks = health_service.check_system()
    by_name = _check_map(checks)
    assert by_name["api_base"].status == "OK"
    assert "api.meta.ai" in by_name["api_base"].message
    assert by_name["voice_model"].status == "OK"
    assert by_name["mode"].message == "mode: real (Meta API calls)"
    assert "FAKE-KEY-abc123" not in "\n".join(
        check.message for check in checks
    )


def test_health_warns_on_plain_http_base(isolated_storage, monkeypatch):
    monkeypatch.setattr(config, "is_configured", lambda: False)
    monkeypatch.setattr(config, "META_API_BASE", "http://api.meta.ai/v1")
    checks = health_service.check_system()
    by_name = _check_map(checks)
    assert by_name["api_base"].status == "WARN"
    assert "https" in by_name["api_base"].message
