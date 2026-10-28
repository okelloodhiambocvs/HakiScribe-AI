"""System health checks: database, ffmpeg, API config, and run mode.

Every check reports name, status (OK/WARN/FAIL), and a message. Messages
never contain the API key — only booleans, hosts, and model names.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from backend.core import config
from backend.integrations.meta.audio_prep import ffmpeg_available
from backend.repositories import recordings_repo

_VERSION_SUFFIX_RE = re.compile(r"[.-]v?\d+(\.\d+)*$")
_DEV_HOST = "dev.meta.ai"
_EXPECTED_BASE = "https://api.meta.ai/v1"


@dataclass(frozen=True)
class HealthCheck:
    """One named system check result."""

    name: str
    status: str  # "OK", "WARN", or "FAIL"
    message: str


def _api_key_configured() -> bool:
    is_configured = getattr(config, "is_configured", None)
    if callable(is_configured):
        try:
            return bool(is_configured())
        except Exception:
            pass
    return bool(os.environ.get("META_API_KEY"))


def _api_base() -> str:
    return (
        getattr(config, "META_API_BASE", "") or os.environ.get("META_API_BASE", "")
    ).strip()


def _voice_model() -> str:
    return (
        getattr(config, "META_VOICE_MODEL", "")
        or os.environ.get("META_VOICE_MODEL", "")
    ).strip()


def check_system(db_path=None) -> list[HealthCheck]:
    """Run every system check; never raises, never leaks the API key."""
    checks: list[HealthCheck] = []

    probe = recordings_repo.check_database(db_path)
    if not probe["reachable"]:
        checks.append(
            HealthCheck(
                "database",
                "FAIL",
                f"database unreachable: {probe['error'] or 'unknown error'}",
            )
        )
    elif not probe["writable"]:
        checks.append(
            HealthCheck(
                "database",
                "FAIL",
                f"database not writable: {probe['error'] or 'unknown error'}",
            )
        )
    elif probe["user_version"] is None:
        checks.append(
            HealthCheck(
                "database", "OK", "reachable, writable, not created yet"
            )
        )
    else:
        checks.append(
            HealthCheck(
                "database",
                "OK",
                f"reachable, writable, schema v{probe['user_version']}",
            )
        )

    if ffmpeg_available():
        checks.append(HealthCheck("ffmpeg", "OK", "ffmpeg available"))
    else:
        checks.append(HealthCheck("ffmpeg", "FAIL", "ffmpeg not available"))

    key_ok = _api_key_configured()
    if key_ok:
        checks.append(HealthCheck("api_key", "OK", "API key configured"))
    else:
        checks.append(
            HealthCheck("api_key", "WARN", "API key not configured (mock mode)")
        )

    base = _api_base()
    host = urlparse(base).hostname or "" if base else ""
    if not host:
        checks.append(HealthCheck("api_base", "FAIL", "API base URL not set"))
    elif _DEV_HOST in host:
        checks.append(
            HealthCheck(
                "api_base",
                "WARN",
                f"host is {host}: this is the developer website, not the API; "
                f"use {_EXPECTED_BASE}",
            )
        )
    elif not base.startswith("https://"):
        checks.append(
            HealthCheck("api_base", "WARN", f"host {host} is not https")
        )
    else:
        checks.append(HealthCheck("api_base", "OK", f"host {host}"))

    model = _voice_model()
    if not model:
        checks.append(HealthCheck("voice_model", "WARN", "voice model not set"))
    elif not _VERSION_SUFFIX_RE.search(model):
        checks.append(
            HealthCheck(
                "voice_model",
                "WARN",
                f"{model} has no version suffix",
            )
        )
    else:
        checks.append(HealthCheck("voice_model", "OK", model))

    mode = "real" if key_ok else "mock"
    if mode == "real":
        checks.append(HealthCheck("mode", "OK", "mode: real (Meta API calls)"))
    else:
        checks.append(
            HealthCheck("mode", "OK", "mode: mock (synthetic demo, no API calls)")
        )

    return checks


def get_system_status(db_path=None) -> list[HealthCheck]:
    """Alias kept for the workflow facade; same checks as check_system."""
    return check_system(db_path)
