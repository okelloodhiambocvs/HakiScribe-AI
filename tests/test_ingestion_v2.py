"""V2 ingestion service tests: synthetic upload validation and storage.

Isolated tmp_path uploads folder and SQLite file per test. The real
data/hakiscribe.db and storage/uploads are never touched here.
"""

import hashlib
from pathlib import Path

import pytest

from backend.services.ingestion_service import validate_and_store_upload


def test_upload_stores_file_and_creates_recording(tmp_path):
    file_bytes = b"synthetic-audio-bytes"
    recording = validate_and_store_upload(
        "CR 123 hearing.mp3",
        file_bytes,
        "Reviewer Amina",
        synthetic_attestation=True,
        upload_dir=tmp_path / "uploads",
        db_path=tmp_path / "t.db",
    )
    assert recording["filename"] == "CR_123_hearing.mp3"
    assert recording["uploaded_by"] == "Reviewer Amina"
    assert recording["size_bytes"] == len(file_bytes)
    assert recording["sha256"] == hashlib.sha256(file_bytes).hexdigest()
    stored = Path(recording["stored_path"])
    assert stored.exists()
    assert stored.read_bytes() == file_bytes


def test_upload_rejects_unsupported_extension(tmp_path):
    with pytest.raises(ValueError):
        validate_and_store_upload(
            "hearing.txt",
            b"synthetic-audio-bytes",
            "Reviewer Amina",
            upload_dir=tmp_path / "uploads",
            db_path=tmp_path / "t.db",
        )


def test_upload_rejects_empty_file(tmp_path):
    with pytest.raises(ValueError):
        validate_and_store_upload(
            "hearing.mp3",
            b"",
            "Reviewer Amina",
            upload_dir=tmp_path / "uploads",
            db_path=tmp_path / "t.db",
        )


def test_upload_requires_reviewer_name(tmp_path):
    with pytest.raises(ValueError):
        validate_and_store_upload(
            "hearing.mp3",
            b"synthetic-audio-bytes",
            "",
            upload_dir=tmp_path / "uploads",
            db_path=tmp_path / "t.db",
        )


def test_upload_requires_synthetic_attestation(tmp_path):
    with pytest.raises(ValueError):
        validate_and_store_upload(
            "hearing.mp3",
            b"synthetic-audio-bytes",
            "Reviewer Amina",
            synthetic_attestation=False,
            upload_dir=tmp_path / "uploads",
            db_path=tmp_path / "t.db",
        )
