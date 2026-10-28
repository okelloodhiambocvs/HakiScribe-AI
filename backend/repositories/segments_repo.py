"""Segments repository: transcript segments. text_original is never updated."""

import sqlite3
from pathlib import Path

from backend.core.errors import HakiScribeError
from database.db import get_connection
from database.schema import init_db

_REQUIRED_KEYS = ("idx", "start_sec", "end_sec", "text_original")
_ALLOWED_SOURCES = ("real", "mock")


class AlreadyTranscribedError(HakiScribeError, ValueError):
    """Recording already has a persisted transcript; nothing was written."""

    code = "already_transcribed"


class TranscriptionLockedError(HakiScribeError, ValueError):
    """Replace refused: flags/corrections exist or provenance is locked."""

    code = "transcription_locked"


def _insert_segment_row(conn, recording_id: int, seg: dict) -> int:
    """Validate and insert one segment row on an open connection.

    No commit here; the caller owns the transaction. text_current always
    starts equal to text_original.
    """
    missing = [key for key in _REQUIRED_KEYS if key not in seg]
    if missing:
        raise ValueError(f"segment missing required keys: {missing}")
    cur = conn.execute(
        """INSERT INTO segments
           (recording_id, idx, start_sec, end_sec, speaker, speaker_label,
            confidence, language, text_original, text_current)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            recording_id,
            seg["idx"],
            seg["start_sec"],
            seg["end_sec"],
            seg.get("speaker") or "UNKNOWN",
            seg.get("speaker_label"),
            seg.get("confidence"),
            seg.get("language") or "mixed",
            seg["text_original"],
            seg["text_original"],
        ),
    )
    return cur.lastrowid


def _check_source(source: str) -> None:
    """Reject transcription sources outside 'real'/'mock' (Python-side)."""
    if source not in _ALLOWED_SOURCES:
        raise ValueError(f"invalid transcription source: {source!r}")


def create_segment(
    recording_id: int,
    idx: int,
    start_sec: float,
    end_sec: float,
    speaker: str,
    confidence: float | None,
    text_original: str,
    language: str = "mixed",
    speaker_label: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Insert one segment; text_current starts equal to text_original."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO segments
               (recording_id, idx, start_sec, end_sec, speaker, speaker_label,
                confidence, language, text_original, text_current)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                recording_id,
                idx,
                start_sec,
                end_sec,
                speaker,
                speaker_label,
                confidence,
                language,
                text_original,
                text_original,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def create_segments(
    recording_id: int,
    segments: list[dict],
    db_path: str | Path | None = None,
) -> list[int]:
    """Insert many segments atomically; return ids in input order.

    Each dict needs idx, start_sec, end_sec, text_original. Missing speaker
    defaults to 'UNKNOWN', missing language to 'mixed', missing confidence
    to None. ValueError when a required key is absent.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        ids = [_insert_segment_row(conn, recording_id, seg) for seg in segments]
        conn.commit()
        return ids
    finally:
        conn.close()


def get_segment(segment_id: int, db_path: str | Path | None = None) -> dict | None:
    """Fetch one segment by id; None when missing."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM segments WHERE id = ?", (segment_id,)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def list_segments(recording_id: int, db_path: str | Path | None = None) -> list[dict]:
    """List a recording's segments ordered by idx."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM segments WHERE recording_id = ? ORDER BY idx",
            (recording_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_segment_current_text(
    segment_id: int, new_text: str, db_path: str | Path | None = None
) -> bool:
    """Update ONLY text_current and updated_at. Never touches text_original."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """UPDATE segments
               SET text_current = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (new_text, segment_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def save_transcription(
    recording_id: int,
    segments: list[dict],
    source: str,
    model: str | None,
    raw_json: str | None,
    db_path: str | Path | None = None,
) -> list[int]:
    """Persist a transcript in ONE connection and ONE transaction.

    BEGIN IMMEDIATE serializes writers: the no-transcription-yet check,
    the segment inserts, and the recording stamp commit atomically.
    Raises AlreadyTranscribedError (writing nothing) when a transcript
    exists, ValueError for a missing recording or bad source. Never
    leaks sqlite3.IntegrityError.
    """
    _check_source(source)
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT transcription_source FROM recordings WHERE id = ?",
            (recording_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"recording not found: {recording_id}")
        (existing_count,) = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE recording_id = ?",
            (recording_id,),
        ).fetchone()
        if row["transcription_source"] is not None or existing_count:
            raise AlreadyTranscribedError(
                f"recording {recording_id} already has a transcript"
            )
        ids = [_insert_segment_row(conn, recording_id, seg) for seg in segments]
        conn.execute(
            """UPDATE recordings
               SET transcription_source = ?, transcription_model = ?,
                   transcription_raw_json = ?, transcribed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (source, model, raw_json, recording_id),
        )
        conn.commit()
        return ids
    except AlreadyTranscribedError:
        conn.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise AlreadyTranscribedError(
            f"recording {recording_id} already has a transcript ({exc})"
        ) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _count_by_recording(conn, table: str, recording_id: int) -> int:
    """Count rows in flags/corrections linked to a recording's segments."""
    (count,) = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE segment_id IN "
        "(SELECT id FROM segments WHERE recording_id = ?)",
        (recording_id,),
    ).fetchone()
    return count


def replace_transcription(
    recording_id: int,
    segments: list[dict],
    source: str,
    model: str | None,
    raw_json: str | None,
    db_path: str | Path | None = None,
) -> list[int]:
    """Replace a transcript in ONE transaction; guarded by review state.

    Allowed ONLY when the recording has zero flags and zero corrections;
    otherwise raises TranscriptionLockedError and writes nothing. Also
    refuses to change transcription_source/raw_json once set (the
    write-once trigger would abort it anyway). Never leaks
    sqlite3.IntegrityError.
    """
    _check_source(source)
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT transcription_source, transcription_raw_json"
            " FROM recordings WHERE id = ?",
            (recording_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"recording not found: {recording_id}")
        flag_count = _count_by_recording(conn, "flags", recording_id)
        correction_count = _count_by_recording(conn, "corrections", recording_id)
        if flag_count or correction_count:
            raise TranscriptionLockedError(
                f"recording {recording_id} has {flag_count} flags and "
                f"{correction_count} corrections; replace refused"
            )
        if (
            row["transcription_source"] is not None
            and row["transcription_source"] != source
        ):
            raise TranscriptionLockedError(
                f"recording {recording_id} transcription_source is locked once set"
            )
        if (
            row["transcription_raw_json"] is not None
            and row["transcription_raw_json"] != raw_json
        ):
            raise TranscriptionLockedError(
                f"recording {recording_id} transcription_raw_json is locked once set"
            )
        conn.execute(
            "DELETE FROM segments WHERE recording_id = ?", (recording_id,)
        )
        ids = [_insert_segment_row(conn, recording_id, seg) for seg in segments]
        conn.execute(
            """UPDATE recordings
               SET transcription_source = ?, transcription_model = ?,
                   transcription_raw_json = ?, transcribed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (source, model, raw_json, recording_id),
        )
        conn.commit()
        return ids
    except TranscriptionLockedError:
        conn.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise TranscriptionLockedError(
            f"recording {recording_id} replace refused ({exc})"
        ) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
