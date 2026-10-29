"""Submission readiness: deletion, evidence hygiene, README claims, key scan."""

import importlib.util
import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from backend.repositories import (
    ai_runs_repo,
    api_calls_repo,
    deletion_log_repo,
    exports_repo,
    recordings_repo,
    segments_repo,
)
from backend.services import export_service, ingestion_service, workflow_service
from database.schema import SCHEMA_VERSION, init_db

ROOT = Path(__file__).resolve().parent.parent


def _load_script(name: str):
    """Load a scripts/<name>.py module without running its __main__."""
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deletion_audit_schema(tmp_path):
    assert SCHEMA_VERSION == 8
    db = tmp_path / "s.db"
    init_db(db)
    conn = sqlite3.connect(db)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(deletion_log)")}
    finally:
        conn.close()
    assert cols == {"id", "recording_id", "reviewer", "deleted_at"}


def test_delete_recording_removes_rows_files_and_logs_content_free(tmp_path):
    db = tmp_path / "t.db"
    upload_dir = tmp_path / "uploads"
    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    recording = ingestion_service.validate_and_store_upload(
        "hearing.mp3",
        b"synthetic-audio",
        "Reviewer Amina",
        synthetic_attestation=True,
        upload_dir=upload_dir,
        db_path=db,
    )
    rec_id = recording["id"]
    audio_path = Path(recording["stored_path"])
    assert audio_path.is_file()
    segments_repo.create_segment(
        rec_id, 0, 0.0, 1.0, "MAGISTRATE", None, "hi", db_path=db
    )
    export_service.generate_draft_docx(
        rec_id, "Reviewer Amina", db_path=db, export_dir=export_dir
    )
    exports = exports_repo.list_exports_by_recording(rec_id, db_path=db)
    assert len(exports) == 1
    docx_path = export_dir / exports[0]["docx_filename"]
    assert docx_path.is_file()

    result = workflow_service.delete_recording(
        rec_id, "Reviewer Amina", "DELETE", export_dir=export_dir, db_path=db
    )
    assert result["recording_id"] == rec_id
    assert result["files_removed"] == 2
    assert result["files_failed"] == []
    assert recordings_repo.get_recording(rec_id, db_path=db) is None
    assert segments_repo.list_segments(rec_id, db_path=db) == []
    assert exports_repo.list_exports_by_recording(rec_id, db_path=db) == []
    assert not audio_path.exists()
    assert not docx_path.exists()
    logs = deletion_log_repo.list_deletions(db_path=db)
    assert len(logs) == 1
    assert set(logs[0].keys()) == {
        "id",
        "recording_id",
        "reviewer",
        "deleted_at",
    }
    assert logs[0]["recording_id"] == rec_id
    assert logs[0]["reviewer"] == "Reviewer Amina"


def test_deletion_needs_confirmation(tmp_path):
    db = tmp_path / "t.db"
    recording = ingestion_service.validate_and_store_upload(
        "hearing.mp3",
        b"synthetic-audio",
        "Reviewer Amina",
        synthetic_attestation=True,
        upload_dir=tmp_path / "uploads",
        db_path=db,
    )
    rec_id = recording["id"]
    with pytest.raises(ValueError, match="DELETE"):
        workflow_service.delete_recording(
            rec_id, "Reviewer Amina", "delete", db_path=db
        )
    with pytest.raises(ValueError, match="reviewer"):
        workflow_service.delete_recording(rec_id, "  ", "DELETE", db_path=db)
    assert recordings_repo.get_recording(rec_id, db_path=db) is not None
    assert deletion_log_repo.list_deletions(db_path=db) == []
    assert Path(recording["stored_path"]).is_file()


