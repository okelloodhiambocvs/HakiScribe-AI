"""Corrections repository: traceable reviewer edits. Parameterized SQL only.

Multi-step operations (edit, decision, role assignment) run in ONE
connection and ONE transaction via the apply_* functions below, using
small patchable row helpers so tests can prove rollback.
"""

import re
from pathlib import Path

from backend.core.errors import EditConflictError
from database.db import get_connection
from database.schema import init_db

ALLOWED_DECISIONS = (
    "ACCEPT_SUGGESTION",
    "EDIT_TEXT",
    "DISMISS_FLAG",
    "RETAIN_UNCERTAIN",
    "ASSIGN_SPEAKER_ROLE",
)
REASON_REQUIRED_DECISIONS = ("DISMISS_FLAG", "RETAIN_UNCERTAIN", "EDIT_TEXT")
ALLOWED_FIELDS = ("text", "speaker_role")
FLAG_DECISIONS = (
    "ACCEPT_SUGGESTION",
    "EDIT_TEXT",
    "DISMISS_FLAG",
    "RETAIN_UNCERTAIN",
)


def _check_reviewer(reviewer_name: str) -> str:
    """Return the stripped reviewer name; ValueError when empty."""
    if not reviewer_name or not reviewer_name.strip():
        raise ValueError("reviewer_name is required")
    return reviewer_name.strip()


def _check_decision(decision: str, allowed=ALLOWED_DECISIONS) -> None:
    """ValueError when the decision is outside the allowed set."""
    if decision not in allowed:
        raise ValueError(f"invalid decision: {decision!r}")


def _check_reason(decision: str, reason: str | None) -> None:
    """ValueError when a reason-required decision has no reason."""
    if decision in REASON_REQUIRED_DECISIONS and not (
        reason and reason.strip()
    ):
        raise ValueError(f"reason is required for decision {decision}")


def _check_field(field: str) -> None:
    """ValueError when the correction field is outside text/speaker_role."""
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"invalid correction field: {field!r}")


def _clean_new_text(new_text: str | None) -> str:
    """Strip reviewer input; ValueError when empty."""
    if new_text is None or not new_text.strip():
        raise ValueError("edited text must not be empty")
    return new_text.strip()


def create_correction(
    segment_id: int,
    flag_id: int | None,
    before_text: str,
    after_text: str,
    reviewer_name: str,
    decision: str,
    reason: str | None = None,
    field: str = "text",
    db_path: str | Path | None = None,
) -> int:
    """Insert a correction row; return its id.

    ValueError when the reviewer is empty, the decision or field is
    invalid, or a reason-required decision has no reason.
    """
    reviewer = _check_reviewer(reviewer_name)
    _check_decision(decision)
    _check_reason(decision, reason)
    _check_field(field)
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO corrections
               (segment_id, flag_id, before_text, after_text,
                reviewer_name, decision, reason, field)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                segment_id,
                flag_id,
                before_text,
                after_text,
                reviewer,
                decision,
                reason,
                field,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _update_current_text(conn, segment_id: int, new_text: str) -> None:
    """Set text_current (+updated_at) on an open connection. No commit."""
    conn.execute(
        """UPDATE segments
           SET text_current = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (new_text, segment_id),
    )


def _insert_correction_row(
    conn,
    segment_id: int,
    flag_id: int | None,
    before_text: str,
    after_text: str,
    reviewer: str,
    decision: str,
    reason: str | None,
    field: str,
) -> int:
    """Insert one correction row on an open connection. No commit."""
    cur = conn.execute(
        """INSERT INTO corrections
           (segment_id, flag_id, before_text, after_text,
            reviewer_name, decision, reason, field)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            segment_id,
            flag_id,
            before_text,
            after_text,
            reviewer,
            decision,
            reason,
            field,
        ),
    )
    return cur.lastrowid


