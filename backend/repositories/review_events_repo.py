"""review_events repository: review-time activity log. Parameterized SQL only."""

from pathlib import Path

from database.db import get_connection
from database.schema import init_db


def record_event(
    recording_id: int,
    reviewer: str,
    event: str,
    db_path: str | Path | None = None,
) -> int:
    """Insert one review event row; return its id."""
    if not reviewer or not reviewer.strip():
        raise ValueError("reviewer is required")
    if not event or not event.strip():
        raise ValueError("event is required")
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO review_events (recording_id, reviewer, event)
               VALUES (?, ?, ?)""",
            (recording_id, reviewer.strip(), event.strip()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_events_by_recording(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """List a recording's review events ordered by id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM review_events WHERE recording_id = ? ORDER BY id",
            (recording_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
