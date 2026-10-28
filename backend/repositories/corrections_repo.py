"""Corrections repository: traceable reviewer edits. Parameterized SQL only."""

from pathlib import Path

from database.db import get_connection
from database.schema import init_db

ALLOWED_DECISIONS = ("ACCEPT_AI", "EDIT_TEXT", "DISMISS_FLAG")


def create_correction(
    segment_id: int,
    flag_id: int | None,
    before_text: str,
    after_text: str,
    reviewer_name: str,
    decision: str,
    reason: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Insert a correction row; return its id.

    ValueError when reviewer_name is empty or decision is invalid.
    """
    if not reviewer_name or not reviewer_name.strip():
        raise ValueError("reviewer_name is required")
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"invalid decision: {decision!r}")
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO corrections
               (segment_id, flag_id, before_text, after_text,
                reviewer_name, decision, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                segment_id,
                flag_id,
                before_text,
                after_text,
                reviewer_name.strip(),
                decision,
                reason,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_corrections_by_segment(
    segment_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """List a segment's corrections ordered by id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM corrections WHERE segment_id = ? ORDER BY id",
            (segment_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_corrections_by_recording(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """List a recording's corrections via a segments join, ordered by id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT corrections.* FROM corrections
               JOIN segments ON corrections.segment_id = segments.id
               WHERE segments.recording_id = ?
               ORDER BY corrections.id""",
            (recording_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
