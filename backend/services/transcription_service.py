"""Transcription service: recording audio to persisted segments."""

from pathlib import Path

from backend.integrations.meta import voice_transcribe
from backend.repositories import segments_repo
from backend.services.ingestion_service import get_recording_or_raise


def transcribe_recording(
    recording_id: int,
    force_mock: bool = False,
    db_path: str | Path | None = None,
) -> dict:
    """Transcribe a recording once and persist its segments.

    Returns already_transcribed without duplicating when segments exist.
    ValueError when the recording or its stored audio file is missing.
    """
    recording = get_recording_or_raise(recording_id, db_path=db_path)
    existing = segments_repo.list_segments(recording_id, db_path=db_path)
    if existing:
        return {
            "recording_id": recording_id,
            "status": "already_transcribed",
            "segment_count": len(existing),
            "segments": existing,
        }
    stored_path = recording["stored_path"]
    if not Path(stored_path).is_file():
        raise ValueError(f"stored audio file missing: {stored_path}")
    result = voice_transcribe.transcribe_audio_file(stored_path, force_mock=force_mock)
    segments_repo.create_segments(recording_id, result["segments"], db_path=db_path)
    saved = segments_repo.list_segments(recording_id, db_path=db_path)
    return {
        "recording_id": recording_id,
        "status": result["status"],
        "segment_count": len(saved),
        "segments": saved,
    }


def get_transcript(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """Return a recording's segments ordered by idx."""
    return segments_repo.list_segments(recording_id, db_path=db_path)
