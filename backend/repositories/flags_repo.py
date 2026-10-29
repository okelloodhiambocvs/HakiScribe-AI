"""Flags repository: Spark review flags on segments. Parameterized SQL only."""

from pathlib import Path

from database.db import get_connection
from database.schema import init_db

ALLOWED_STATUSES = ("OPEN", "RESOLVED", "DISMISSED", "RETAINED")


def create_flag(
    segment_id: int,
    flag_type: str,
    severity: str,
    message: str,
    evidence: str | None = None,
    created_by_model: str = "muse-spark",
    suggestion: str | None = None,
    related_segment_id: int | None = None,
    prompt_version: str | None = None,
    evidence_verified: int = 0,
    db_path: str | Path | None = None,
) -> int:
    """Insert an OPEN flag; return its id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO flags
               (segment_id, flag_type, severity, message, evidence,
                created_by_model, suggestion, related_segment_id,
                prompt_version, evidence_verified)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                segment_id,
                flag_type,
                severity,
                message,
                evidence,
                created_by_model,
                suggestion,
                related_segment_id,
                prompt_version,
                evidence_verified,
            ),
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


def list_unresolved_by_recording(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """List OPEN and RETAINED flags with segment context, ordered by idx."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT flags.*, segments.idx AS segment_idx,
                      segments.start_sec, segments.end_sec, segments.speaker
               FROM flags JOIN segments ON flags.segment_id = segments.id
               WHERE segments.recording_id = ?
                 AND flags.status IN ('OPEN', 'RETAINED')
               ORDER BY segments.idx, flags.id""",
            (recording_id,),
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


def list_flags_by_recording(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """List a recording's flags with segment_idx, ordered by idx then id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT flags.*, segments.idx AS segment_idx
               FROM flags JOIN segments ON flags.segment_id = segments.id
               WHERE segments.recording_id = ?
               ORDER BY segments.idx, flags.id""",
            (recording_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def replace_review_flags(
    recording_id: int,
    flags: list[dict],
    created_by_model: str,
    db_path: str | Path | None = None,
) -> tuple[list[int], int]:
    """Refresh a recording's AI suggestions in ONE transaction.

    Deletes only flags that are OPEN, AI-created (muse-spark*), and have
    no linked corrections; decided flags are kept. New flags duplicating
    a kept flag (segment, type, evidence) are skipped. Returns (new ids,
    skipped-duplicate count).
    """
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """DELETE FROM flags
               WHERE id IN (
                   SELECT flags.id FROM flags
                   JOIN segments ON flags.segment_id = segments.id
                   WHERE segments.recording_id = ?
                     AND flags.status = 'OPEN'
                     AND flags.created_by_model LIKE 'muse-spark%'
                     AND NOT EXISTS (
                         SELECT 1 FROM corrections
                         WHERE corrections.flag_id = flags.id
                     )
               )""",
            (recording_id,),
        )
        kept = {
            (row["segment_id"], row["flag_type"], row["evidence"])
            for row in conn.execute(
                """SELECT flags.segment_id, flags.flag_type, flags.evidence
                   FROM flags JOIN segments ON flags.segment_id = segments.id
                   WHERE segments.recording_id = ?""",
                (recording_id,),
            ).fetchall()
        }
        ids = []
        skipped = 0
        for flag in flags:
            key = (flag["segment_id"], flag["flag_type"], flag["evidence"])
            if key in kept:
                skipped += 1
                continue
            kept.add(key)
            cur = conn.execute(
                """INSERT INTO flags
                   (segment_id, flag_type, severity, message, evidence,
                    created_by_model, suggestion, related_segment_id,
                    prompt_version, evidence_verified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    flag["segment_id"],
                    flag["flag_type"],
                    flag.get("severity") or "MEDIUM",
                    flag["message"],
                    flag.get("evidence"),
                    created_by_model,
                    flag.get("suggestion"),
                    flag.get("related_segment_id"),
                    flag.get("prompt_version"),
                    flag.get("evidence_verified", 0),
                ),
            )
            ids.append(cur.lastrowid)
        conn.commit()
        return ids, skipped
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
