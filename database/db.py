"""SQLite connection helpers for HakiScribe-AI V2.

Only `backend/repositories/` should import this module.
No Streamlit, no Meta API calls, no keys here.
"""

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("data/hakiscribe.db")
DB_PATH_ENV_VAR = "HAKISCRIBE_DB_PATH"


def get_db_path(db_path: str | Path | None = None) -> Path:
    """Resolve the database file path.

    Precedence: explicit argument, then the HAKISCRIBE_DB_PATH environment
    variable, then DEFAULT_DB_PATH.
    """
    if db_path is not None:
        return Path(db_path)
    env_path = os.getenv(DB_PATH_ENV_VAR)
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with Row rows and foreign keys enforced."""
    path = get_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
