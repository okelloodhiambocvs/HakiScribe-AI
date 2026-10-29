"""ai_runs repository: AI review run ledger. Parameterized SQL only."""

from pathlib import Path

from database.db import get_connection
from database.schema import init_db

ALLOWED_MODES = ("real", "mock")


def create_ai_run(
    recording_id: int,
    model: str,
    prompt_version: str,
    mode: str,
    status: str = "complete",
    flags_created: int = 0,
    flags_dropped: int = 0,
    raw_json: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Insert one review run row; return its id."""
    if mode not in ALLOWED_MODES:
        raise ValueError(f"invalid ai_runs mode: {mode!r}")
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO ai_runs
               (recording_id, model, prompt_version, mode, status,
                flags_created, flags_dropped, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                recording_id,
                model,
                prompt_version,
                mode,
                status,
                flags_created,
                flags_dropped,
                raw_json,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_ai_runs_by_recording(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """List a recording's review runs, newest first."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ai_runs WHERE recording_id = ? ORDER BY id DESC",
            (recording_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_latest_ai_run(
    recording_id: int, db_path: str | Path | None = None
) -> dict | None:
    """Fetch the newest review run; None when the recording was never run."""
    runs = list_ai_runs_by_recording(recording_id, db_path=db_path)
    return runs[0] if runs else None


def list_recent_ai_runs(
    limit: int = 10, db_path: str | Path | None = None
) -> list[dict]:
    """List review runs across recordings, newest first, capped at limit."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ai_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
