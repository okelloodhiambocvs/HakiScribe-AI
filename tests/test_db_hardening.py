"""V2 database hardening tests: migration, triggers, init-once, exports.

Offline schema/tables live in tests/test_database_v2.py; this file covers
the v2 migration, immutability triggers, init_db caching, and the small
config/service export items. Isolated tmp_path SQLite files only.
"""

import sqlite3

import pytest

import backend.core.config as config
from backend.integrations.meta.audio_prep import AudioPrepError as AudioPrepErrorDirect
from backend.repositories import corrections_repo, flags_repo, recordings_repo
from backend.repositories import segments_repo
from backend.repositories.segments_repo import (
    AlreadyTranscribedError,
    TranscriptionLockedError,
)
from backend.services import transcription_service
from database.db import get_connection
from database.schema import SCHEMA_SQL, SCHEMA_VERSION, init_db

TRIGGER_NAMES = {
    "trg_segments_text_original_immutable",
    "trg_corrections_no_update",
    "trg_recordings_transcription_locked",
    "trg_recordings_source_valid_insert",
    "trg_recordings_source_valid_update",
}

NEW_COLUMNS = {
    "transcription_source",
    "transcription_model",
    "transcription_raw_json",
    "transcribed_at",
}


def _user_version(db):
    conn = get_connection(db)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _recording_id(db):
    return recordings_repo.create_recording(
        filename="hardening.mp3",
        stored_path="storage/uploads/hardening.mp3",
        sha256="hardening-sha",
        size_bytes=512,
        duration_sec=None,
        uploaded_by="Reviewer Amina",
        db_path=db,
    )


def _segment_id(db, rec_id, text="Sikuwa hapo."):
    return segments_repo.create_segment(
        rec_id, 0, 0.0, 4.2, "ACCUSED", 0.6, text, db_path=db
    )


