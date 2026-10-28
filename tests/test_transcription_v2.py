"""V2 transcription tests: mock Voice Transcribe through the service layer.

Isolated tmp_path uploads folder and SQLite file per test. The real
data/hakiscribe.db and storage/uploads are never touched here.
"""

from backend.integrations.meta.voice_transcribe import normalize_speaker
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