def test_evidence_output_has_no_key_or_full_transcript(tmp_path):
    evidence = _load_script("generate_api_evidence")
    db = tmp_path / "ev.db"
    fake_key = "EvidenceFakeKey-abc123XYZ789"
    long_transcript = (
        "Kortini leo tunaendelea na kesi hii muhimu sana. " * 6
    )
    assert len(long_transcript) > 200
    api_calls_repo.create_api_call(
        "meta",
        "muse-voice-transcribe-1.0",
        "/asr/transcribe",
        "DIARIZATION",
        http_status=200,
        ok=True,
        latency_ms=1200.0,
        db_path=db,
    )
    api_calls_repo.create_api_call(
        "meta",
        "muse-voice-transcribe-1.0",
        "/asr/transcribe",
        "DIARIZATION",
        http_status=429,
        ok=False,
        error_code="HTTP_429",
        db_path=db,
    )
    api_calls_repo.create_api_call(
        "meta",
        "muse-voice-transcribe-1.0",
        "/asr/transcribe",
        "DIARIZATION",
        http_status=None,
        ok=False,
        error_code="TIMEOUT",
        db_path=db,
    )
    rec_id = recordings_repo.create_recording(
        "a.wav", "p", "s", 8, 1.0, "R", db_path=db
    )
    raw = json.dumps(
        {
            "sessionId": "12345678-90ab-cdef-1234-567890abcdef",
            "transcript": long_transcript,
            "note": f"Bearer {fake_key}",
        }
    )
    segments_repo.save_transcription(
        rec_id,
        [{"idx": 0, "start_sec": 0.0, "end_sec": 1.0, "text_original": "hi"}],
        source="real",
        model="m",
        raw_json=raw,
        db_path=db,
    )
    ai_runs_repo.create_ai_run(
        rec_id,
        "muse-spark-1.1",
        "v1",
        "real",
        raw_json=json.dumps({"reply": "ok", "accessToken": fake_key}),
        db_path=db,
    )
    out = tmp_path / "API-EVIDENCE.md"
    assert (
        evidence.main(
            ["generate_api_evidence.py", "--db", str(db), "--out", str(out)]
        )
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert fake_key not in text
    assert long_transcript not in text
    assert long_transcript[:100] in text
    assert "429 responses: 1" in text
    assert "timeouts: 1" in text
    assert "12345678-90ab-cdef-1234-567890abcdef" not in text
    assert "12345678…" in text
    assert "/asr/transcribe" in text


def test_readme_makes_no_providing_claims():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    lowered = readme.lower()
    assert "no certification" in lowered
    assert "no legal advice" in lowered
    for phrase in (
        "provides legal advice",
        "certifies",
        "certification provided",
        "decides appeals",
        "appeal outcome",
    ):
        assert phrase not in lowered, f"README provides: {phrase}"


def test_readme_claim_table_paths_exist():
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    in_table = False
    rows = 0
    for line in lines:
        if line.startswith("## What is built"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table or not line.startswith("|"):
            continue
        if "Capability" in line or "---" in line:
            continue
        rows += 1
        paths = [
            match for match in re.findall(r"`([^`]+)`", line) if "/" in match
        ]
        assert paths, f"claim row has no evidence path: {line}"
        for path in paths:
            assert (ROOT / path).exists(), f"missing evidence: {path}"
    assert rows >= 10


_KEY_VALUE_RE = re.compile(
    r"META_API_KEY\s*=\s*[\"']?([A-Za-z0-9_\-\.]{16,})[\"']?"
)
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
_BEARER_TOKEN_RE = re.compile(r"Bearer [A-Za-z0-9_\-\.]{20,}")
_ALLOW_WORDS = (
    "fake",
    "test",
    "placeholder",
    "your",
    "example",
    "changeme",
    "xxx",
    "key_here",
    "here_from",
)


def _looks_real(token: str) -> bool:
    lowered = token.lower()
    return not any(word in lowered for word in _ALLOW_WORDS)


def test_tracked_files_have_no_keys_and_ignores_cover():
    git = shutil.which("git")
    if git is None:
        pytest.skip("git not available")
    proc = subprocess.run(
        [git, "-c", "safe.directory=*", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        pytest.skip("git ls-files failed")
    offenders = []
    for rel in proc.stdout.splitlines():
        if not rel or rel.endswith((".pyc", ".db", ".wav", ".mp3", ".docx")):
            continue
        path = ROOT / rel
        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _KEY_VALUE_RE.findall(text):
            if _looks_real(match):
                offenders.append(f"{rel}: META_API_KEY value")
        for match in _SK_RE.findall(text):
            if _looks_real(match):
                offenders.append(f"{rel}: sk- token")
        for match in _BEARER_TOKEN_RE.findall(text):
            if _looks_real(match):
                offenders.append(f"{rel}: Bearer token")
    assert offenders == []
    ignore_lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore_lines
    assert "*.db" in ignore_lines
    assert any("storage/uploads" in line for line in ignore_lines)
