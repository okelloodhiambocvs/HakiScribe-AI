"""UI-facing facade: the ONLY backend.services module views import.

Snapshot-first: every render rebuilds a frozen WorkflowSnapshot from the
database, so session state holds only recording_id and UI selections.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from backend.repositories import (
    api_calls_repo,
    corrections_repo,
    flags_repo,
    recordings_repo,
    segments_repo,
)
from backend.services import (
    health_service,
    ingestion_service,
    transcription_service,
)

LOW_CONFIDENCE_THRESHOLD = 0.75


def _resolve_upload_dir(upload_dir: str | Path | None) -> Path:
    """Default upload dir, honoring HAKISCRIBE_UPLOAD_DIR for tests."""
    if upload_dir is not None:
        return Path(upload_dir)
    return Path(os.environ.get("HAKISCRIBE_UPLOAD_DIR", "storage/uploads"))


@dataclass(frozen=True)
class WorkflowSnapshot:
    """Frozen per-render view of one recording's workflow state."""

    recording: dict | None
    transcript_status: str  # "none" or "present"
    source: str | None  # "real", "mock", or None
    segments: tuple = ()
    segment_count: int = 0
    speakers: tuple = ()
    low_confidence_count: int = 0
    open_flag_count: int = 0
    correction_count: int = 0
    can_transcribe: bool = False
    can_review: bool = False
    can_export: bool = False


def get_system_status(db_path: str | Path | None = None):
    """Return health_service.check_system results for the sidebar."""
    return health_service.check_system(db_path)


def upload_recording(
    filename: str,
    data: bytes,
    reviewer: str,
    attested: bool,
    upload_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """Validate and store an upload; return its recording row."""
    return ingestion_service.validate_and_store_upload(
        filename,
        data,
        reviewer,
        synthetic_attestation=attested,
        upload_dir=_resolve_upload_dir(upload_dir),
        db_path=db_path,
    )


def load_demo(
    reviewer: str,
    upload_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """Load the bundled demo recording through the normal upload path."""
    return ingestion_service.load_demo_recording(
        reviewer, upload_dir=_resolve_upload_dir(upload_dir), db_path=db_path
    )


def transcribe(
    recording_id: int,
    force_mock: bool = False,
    db_path: str | Path | None = None,
) -> dict:
    """Transcribe a recording; second call reports already_transcribed."""
    return transcription_service.transcribe_recording(
        recording_id, force_mock=force_mock, db_path=db_path
    )


def retranscribe(
    recording_id: int,
    force_mock: bool = False,
    db_path: str | Path | None = None,
) -> dict:
    """Replace a transcript; locked once flags or corrections exist."""
    return transcription_service.retranscribe_recording(
        recording_id, force_mock=force_mock, db_path=db_path
    )


def list_recent_api_calls(
    limit: int = 10, db_path: str | Path | None = None
) -> list[dict]:
    """Return the most recent Meta API attempt rows (newest first)."""
    return api_calls_repo.list_recent_api_calls(limit=limit, db_path=db_path)


def get_snapshot(
    recording_id: int | None, db_path: str | Path | None = None
) -> WorkflowSnapshot | None:
    """Rebuild the workflow snapshot from the database.

    Returns None when no recording is selected or the id no longer
    exists (stale session); the UI then resets to the Upload step.
    """
    if recording_id is None:
        return None
    recording = recordings_repo.get_recording(recording_id, db_path=db_path)
    if recording is None:
        return None
    segments = segments_repo.list_segments(recording_id, db_path=db_path)
    segment_ids = {segment["id"] for segment in segments}
    open_flags = [
        flag
        for flag in flags_repo.list_open_flags(db_path=db_path)
        if flag["segment_id"] in segment_ids
    ]
    corrections = corrections_repo.list_corrections_by_recording(
        recording_id, db_path=db_path
    )
    has_transcript = len(segments) > 0
    return WorkflowSnapshot(
        recording=recording,
        transcript_status="present" if has_transcript else "none",
        source=recording.get("transcription_source"),
        segments=tuple(segments),
        segment_count=len(segments),
        speakers=tuple(sorted({segment["speaker"] for segment in segments})),
        low_confidence_count=sum(
            1
            for segment in segments
            if segment.get("confidence") is not None
            and segment["confidence"] < LOW_CONFIDENCE_THRESHOLD
        ),
        open_flag_count=len(open_flags),
        correction_count=len(corrections),
        can_transcribe=True,
        can_review=has_transcript,
        can_export=has_transcript,
    )
