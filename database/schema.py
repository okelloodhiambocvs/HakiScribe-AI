"""V2 SQLite schema: recordings, segments, flags, corrections, exports.

Creation only — this module changes no data. `segments.text_original` is
immutable by trigger; edits live in `corrections` rows. The schema is
versioned with PRAGMA user_version; init_db migrates old files in place.
"""

import threading
from pathlib import Path

from database.db import get_connection, get_db_path

SCHEMA_VERSION = 3

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

# v1 -> v2: transcription provenance on recordings. Added with ALTER TABLE
# so existing databases upgrade in place; fresh databases run the same
# migration and converge on the identical schema.
_RECORDINGS_V2_COLUMNS = (
    ("transcription_source", "TEXT"),
    ("transcription_model", "TEXT"),
    ("transcription_raw_json", "TEXT"),
    ("transcribed_at", "TEXT"),
)

TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_segments_text_original_immutable
BEFORE UPDATE ON segments
WHEN OLD.text_original IS NOT NEW.text_original
BEGIN
    SELECT RAISE(ABORT, 'segments.text_original is immutable: update text_current instead');
END;

CREATE TRIGGER IF NOT EXISTS trg_corrections_no_update
BEFORE UPDATE ON corrections
BEGIN
    SELECT RAISE(ABORT, 'corrections are append-only: updates are blocked');
END;

CREATE TRIGGER IF NOT EXISTS trg_recordings_transcription_locked
BEFORE UPDATE ON recordings
WHEN (OLD.transcription_source IS NOT NULL
      AND NEW.transcription_source IS NOT OLD.transcription_source)
  OR (OLD.transcription_raw_json IS NOT NULL
      AND NEW.transcription_raw_json IS NOT OLD.transcription_raw_json)
BEGIN
    SELECT RAISE(ABORT, 'recordings transcription_source and transcription_raw_json are immutable once set');
END;

CREATE TRIGGER IF NOT EXISTS trg_recordings_source_valid_insert
BEFORE INSERT ON recordings
WHEN NEW.transcription_source IS NOT NULL
 AND NEW.transcription_source NOT IN ('real', 'mock')
BEGIN
    SELECT RAISE(ABORT, 'recordings.transcription_source must be ''real'' or ''mock''');
END;

CREATE TRIGGER IF NOT EXISTS trg_recordings_source_valid_update
BEFORE UPDATE ON recordings
WHEN NEW.transcription_source IS NOT NULL
 AND NEW.transcription_source NOT IN ('real', 'mock')
BEGIN
    SELECT RAISE(ABORT, 'recordings.transcription_source must be ''real'' or ''mock''');
END;
"""

_INITIALIZED_PATHS: set[str] = set()
_INIT_LOCK = threading.Lock()


def _column_names(conn, table: str) -> set[str]:
    """Return a table's column names via PRAGMA table_info."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _current_version(conn) -> int:
    """Return the database PRAGMA user_version (0 when never stamped)."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def _migrate_to_v2(conn) -> None:
    """Add v2 columns (guarded), install triggers, stamp user_version 2."""
    existing = _column_names(conn, "recordings")
    for name, ddl in _RECORDINGS_V2_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE recordings ADD COLUMN {name} {ddl}")
    conn.executescript(TRIGGERS_SQL)
    conn.execute("PRAGMA user_version = 2")


# v2 -> v3: raw diarization letter on segments plus the Meta API attempt
# log. api_calls stores outcomes only — never keys or request/response
# bodies. Recording deletes keep the log (recording_id SET NULL).
_API_CALLS_SQL = """
CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    endpoint_path TEXT NOT NULL,
    mode TEXT NOT NULL,
    recording_id INTEGER REFERENCES recordings(id) ON DELETE SET NULL,
    http_status INTEGER,
    ok INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL,
    audio_bytes INTEGER,
    audio_ms INTEGER,
    request_id TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_calls_recording_id ON api_calls(recording_id);
"""


def _migrate_to_v3(conn) -> None:
    """Add segments.speaker_label + api_calls log; stamp user_version 3."""
    if "speaker_label" not in _column_names(conn, "segments"):
        conn.execute("ALTER TABLE segments ADD COLUMN speaker_label TEXT")
    conn.executescript(_API_CALLS_SQL)
    conn.execute("PRAGMA user_version = 3")


def _initialize_database(path: Path) -> None:
    """Run the full init body once: base tables, then migrate to current."""
    conn = get_connection(path)
    try:
        conn.executescript(SCHEMA_SQL)
        version = _current_version(conn)
        if version < 2:
            _migrate_to_v2(conn)
        if version < 3:
            _migrate_to_v3(conn)
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str | Path | None = None) -> Path:
    """Create/migrate all V2 tables idempotently; return the path used.

    Skips work when this process already initialized the same resolved
    path and the file still exists. Fresh tmp paths and deleted-and-
    recreated files always re-run the body.
    """
    path = get_db_path(db_path)
    key = str(path.resolve())
    with _INIT_LOCK:
        if key in _INITIALIZED_PATHS and path.exists():
            return path
    _initialize_database(path)
    with _INIT_LOCK:
        _INITIALIZED_PATHS.add(key)
    return path
