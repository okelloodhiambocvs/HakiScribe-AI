"""deletion_log repository: content-free deletion audit. No filenames."""

from pathlib import Path

from database.db import get_connection
from database.schema import init_db


def log_deletion(
    recording_id: int, reviewer: str, db_path: str | Path | None = None
) -> int:
    """Record that a recording was deleted (id, reviewer, time only)."""
    if not (reviewer or "").strip():
        raise ValueError("reviewer name is required")
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO deletion_log (recording_id, reviewer)"
            " VALUES (?, ?)",
            (recording_id, reviewer.strip()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_deletions(db_path: str | Path | None = None) -> list[dict]:
    """List deletion events ordered by id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM deletion_log ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
