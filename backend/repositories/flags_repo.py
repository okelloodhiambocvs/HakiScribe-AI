"""Flags repository: Spark review flags on segments. Parameterized SQL only."""

from pathlib import Path

from database.db import get_connection
from database.schema import init_db

ALLOWED_STATUSES = ("OPEN", "RESOLVED", "DISMISSED")


def create_flag(
    segment_id: int,
    flag_type: str,
    severity: str,
    message: str,
    evidence: str | None = None,
    created_by_model: str = "muse-spark",
    db_path: str | Path | None = None,
) -> int:
    """Insert an OPEN flag; return its id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO flags
               (segment_id, flag_type, severity, message, evidence, created_by_model)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (segment_id, flag_type, severity, message, evidence, created_by_model),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_flag(flag_id: int, db_path: str | Path | None = None) -> dict | None:
    """Fetch one flag by id; None when missing."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM flags WHERE id = ?", (flag_id,)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def list_flags_by_segment(
    segment_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """List a segment's flags ordered by id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM flags WHERE segment_id = ? ORDER BY id", (segment_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_open_flags(db_path: str | Path | None = None) -> list[dict]:
    """List all OPEN flags ordered by id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM flags WHERE status = 'OPEN' ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_flag_status(
    flag_id: int,
    status: str,
    resolved_by: str | None = None,
    resolution_note: str | None = None,
    db_path: str | Path | None = None,
) -> bool:
    """Set a flag's status. RESOLVED/DISMISSED stamps resolved_at; reopening
    to OPEN clears the resolution fields. ValueError on invalid status."""
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"invalid flag status: {status!r}")
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        if status == "OPEN":
            cur = conn.execute(
                """UPDATE flags
                   SET status = 'OPEN', resolved_at = NULL,
                       resolved_by = NULL, resolution_note = NULL
                   WHERE id = ?""",
                (flag_id,),
            )
        else:
            cur = conn.execute(
                """UPDATE flags
                   SET status = ?, resolved_at = CURRENT_TIMESTAMP,
                       resolved_by = ?, resolution_note = ?
                   WHERE id = ?""",
                (status, resolved_by, resolution_note, flag_id),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