def _set_flag_decided(
    conn, flag_id: int, status: str, reviewer: str, note: str | None
) -> None:
    """Resolve a flag with who/when/why on an open connection. No commit."""
    conn.execute(
        """UPDATE flags
           SET status = ?, resolved_at = CURRENT_TIMESTAMP,
               resolved_by = ?, resolution_note = ?
           WHERE id = ?""",
        (status, reviewer, note, flag_id),
    )


def _upsert_speaker_role(
    conn, recording_id: int, speaker_label: str, role: str, reviewer: str
) -> None:
    """Insert or replace a speaker role on an open connection. No commit."""
    conn.execute(
        """INSERT INTO speaker_roles
           (recording_id, speaker_label, role, assigned_by, assigned_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(recording_id, speaker_label) DO UPDATE SET
               role = excluded.role,
               assigned_by = excluded.assigned_by,
               assigned_at = CURRENT_TIMESTAMP""",
        (recording_id, speaker_label, role, reviewer),
    )


def apply_text_edit(
    segment_id: int,
    expected_current: str | None,
    new_text: str | None,
    reviewer_name: str,
    decision: str,
    reason: str | None,
    field: str = "text",
    flag_id: int | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """Apply a text edit plus its correction row in ONE transaction.

    expected_current is the text the reviewer saw; a mismatch raises
    EditConflictError and writes nothing. Empty and no-op edits are
    rejected. Returns {correction_id, before_text, after_text}.
    """
    reviewer = _check_reviewer(reviewer_name)
    _check_decision(decision)
    _check_reason(decision, reason)
    _check_field(field)
    clean = _clean_new_text(new_text)
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT text_current FROM segments WHERE id = ?", (segment_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"segment not found: {segment_id}")
        if flag_id is not None:
            flag_row = conn.execute(
                "SELECT id FROM flags WHERE id = ?", (flag_id,)
            ).fetchone()
            if flag_row is None:
                raise ValueError(f"flag not found: {flag_id}")
        current = row["text_current"]
        if expected_current is not None and current != expected_current:
            raise EditConflictError(
                f"segment {segment_id} changed since review started",
                user_message=(
                    "This segment changed while you were editing. "
                    "Reload and reapply your edit."
                ),
            )
        if clean == current:
            raise ValueError("no changes to save: text is identical")
        _update_current_text(conn, segment_id, clean)
        correction_id = _insert_correction_row(
            conn,
            segment_id,
            flag_id,
            current,
            clean,
            reviewer,
            decision,
            reason,
            field,
        )
        conn.commit()
        return {
            "correction_id": correction_id,
            "before_text": current,
            "after_text": clean,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_decision(
    flag_id: int,
    decision: str,
    reviewer_name: str,
    reason: str | None,
    new_text: str | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """Apply one flag decision in ONE transaction.

    ACCEPT_SUGGESTION runs through the same edit path (text) or the
    role path (SPEAKER_ATTRIBUTION hints, whose suggestion is already
    taxonomy-validated). EDIT_TEXT needs new_text; DISMISS_FLAG and
    RETAIN_UNCERTAIN record the unchanged text with the reason.
    Returns {correction_id, status}.
    """
    reviewer = _check_reviewer(reviewer_name)
    if decision not in FLAG_DECISIONS:
        raise ValueError(f"invalid flag decision: {decision!r}")
    _check_reason(decision, reason)
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        flag = conn.execute(
            """SELECT flags.*, segments.text_current, segments.recording_id,
                      segments.speaker_label
               FROM flags JOIN segments ON flags.segment_id = segments.id
               WHERE flags.id = ?""",
            (flag_id,),
        ).fetchone()
        if flag is None:
            raise ValueError(f"flag not found: {flag_id}")
        current = flag["text_current"]
        if decision == "ACCEPT_SUGGESTION":
            suggestion = flag["suggestion"]
            if suggestion is None or not suggestion.strip():
                raise ValueError("flag has no suggestion to accept")
            if flag["flag_type"] == "SPEAKER_ATTRIBUTION":
                role_row = conn.execute(
                    """SELECT role FROM speaker_roles
                       WHERE recording_id = ? AND speaker_label = ?""",
                    (flag["recording_id"], flag["speaker_label"]),
                ).fetchone()
                before = role_row["role"] if role_row else ""
                _upsert_speaker_role(
                    conn,
                    flag["recording_id"],
                    flag["speaker_label"],
                    suggestion,
                    reviewer,
                )
                correction_id = _insert_correction_row(
                    conn,
                    flag["segment_id"],
                    flag_id,
                    before,
                    suggestion,
                    reviewer,
                    decision,
                    reason,
                    "speaker_role",
                )
            else:
                clean = _clean_new_text(suggestion)
                evidence = flag["evidence"] or ""
                if not evidence or evidence.lower() not in current.lower():
                    raise ValueError(
                        "the quoted evidence is no longer in the segment "
                        "text; use Edit instead"
                    )
                new_text = re.sub(
                    re.escape(evidence),
                    lambda _match: clean,
                    current,
                    count=1,
                    flags=re.IGNORECASE,
                )
                if new_text == current:
                    raise ValueError("no changes to save: text is identical")
                _update_current_text(conn, flag["segment_id"], new_text)
                correction_id = _insert_correction_row(
                    conn,
                    flag["segment_id"],
                    flag_id,
                    current,
                    new_text,
                    reviewer,
                    decision,
                    reason,
                    "text",
                )
            status = "RESOLVED"
        elif decision == "EDIT_TEXT":
            clean = _clean_new_text(new_text)
            if clean == current:
                raise ValueError("no changes to save: text is identical")
            _update_current_text(conn, flag["segment_id"], clean)
            correction_id = _insert_correction_row(
                conn,
                flag["segment_id"],
                flag_id,
                current,
                clean,
                reviewer,
                decision,
                reason,
                "text",
            )
            status = "RESOLVED"
        elif decision == "DISMISS_FLAG":
            correction_id = _insert_correction_row(
                conn,
                flag["segment_id"],
                flag_id,
                current,
                current,
                reviewer,
                decision,
                reason,
                "text",
            )
            status = "DISMISSED"
        else:  # RETAIN_UNCERTAIN
            correction_id = _insert_correction_row(
                conn,
                flag["segment_id"],
                flag_id,
                current,
                current,
                reviewer,
                decision,
                reason,
                "text",
            )
            status = "RETAINED"
        _set_flag_decided(conn, flag_id, status, reviewer, reason)
        conn.commit()
        return {"correction_id": correction_id, "status": status}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_role_assignment(
    recording_id: int,
    speaker_label: str,
    role: str,
    reviewer_name: str,
    reason: str | None,
    decision: str = "ASSIGN_SPEAKER_ROLE",
    db_path: str | Path | None = None,
) -> dict:
    """Assign a speaker role plus its correction row in ONE transaction.

    The correction anchors on the label's first segment. The role must
    already be taxonomy-validated by the caller.
    Returns {correction_id, before_role, after_role}.
    """
    reviewer = _check_reviewer(reviewer_name)
    _check_decision(decision)
    _check_reason(decision, reason)
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        segment = conn.execute(
            """SELECT id FROM segments
               WHERE recording_id = ? AND speaker_label = ?
               ORDER BY idx LIMIT 1""",
            (recording_id, speaker_label),
        ).fetchone()
        if segment is None:
            raise ValueError(
                f"unknown speaker label {speaker_label!r} "
                f"for recording {recording_id}"
            )
        role_row = conn.execute(
            """SELECT role FROM speaker_roles
               WHERE recording_id = ? AND speaker_label = ?""",
            (recording_id, speaker_label),
        ).fetchone()
        before = role_row["role"] if role_row else ""
        _upsert_speaker_role(conn, recording_id, speaker_label, role, reviewer)
        correction_id = _insert_correction_row(
            conn,
            segment["id"],
            None,
            before,
            role,
            reviewer,
            decision,
            reason,
            "speaker_role",
        )
        conn.commit()
        return {
            "correction_id": correction_id,
            "before_role": before,
            "after_role": role,
        }
    except Exception:
        conn.rollback()
        raise
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
