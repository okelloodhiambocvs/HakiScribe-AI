"""speaker_roles repository: one court role per speaker label. Parameterized SQL only."""

from pathlib import Path

from database.db import get_connection
from database.schema import init_db


def list_roles_by_recording(
    recording_id: int, db_path: str | Path | None = None
) -> dict[str, str]:
    """Map speaker_label to role for a recording (assigned roles only)."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT speaker_label, role FROM speaker_roles WHERE recording_id = ?",
            (recording_id,),
        ).fetchall()
        return {row["speaker_label"]: row["role"] for row in rows}
    finally:
        conn.close()
