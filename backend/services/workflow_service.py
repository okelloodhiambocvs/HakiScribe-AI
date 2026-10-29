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
    exports_repo,
    flags_repo,
    recordings_repo,
    segments_repo,
)
from backend.services import (
    evaluation_service,
    export_service,
    health_service,
    ingestion_service,
    live_session_service,
    review_prompt,
    review_service,
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


def run_review(
    recording_id: int,
    force_mock: bool = False,
    db_path: str | Path | None = None,
) -> dict:
    """Run AI review over a transcript; return run summary plus flags."""
    return review_service.run_review(
        recording_id, force_mock=force_mock, db_path=db_path
    )


def get_flags(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """Return a recording's review flags with segment_idx."""
    return review_service.get_flags(recording_id, db_path=db_path)


def get_review_summary(
    recording_id: int, db_path: str | Path | None = None
) -> dict | None:
    """Return the latest review run row; None when never reviewed."""
    return review_service.get_review_summary(recording_id, db_path=db_path)


def edit_segment(
    segment_id: int,
    new_text: str | None,
    reviewer: str,
    reason: str | None,
    expected_current: str | None,
    db_path: str | Path | None = None,
) -> dict:
    """Apply a reviewer text edit with stale-write protection."""
    return review_service.edit_segment(
        segment_id, new_text, reviewer, reason, expected_current, db_path=db_path
    )


def decide_flag(
    flag_id: int,
    decision: str,
    reviewer: str,
    reason: str | None,
    new_text: str | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """Apply one flag decision atomically and resolve the flag."""
    return review_service.decide_flag(
        flag_id, decision, reviewer, reason, new_text=new_text, db_path=db_path
    )


def assign_speaker_role(
    recording_id: int,
    speaker_label: str,
    role: str,
    reviewer: str,
    reason: str | None,
    db_path: str | Path | None = None,
) -> dict:
    """Assign a locked-taxonomy role to a speaker label."""
    return review_service.assign_speaker_role(
        recording_id, speaker_label, role, reviewer, reason, db_path=db_path
    )


def get_segment_history(
    segment_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """Return a segment's corrections ordered by id."""
    return review_service.get_segment_history(segment_id, db_path=db_path)


def get_unresolved(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """Return OPEN and RETAINED flags with segment time and message."""
    return review_service.get_unresolved(recording_id, db_path=db_path)


def get_speaker_roles(
    recording_id: int, db_path: str | Path | None = None
) -> dict[str, str]:
    """Map speaker labels to assigned court roles for a recording."""
    return review_service.get_speaker_roles(recording_id, db_path=db_path)


def record_review_event(
    recording_id: int,
    reviewer: str,
    event: str,
    db_path: str | Path | None = None,
) -> int:
    """Log one review-time event (review_opened, edit, decision)."""
    return review_service.record_review_event(
        recording_id, reviewer, event, db_path=db_path
    )


def get_taxonomy_roles() -> tuple[str, ...]:
    """Return the locked speaker taxonomy roles for selectors."""
    return review_prompt.TAXONOMY_ROLES


def _resolve_export_dir(export_dir: str | Path | None) -> Path:
    """Default export dir, honoring HAKISCRIBE_EXPORT_DIR for tests."""
    if export_dir is not None:
        return Path(export_dir)
    return Path(os.environ.get("HAKISCRIBE_EXPORT_DIR", "storage/exports"))


def evaluate_recording(
    recording_id: int, db_path: str | Path | None = None
) -> dict:
    """Return all five evaluation metric envelopes for a recording."""
    return {
        "ai_vs_reviewed": evaluation_service.compare_ai_vs_reviewed(
            recording_id, db_path=db_path
        ),
        "reference": evaluation_service.compare_to_reference(
            recording_id, None, db_path=db_path
        ),
        "speaker": evaluation_service.speaker_attribution_accuracy(
            recording_id, None, db_path=db_path
        ),
        "traceability": evaluation_service.traceability_completeness(
            recording_id, db_path=db_path
        ),
        "review_time": evaluation_service.review_time(
            recording_id, db_path=db_path
        ),
    }


def generate_draft_docx(
    recording_id: int,
    reviewer: str,
    export_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """Build the watermarked draft DOCX and record the export."""
    return export_service.generate_draft_docx(
        recording_id,
        reviewer,
        db_path=db_path,
        export_dir=_resolve_export_dir(export_dir),
    )


def get_latest_export(
    recording_id: int, db_path: str | Path | None = None
) -> dict | None:
    """Fetch the newest export row; None when never exported."""
    return exports_repo.get_latest_export_by_recording(
        recording_id, db_path=db_path
    )


def export_file_path(
    docx_filename: str, export_dir: str | Path | None = None
) -> Path:
    """Resolve an export filename to its on-disk path."""
    return _resolve_export_dir(export_dir) / docx_filename


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


def list_microphones() -> list[dict]:
    """List microphone devices as [{index, name}]."""
    return live_session_service.list_microphones()


def start_live_session(
    reviewer: str,
    consent_attested: bool,
    device=None,
    upload_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """Start one live microphone session; return its state."""
    return live_session_service.start_live_session(
        reviewer,
        consent_attested,
        device=device,
        db_path=db_path,
        upload_dir=_resolve_upload_dir(upload_dir),
    )


def stop_live_session() -> dict:
    """Stop the running live session; return its state."""
    return live_session_service.stop_live_session()


def get_live_state() -> dict:
    """Return a copy of the current live session state."""
    return live_session_service.get_live_state()


def finalise_live_session(
    recording_id: int,
    force_mock: bool = False,
    db_path: str | Path | None = None,
) -> dict:
    """Run the guarded batch pass over the saved live WAV."""
    return live_session_service.finalise_live_session(
        recording_id, force_mock=force_mock, db_path=db_path
    )


def delete_recording(
    recording_id: int,
    reviewer: str,
    confirm: str,
    export_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """Delete a recording's rows and files (typed DELETE confirmation)."""
    return ingestion_service.delete_recording(
        recording_id,
        reviewer,
        confirm,
        export_dir=_resolve_export_dir(export_dir),
        db_path=db_path,
    )
