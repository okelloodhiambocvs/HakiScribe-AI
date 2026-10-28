"""Transcription service: recording audio to persisted segments.

The slow Meta call always runs outside any database transaction. An
in-process guard stops the same recording being transcribed twice at
once; the repository serializes the actual write with BEGIN IMMEDIATE.
"""

import json
import threading
from pathlib import Path

from backend.integrations.meta import voice_transcribe
from backend.integrations.meta.audio_prep import AudioPrepError  # noqa: F401 (re-export)
from backend.integrations.meta.voice_transcribe import (  # noqa: F401 (re-export)
    TranscriptionError,
)
from backend.repositories import segments_repo
from backend.repositories.segments_repo import (  # noqa: F401 (re-export)
    AlreadyTranscribedError,
    TranscriptionLockedError,
)
from backend.services.ingestion_service import get_recording_or_raise

__all__ = [
    "transcribe_recording",
    "retranscribe_recording",
    "get_transcript",
    "TranscriptionError",
    "AudioPrepError",
    "AlreadyTranscribedError",
    "TranscriptionLockedError",
    "TranscriptionInProgressError",
]


class TranscriptionInProgressError(ValueError):
    """A transcription call for this recording is already running here."""


_transcribe_lock = threading.Lock()
_transcribe_in_flight: set[tuple[str, int]] = set()


def _in_flight_key(
    recording_id: int, db_path: str | Path | None
) -> tuple[str, int]:
    """Scope in-flight tracking per database argument + recording.

    Best effort: two spellings of one file key differently, but the
    repository's BEGIN IMMEDIATE plus the AlreadyTranscribedError
    conversion still guarantee exactly one transcript. Deliberately
    avoids importing database (services never import it).
    """
    scope = "DEFAULT" if db_path is None else str(db_path)
    return (scope, recording_id)


def _source_of(recording: dict) -> str:
    """Return 'real' or 'mock'; legacy NULL rows report conservatively."""
    return recording.get("transcription_source") or "mock"


def _already_transcribed_result(
    recording_id: int, recording: dict, db_path: str | Path | None
) -> dict:
    """Build the already_transcribed shape with its provenance source."""
    existing = segments_repo.list_segments(recording_id, db_path=db_path)
    return {
        "recording_id": recording_id,
        "status": "already_transcribed",
        "segment_count": len(existing),
        "segments": existing,
        "source": _source_of(recording),
    }


def _persist_result(
    recording_id: int,
    result: dict,
    db_path: str | Path | None,
    replace: bool,
) -> tuple[list[dict], str]:
    """Save (or replace) a transcript; return (saved segments, source).

    Real calls store the raw response JSON; mock calls store NULL.
    """
    source = "real" if result.get("status") == "real" else "mock"
    raw = result.get("raw")
    raw_json = (
        json.dumps(raw, ensure_ascii=False)
        if source == "real" and raw is not None
        else None
    )
    writer = (
        segments_repo.replace_transcription if replace else segments_repo.save_transcription
    )
    writer(
        recording_id,
        result["segments"],
        source,
        result.get("model"),
        raw_json,
        db_path=db_path,
    )
    return segments_repo.list_segments(recording_id, db_path=db_path), source


def transcribe_recording(
    recording_id: int,
    force_mock: bool = False,
    db_path: str | Path | None = None,
) -> dict:
    """Transcribe a recording once and persist its segments.

    Returns already_transcribed without duplicating when segments exist.
    ValueError when the recording or its stored audio file is missing.
    TranscriptionInProgressError when this process is already
    transcribing the same recording.
    """
    key = _in_flight_key(recording_id, db_path)
    with _transcribe_lock:
        if key in _transcribe_in_flight:
            raise TranscriptionInProgressError(
                f"transcription already in progress for recording {recording_id}"
            )
        _transcribe_in_flight.add(key)
    try:
        recording = get_recording_or_raise(recording_id, db_path=db_path)
        if segments_repo.list_segments(recording_id, db_path=db_path):
            return _already_transcribed_result(recording_id, recording, db_path)
        stored_path = recording["stored_path"]
        if not Path(stored_path).is_file():
            raise ValueError(f"stored audio file missing: {stored_path}")
        # Slow network call: outside any transaction by construction.
        result = voice_transcribe.transcribe_audio_file(
            stored_path, force_mock=force_mock
        )
        try:
            saved, source = _persist_result(
                recording_id, result, db_path, replace=False
            )
        except AlreadyTranscribedError:
            # Another process transcribed while the Meta call was running.
            fresh = get_recording_or_raise(recording_id, db_path=db_path)
            return _already_transcribed_result(recording_id, fresh, db_path)
        return {
            "recording_id": recording_id,
            "status": result["status"],
            "segment_count": len(saved),
            "segments": saved,
            "source": source,
        }
    finally:
        with _transcribe_lock:
            _transcribe_in_flight.discard(key)


def retranscribe_recording(
    recording_id: int,
    force_mock: bool = False,
    db_path: str | Path | None = None,
) -> dict:
    """Replace a recording's transcript via the guarded replace path.

    Raises TranscriptionLockedError when flags or corrections exist.
    """
    recording = get_recording_or_raise(recording_id, db_path=db_path)
    stored_path = recording["stored_path"]
    if not Path(stored_path).is_file():
        raise ValueError(f"stored audio file missing: {stored_path}")
    result = voice_transcribe.transcribe_audio_file(stored_path, force_mock=force_mock)
    saved, source = _persist_result(recording_id, result, db_path, replace=True)
    return {
        "recording_id": recording_id,
        "status": result["status"],
        "segment_count": len(saved),
        "segments": saved,
        "source": source,
    }


def get_transcript(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """Return a recording's segments ordered by idx."""
    return segments_repo.list_segments(recording_id, db_path=db_path)
