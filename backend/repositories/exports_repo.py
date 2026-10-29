"""Exports repository: DOCX draft export records. Parameterized SQL only."""

from pathlib import Path

from database.db import get_connection
from database.schema import init_db


def create_export(
    recording_id: int,
    docx_filename: str,
    wer: float | None,
    cer: float | None,
    segments_changed_pct: float | None,
    flags_total: int,
    flags_resolved: int,
    generated_by: str,
    ref_wer: float | None = None,
    ref_cer: float | None = None,
    speaker_attribution_pct: float | None = None,
    boundary_error_ms: float | None = None,
    traceability_pct: float | None = None,
    review_seconds: float | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Insert an export row; return its id. ValueError when generated_by is empty."""
    if not generated_by or not generated_by.strip():
        raise ValueError("generated_by is required")
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO exports
               (recording_id, docx_filename, wer, cer, segments_changed_pct,
                flags_total, flags_resolved, generated_by, ref_wer, ref_cer,
                speaker_attribution_pct, boundary_error_ms, traceability_pct,
                review_seconds)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                recording_id,
                docx_filename,
                wer,
                cer,
                segments_changed_pct,
                flags_total,
                flags_resolved,
                generated_by.strip(),
                ref_wer,
                ref_cer,
                speaker_attribution_pct,
                boundary_error_ms,
                traceability_pct,
                review_seconds,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_exports_by_recording(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """List a recording's exports ordered by id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM exports WHERE recording_id = ? ORDER BY id",
            (recording_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_latest_export_by_recording(
    recording_id: int, db_path: str | Path | None = None
) -> dict | None:
    """Fetch the newest export row; None when never exported."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """SELECT * FROM exports
               WHERE recording_id = ? ORDER BY id DESC LIMIT 1""",
            (recording_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
