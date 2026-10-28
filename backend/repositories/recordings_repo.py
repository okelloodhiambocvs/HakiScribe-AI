"""Recordings repository: ingested hearing rows. Parameterized SQL only."""

from pathlib import Path

from database.db import get_connection
from database.schema import init_db


def create_recording(
    filename: str,
    stored_path: str,
    sha256: str,
    size_bytes: int,
    duration_sec: float | None,
    uploaded_by: str,
    synthetic_attestation: bool = True,
    db_path: str | Path | None = None,
) -> int:
    """Insert a recording row; return its id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO recordings
               (filename, stored_path, sha256, size_bytes, duration_sec,
                uploaded_by, synthetic_attestation)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                filename,
                stored_path,
                sha256,
                size_bytes,
                duration_sec,
                uploaded_by,
                int(synthetic_attestation),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_recording(recording_id: int, db_path: str | Path | None = None) -> dict | None:
    """Fetch one recording by id; None when missing."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def list_recordings(db_path: str | Path | None = None) -> list[dict]:
    """List all recordings ordered by id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM recordings ORDER BY id").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