def _make_v1_database(db):
    """Build a pre-migration database: v1 tables, version 0, no triggers."""
    conn = get_connection(db)
    try:
        conn.executescript(SCHEMA_SQL)
        cur = conn.execute(
            """INSERT INTO recordings
               (filename, stored_path, sha256, size_bytes, uploaded_by)
               VALUES (?, ?, ?, ?, ?)""",
            ("old.mp3", "storage/uploads/old.mp3", "old-sha", 64, "Reviewer Amina"),
        )
        rec_id = cur.lastrowid
        conn.execute(
            """INSERT INTO segments
               (recording_id, idx, start_sec, end_sec, speaker, text_original,
                text_current)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rec_id, 0, 0.0, 1.0, "MAGISTRATE", "Court in session.", "Court in session."),
        )
        conn.commit()
    finally:
        conn.close()
    assert _user_version(db) == 0
    return rec_id


def test_migration_upgrades_old_db_in_place(tmp_path):
    db = tmp_path / "old.db"
    rec_id = _make_v1_database(db)
    init_db(db)
    assert _user_version(db) == SCHEMA_VERSION
    conn = get_connection(db)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(recordings)")}
        assert NEW_COLUMNS <= cols
        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            )
        }
        assert triggers == TRIGGER_NAMES
        rec = conn.execute(
            "SELECT * FROM recordings WHERE id = ?", (rec_id,)
        ).fetchone()
        assert rec["filename"] == "old.mp3"
        assert rec["transcription_source"] is None
        assert rec["transcription_model"] is None
        assert rec["transcription_raw_json"] is None
        assert rec["transcribed_at"] is None
        seg = conn.execute(
            "SELECT * FROM segments WHERE recording_id = ?", (rec_id,)
        ).fetchone()
        assert seg["text_original"] == "Court in session."
    finally:
        conn.close()


def test_fresh_database_matches_migrated_schema(tmp_path):
    old_db = tmp_path / "old.db"
    _make_v1_database(old_db)
    init_db(old_db)
    fresh_db = tmp_path / "fresh.db"
    init_db(fresh_db)
    assert _user_version(fresh_db) == SCHEMA_VERSION

    def _shape(db):
        conn = get_connection(db)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            recordings_cols = [
                (row[1], row[2])
                for row in conn.execute("PRAGMA table_info(recordings)")
            ]
            triggers = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                )
            }
            return tables, recordings_cols, triggers
        finally:
            conn.close()

    assert _shape(fresh_db) == _shape(old_db)


def test_text_original_trigger_blocks_raw_update(tmp_path):
    db = tmp_path / "t.db"
    seg_id = _segment_id(db, _recording_id(db))
    conn = get_connection(db)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE segments SET text_original = 'rewritten' WHERE id = ?",
                (seg_id,),
            )
    finally:
        conn.close()
    assert segments_repo.update_segment_current_text(
        seg_id, "Edited current text.", db_path=db
    )
    seg = segments_repo.get_segment(seg_id, db_path=db)
    assert seg["text_current"] == "Edited current text."
    assert seg["text_original"] == "Sikuwa hapo."


def test_corrections_updates_blocked_but_cascade_delete_works(tmp_path):
    db = tmp_path / "t.db"
    rec_id = _recording_id(db)
    seg_id = _segment_id(db, rec_id)
    flag_id = flags_repo.create_flag(
        seg_id, "LOW_CONFIDENCE", "HIGH", "Confirm wording.", db_path=db
    )
    corrections_repo.create_correction(
        seg_id, flag_id, "Sikuwa hapo.", "Si kweli, sikuwa hapo.",
        "Reviewer Amina", "EDIT_TEXT", db_path=db,
    )
    conn = get_connection(db)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE corrections SET reason = 'rewritten history'"
            )
        conn.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
        conn.commit()
        for table in ("segments", "flags", "corrections", "exports"):
            (count,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            assert count == 0
    finally:
        conn.close()


def test_transcription_source_write_once_and_validated(tmp_path):
    db = tmp_path / "t.db"
    rec_id = _recording_id(db)
    conn = get_connection(db)
    try:
        conn.execute(
            "UPDATE recordings SET transcription_source = 'real' WHERE id = ?",
            (rec_id,),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable once set"):
            conn.execute(
                "UPDATE recordings SET transcription_source = 'mock' WHERE id = ?",
                (rec_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable once set"):
            conn.execute(
                "UPDATE recordings SET transcription_source = NULL WHERE id = ?",
                (rec_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="'real' or 'mock'"):
            conn.execute(
                """INSERT INTO recordings
                   (filename, stored_path, sha256, size_bytes, uploaded_by,
                    transcription_source)
                   VALUES (?, ?, ?, ?, ?, 'bogus')""",
                ("b.mp3", "p", "h", 1, "Reviewer Amina"),
            )
    finally:
        conn.close()
    rec_id2 = recordings_repo.create_recording(
        filename="second.mp3",
        stored_path="storage/uploads/second.mp3",
        sha256="second-sha",
        size_bytes=8,
        duration_sec=None,
        uploaded_by="Reviewer Amina",
        db_path=db,
    )
    conn = get_connection(db)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="'real' or 'mock'"):
            conn.execute(
                "UPDATE recordings SET transcription_source = 'bogus' WHERE id = ?",
                (rec_id2,),
            )
    finally:
        conn.close()
    with pytest.raises(ValueError, match="invalid transcription source"):
        segments_repo.save_transcription(
            rec_id2, [], "bogus", "model", None, db_path=db
        )


def test_save_transcription_errors_and_single_write(tmp_path):
    assert issubclass(AlreadyTranscribedError, ValueError)
    assert issubclass(TranscriptionLockedError, ValueError)
    db = tmp_path / "t.db"
    with pytest.raises(ValueError, match="recording not found"):
        segments_repo.save_transcription(999, [], "mock", "m", None, db_path=db)
    rec_id = _recording_id(db)
    segments = [
        {"idx": 0, "start_sec": 0.0, "end_sec": 1.0, "text_original": "One."},
        {"idx": 1, "start_sec": 1.0, "end_sec": 2.0, "text_original": "Two."},
    ]
    ids = segments_repo.save_transcription(
        rec_id, segments, "mock", "muse-voice-transcribe-mock", None, db_path=db
    )
    assert len(ids) == 2
    with pytest.raises(AlreadyTranscribedError):
        segments_repo.save_transcription(
            rec_id, segments, "mock", "muse-voice-transcribe-mock", None,
            db_path=db,
        )
    assert len(segments_repo.list_segments(rec_id, db_path=db)) == 2


def test_init_db_body_runs_once_for_many_repository_calls(tmp_path, monkeypatch):
    calls = []
    real_get_connection = get_connection

    def counting_get_connection(db_path=None):
        calls.append(db_path)
        return real_get_connection(db_path)

    monkeypatch.setattr(
        "database.schema.get_connection", counting_get_connection
    )
    db = tmp_path / "t.db"
    rec_id = _recording_id(db)
    seg_id = _segment_id(db, rec_id)
    segments_repo.list_segments(rec_id, db_path=db)
    segments_repo.get_segment(seg_id, db_path=db)
    flags_repo.list_open_flags(db_path=db)
    assert len(calls) == 1
    other_db = tmp_path / "other.db"
    recordings_repo.list_recordings(db_path=other_db)
    assert len(calls) == 2


def test_init_db_reruns_after_file_deleted(tmp_path):
    db = tmp_path / "t.db"
    _recording_id(db)
    assert recordings_repo.list_recordings(db_path=db)
    db.unlink()
    assert recordings_repo.list_recordings(db_path=db) == []
    assert db.exists()


def test_config_all_contains_parked_model_names():
    for name in (
        "META_SAM_MODEL",
        "META_IMAGE_MODEL",
        "META_OPEN_MODEL",
        "GLIMMER_MODEL_PATH",
    ):
        assert name in config.__all__


def test_audio_prep_error_reexported_from_service():
    assert transcription_service.AudioPrepError is AudioPrepErrorDirect
    assert "AudioPrepError" in transcription_service.__all__
