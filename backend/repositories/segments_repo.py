"""Segments repository: transcript segments. text_original is never updated."""

from pathlib import Path

from database.db import get_connection
from database.schema import init_db

_REQUIRED_KEYS = ("idx", "start_sec", "end_sec", "text_original")


def create_segment(
    recording_id: int,
    idx: int,
    start_sec: float,
    end_sec: float,
    speaker: str,
    confidence: float | None,
    text_original: str,
    language: str = "mixed",
    db_path: str | Path | None = None,
) -> int:
    """Insert one segment; text_current starts equal to text_original."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO segments
               (recording_id, idx, start_sec, end_sec, speaker, confidence,
                language, text_original, text_current)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                recording_id,
                idx,
                start_sec,
                end_sec,
                speaker,
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
        ids = []
        for seg in segments:
            missing = [key for key in _REQUIRED_KEYS if key not in seg]
            if missing:
                raise ValueError(f"segment missing required keys: {missing}")
            cur = conn.execute(
                """INSERT INTO segments
                   (recording_id, idx, start_sec, end_sec, speaker, confidence,
                    language, text_original, text_current)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    recording_id,
                    seg["idx"],
                    seg["start_sec"],
                    seg["end_sec"],
                    seg.get("speaker") or "UNKNOWN",
                    seg.get("confidence"),
                    seg.get("language") or "mixed",
                    seg["text_original"],
                    seg["text_original"],
                ),
            )
            ids.append(cur.lastrowid)
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
