"""V2 SQLite schema: recordings, segments, flags, corrections, exports.

Creation only — this module changes no data. `segments.text_original` is
immutable by trigger; edits live in `corrections` rows. The schema is
versioned with PRAGMA user_version; init_db migrates old files in place.
"""

import threading
from pathlib import Path

from database.db import get_connection, get_db_path

SCHEMA_VERSION = 8

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


# v3 -> v4: review metadata on flags plus the ai_runs ledger. related
# segment ids reference segments(id); recording deletes cascade the runs.
_FLAGS_V4_COLUMNS = (
    ("suggestion", "TEXT"),
    ("related_segment_id", "INTEGER"),
    ("prompt_version", "TEXT"),
    ("evidence_verified", "INTEGER NOT NULL DEFAULT 0"),
)

_AI_RUNS_SQL = """
CREATE TABLE IF NOT EXISTS ai_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('real', 'mock')),
    status TEXT NOT NULL DEFAULT 'complete',
    flags_created INTEGER NOT NULL DEFAULT 0,
    flags_dropped INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ai_runs_recording_id ON ai_runs(recording_id);
"""


def _migrate_to_v4(conn) -> None:
    """Add flags review columns + ai_runs ledger; stamp user_version 4."""
    existing = _column_names(conn, "flags")
    for name, ddl in _FLAGS_V4_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE flags ADD COLUMN {name} {ddl}")
    conn.executescript(_AI_RUNS_SQL)
    conn.execute("PRAGMA user_version = 4")


# v4 -> v5: human-review traceability. corrections.field marks text vs
# speaker_role edits; speaker_roles holds one role per speaker label;
# review_events logs review-time activity. Recording deletes cascade.
_SPEAKER_ROLES_SQL = """
CREATE TABLE IF NOT EXISTS speaker_roles (
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    speaker_label TEXT NOT NULL,
    role TEXT NOT NULL,
    assigned_by TEXT NOT NULL,
    assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(recording_id, speaker_label)
);

CREATE INDEX IF NOT EXISTS idx_speaker_roles_recording_id
    ON speaker_roles(recording_id);
"""

_REVIEW_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL,
    event TEXT NOT NULL,
    at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_review_events_recording_id
    ON review_events(recording_id);
"""


def _migrate_to_v5(conn) -> None:
    """Add corrections.field + speaker_roles + review_events; stamp v5."""
    if "field" not in _column_names(conn, "corrections"):
        conn.execute(
            "ALTER TABLE corrections ADD COLUMN field TEXT NOT NULL DEFAULT 'text'"
        )
    conn.executescript(_SPEAKER_ROLES_SQL)
    conn.executescript(_REVIEW_EVENTS_SQL)
    conn.execute("PRAGMA user_version = 5")


# v5 -> v6: evaluation snapshot columns on exports. All nullable: metrics
# that cannot be computed stay NULL instead of placeholder numbers.
_EXPORTS_V6_COLUMNS = (
    ("ref_wer", "REAL"),
    ("ref_cer", "REAL"),
    ("speaker_attribution_pct", "REAL"),
    ("boundary_error_ms", "REAL"),
    ("traceability_pct", "REAL"),
    ("review_seconds", "REAL"),
)


def _migrate_to_v6(conn) -> None:
    """Add exports evaluation columns; stamp user_version 6."""
    existing = _column_names(conn, "exports")
    for name, ddl in _EXPORTS_V6_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE exports ADD COLUMN {name} {ddl}")
    conn.execute("PRAGMA user_version = 6")


# v6 -> v7: live microphone capture. capture_source marks rows recorded
# live; segments.is_approximate marks live timestamps from our audio
# clock, replaced by batch timestamps on finalise.
_RECORDINGS_V7_COLUMNS = (
    ("capture_source", "TEXT NOT NULL DEFAULT 'upload'"),
)

_SEGMENTS_V7_COLUMNS = (
    ("is_approximate", "INTEGER NOT NULL DEFAULT 0"),
)


def _migrate_to_v7(conn) -> None:
    """Add live-capture columns; stamp user_version 7."""
    existing = _column_names(conn, "recordings")
    for name, ddl in _RECORDINGS_V7_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE recordings ADD COLUMN {name} {ddl}")
    existing = _column_names(conn, "segments")
    for name, ddl in _SEGMENTS_V7_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE segments ADD COLUMN {name} {ddl}")
    conn.execute("PRAGMA user_version = 7")


# v7 -> v8: deletion audit. deletion_log keeps content-free events
# (deleted recording id, reviewer, time) after rows and files are
# removed. No foreign key: the recording row is gone by design.
_DELETION_LOG_SQL = """
CREATE TABLE IF NOT EXISTS deletion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL,
    reviewer TEXT NOT NULL,
    deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_deletion_log_recording_id
    ON deletion_log(recording_id);
"""


def _migrate_to_v8(conn) -> None:
    """Add the deletion_log audit table; stamp user_version 8."""
    conn.executescript(_DELETION_LOG_SQL)
    conn.execute("PRAGMA user_version = 8")


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
        if version < 4:
            _migrate_to_v4(conn)
        if version < 5:
            _migrate_to_v5(conn)
        if version < 6:
            _migrate_to_v6(conn)
        if version < 7:
            _migrate_to_v7(conn)
        if version < 8:
            _migrate_to_v8(conn)
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
