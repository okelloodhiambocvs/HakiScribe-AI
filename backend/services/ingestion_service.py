"""Ingestion service: validate and store synthetic uploads.

Validates type, size, and synthetic attestation, then stores the file and a
recording row. Never decodes or transcribes audio — that is a later service.
"""

import hashlib
import re
import uuid
from pathlib import Path

from backend.core.errors import UploadValidationError
from backend.repositories import (
    deletion_log_repo,
    exports_repo,
    recordings_repo,
)

ALLOWED_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".adts", ".ogg", ".opus", ".webm")
DEMO_RECORDING_PATH = Path("demo-data/synthetic/case-cr-123-2026.wav")
_BYTES_PER_MB = 1024 * 1024


def _sanitize_filename(filename: str) -> str:
    """Strip directories, spaces to underscores, safe characters only."""
    name = Path(filename).name.replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9._-]", "", name)
    stem, dot, suffix = name.partition(".")
    if not stem or not dot:
        raise UploadValidationError(f"invalid filename: {filename!r}")
    return name


def validate_and_store_upload(
    filename: str,
    file_bytes: bytes,
    uploaded_by: str,
    synthetic_attestation: bool = True,
    upload_dir: str | Path = "storage/uploads",
    db_path: str | Path | None = None,
    max_size_mb: int = 25,
) -> dict:
    """Validate an upload, store it, and return its recording row."""
    if not uploaded_by or not uploaded_by.strip():
        raise UploadValidationError("uploaded_by is required")
    if not synthetic_attestation:
        raise UploadValidationError(
            "only synthetic demo recordings are allowed for this hackathon"
        )
    safe_name = _sanitize_filename(filename)
    if Path(safe_name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            f"unsupported audio type: {filename!r} "
            f"(use {', '.join(ALLOWED_EXTENSIONS)})"
        )
    if not file_bytes:
        raise UploadValidationError("uploaded file is empty")
    if len(file_bytes) > max_size_mb * _BYTES_PER_MB:
        raise UploadValidationError(
            f"file exceeds {max_size_mb} MB limit"
        )

    target_dir = Path(upload_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_path = target_dir / f"{uuid.uuid4().hex}_{safe_name}"
    stored_path.write_bytes(file_bytes)

    recording_id = recordings_repo.create_recording(
        filename=safe_name,
        stored_path=str(stored_path),
        sha256=hashlib.sha256(file_bytes).hexdigest(),
        size_bytes=len(file_bytes),
        duration_sec=None,
        uploaded_by=uploaded_by.strip(),
        synthetic_attestation=True,
        db_path=db_path,
    )
    return recordings_repo.get_recording(recording_id, db_path=db_path)


def load_demo_recording(
    reviewer_name: str,
    upload_dir: str | Path = "storage/uploads",
    db_path: str | Path | None = None,
    max_size_mb: int = 25,
) -> dict:
    """Load the bundled synthetic demo recording through the normal path.

    Same validation, hashing, and synthetic attestation as an upload.
    ValueError with a friendly message when the demo file is missing.
    """
    if not DEMO_RECORDING_PATH.is_file():
        raise UploadValidationError(
            "Demo recording not found at demo-data/synthetic/case-cr-123-2026.wav. "
            "Run scripts/make_demo_audio.ps1 to generate it, or upload a file below."
        )
    return validate_and_store_upload(
        DEMO_RECORDING_PATH.name,
        DEMO_RECORDING_PATH.read_bytes(),
        reviewer_name,
        synthetic_attestation=True,
        upload_dir=upload_dir,
        db_path=db_path,
        max_size_mb=max_size_mb,
    )


def get_recording_or_raise(
    recording_id: int, db_path: str | Path | None = None
) -> dict:
    """Fetch a recording row; ValueError when it does not exist."""
    recording = recordings_repo.get_recording(recording_id, db_path=db_path)
    if recording is None:
        raise UploadValidationError(
            f"recording not found: {recording_id}"
        )
    return recording


DELETE_CONFIRMATION = "DELETE"


def delete_recording(
    recording_id: int,
    reviewer: str,
    confirm: str,
    export_dir: str | Path = "storage/exports",
    db_path: str | Path | None = None,
) -> dict:
    """Delete a recording's rows, audio file, and export files.

    Requires confirm == "DELETE" and a non-empty reviewer. Writes a
    content-free deletion_log row (deleted id, reviewer, time). Files
    that are already gone are skipped; failures are reported, not raised.
    """
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise ValueError("reviewer name is required")
    if confirm != DELETE_CONFIRMATION:
        raise ValueError("type DELETE to confirm deletion")
    recording = get_recording_or_raise(recording_id, db_path=db_path)
    exports = exports_repo.list_exports_by_recording(
        recording_id, db_path=db_path
    )
    candidates = [recording["stored_path"]]
    export_root = Path(export_dir)
    for export in exports:
        name = export.get("docx_filename") or ""
        if not name or Path(name).name != name:
            continue
        candidates.append(str(export_root / name))
    removed, failed = 0, []
    for candidate in candidates:
        try:
            if Path(candidate).is_file():
                Path(candidate).unlink()
                removed += 1
        except OSError:
            failed.append(Path(candidate).name)
    recordings_repo.delete_recording(recording_id, db_path=db_path)
    deletion_log_repo.log_deletion(recording_id, reviewer, db_path=db_path)
    return {
        "recording_id": recording_id,
        "files_removed": removed,
        "files_failed": failed,
    }
