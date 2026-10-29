"""Recordings repository: ingested hearing rows. Parameterized SQL only."""

import os
import sqlite3
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
    capture_source: str = "upload",
    db_path: str | Path | None = None,
) -> int:
    """Insert a recording row; return its id."""
    if capture_source not in ("upload", "live"):
        raise ValueError(f"invalid capture source: {capture_source!r}")
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO recordings
               (filename, stored_path, sha256, size_bytes, duration_sec,
                uploaded_by, synthetic_attestation, capture_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                filename,
                stored_path,
                sha256,
                size_bytes,
                duration_sec,
                uploaded_by,
                int(synthetic_attestation),
                capture_source,
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


def check_database(db_path: str | Path | None = None) -> dict:
    """Probe reachability, writability, and user_version without changing data.

    Never creates the database file and never calls init_db: a missing
    file with a writable directory reports healthy ("not created yet").
    """
    from database.db import get_db_path

    path = get_db_path(db_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "reachable": False,
            "writable": False,
            "user_version": None,
            "error": f"cannot create directory: {exc}",
        }
    if not path.exists():
        if os.access(path.parent, os.W_OK):
            return {
                "reachable": True,
                "writable": True,
                "user_version": None,
                "error": None,
                "note": "not created yet",
            }
        return {
            "reachable": False,
            "writable": False,
            "user_version": None,
            "error": "directory not writable",
        }
    try:
        conn = get_connection(path)
    except sqlite3.Error as exc:
        return {
            "reachable": False,
            "writable": False,
            "user_version": None,
            "error": str(exc),
        }
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()
        return {
            "reachable": True,
            "writable": True,
            "user_version": int(version),
            "error": None,
        }
    except sqlite3.Error as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return {
            "reachable": True,
            "writable": False,
            "user_version": None,
            "error": str(exc),
        }
    finally:
        conn.close()


def delete_recording(
    recording_id: int, db_path: str | Path | None = None
) -> bool:
    """Delete one recording row; children cascade, api_calls unlinks.

    Returns True when a row was deleted, False when the id was missing.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM recordings WHERE id = ?", (recording_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
