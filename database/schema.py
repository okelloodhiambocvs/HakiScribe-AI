"""V2 SQLite schema: recordings, segments, flags, corrections, exports.

Creation only — this module changes no data. `segments.text_original` is
treated as immutable by convention; edits live in `corrections` rows.
"""

from pathlib import Path

from database.db import get_connection, get_db_path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    duration_sec REAL,
    uploaded_by TEXT NOT NULL,
    synthetic_attestation INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    speaker TEXT NOT NULL DEFAULT 'UNKNOWN',
    confidence REAL,
    language TEXT NOT NULL DEFAULT 'mixed',
    text_original TEXT NOT NULL,
    text_current TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    UNIQUE(recording_id, idx)
);

CREATE TABLE IF NOT EXISTS flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    flag_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'MEDIUM',
    message TEXT NOT NULL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_by_model TEXT NOT NULL DEFAULT 'muse-spark',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    resolved_by TEXT,
    resolution_note TEXT
);

CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    flag_id INTEGER REFERENCES flags(id) ON DELETE SET NULL,
    before_text TEXT NOT NULL,
    after_text TEXT NOT NULL,
    reviewer_name TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    docx_filename TEXT NOT NULL,
    wer REAL,
    cer REAL,
    segments_changed_pct REAL,
    flags_total INTEGER NOT NULL DEFAULT 0,
    flags_resolved INTEGER NOT NULL DEFAULT 0,
    generated_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_segments_recording_id ON segments(recording_id);
CREATE INDEX IF NOT EXISTS idx_flags_segment_id ON flags(segment_id);
CREATE INDEX IF NOT EXISTS idx_corrections_segment_id ON corrections(segment_id);
CREATE INDEX IF NOT EXISTS idx_exports_recording_id ON exports(recording_id);
"""


def init_db(db_path: str | Path | None = None) -> Path:
    """Create all V2 tables idempotently; return the database path used."""
    path = get_db_path(db_path)
    conn = get_connection(path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    return path
