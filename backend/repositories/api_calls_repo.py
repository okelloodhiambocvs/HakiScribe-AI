"""api_calls repository: Meta API attempt log. Parameterized SQL only.

One row per HTTP attempt (success, 4xx, 5xx, 429 retries, timeouts).
Outcomes only — rows never store API keys or request/response bodies.
"""

from pathlib import Path

from database.db import get_connection
from database.schema import init_db


def create_api_call(
    provider: str,
    model: str,
    endpoint_path: str,
    mode: str,
    recording_id: int | None = None,
    http_status: int | None = None,
    ok: bool = False,
    latency_ms: float | None = None,
    audio_bytes: int | None = None,
    audio_ms: int | None = None,
    request_id: str | None = None,
    error_code: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Insert one attempt row; return its id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO api_calls
               (provider, model, endpoint_path, mode, recording_id,
                http_status, ok, latency_ms, audio_bytes, audio_ms,
                request_id, error_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                provider,
                model,
                endpoint_path,
                mode,
                recording_id,
                http_status,
                int(ok),
                latency_ms,
                audio_bytes,
                audio_ms,
                request_id,
                error_code,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_recent_api_calls(
    limit: int = 10, db_path: str | Path | None = None
) -> list[dict]:
    """List attempt rows newest-first, capped at limit."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM api_calls ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
