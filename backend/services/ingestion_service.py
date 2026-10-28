"""Ingestion service: validate and store synthetic uploads.

Validates type, size, and synthetic attestation, then stores the file and a
recording row. Never decodes or transcribes audio — that is a later service.
"""

import hashlib
import re
import uuid
from pathlib import Path

from backend.repositories import recordings_repo

ALLOWED_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".adts", ".ogg", ".opus", ".webm")
_BYTES_PER_MB = 1024 * 1024


def _sanitize_filename(filename: str) -> str:
    """Strip directories, spaces to underscores, safe characters only."""
    name = Path(filename).name.replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9._-]", "", name)
    stem, dot, suffix = name.partition(".")
    if not stem or not dot:
        raise ValueError(f"invalid filename: {filename!r}")
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
        raise ValueError("uploaded_by is required")
    if not synthetic_attestation:
        raise ValueError("only synthetic demo recordings are allowed for this hackathon")
    safe_name = _sanitize_filename(filename)
    if Path(safe_name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"unsupported audio type: {filename!r} "
            f"(use {', '.join(ALLOWED_EXTENSIONS)})"
        )
    if not file_bytes:
        raise ValueError("uploaded file is empty")
    if len(file_bytes) > max_size_mb * _BYTES_PER_MB:
        raise ValueError(f"file exceeds {max_size_mb} MB limit")

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


def get_recording_or_raise(
    recording_id: int, db_path: str | Path | None = None
) -> dict:
    """Fetch a recording row; ValueError when it does not exist."""
    recording = recordings_repo.get_recording(recording_id, db_path=db_path)
    if recording is None:
        raise ValueError(f"recording not found: {recording_id}")
    return recording
