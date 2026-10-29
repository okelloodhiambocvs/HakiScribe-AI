"""Generate docs/API-EVIDENCE.md from the local api_calls/ai_runs tables.

For each of Voice batch, Voice realtime, and Spark: endpoint path,
model, mode, status, latency, a sanitised excerpt of the stored
response, observed error-handling cases, and the date. Sanitising
removes key-like strings, shortens session ids, and caps transcript
excerpts at 200 characters. Never writes secrets.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.repositories import (  # noqa: E402
    ai_runs_repo,
    api_calls_repo,
    recordings_repo,
)

VOICE_BATCH_PATH = "/asr/transcribe"
VOICE_REALTIME_PATH = "/asr/realtime"
EXCERPT_CHARS = 200

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_HEX_TOKEN_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.~+/=]+")
_SECRET_ASSIGN_RE = re.compile(
    r"(accessToken|api[_-]?key)\s*[:=]\s*['\"]?\S+", re.IGNORECASE
)


def sanitize(text: str) -> str:
    """Redact key-like strings and shorten session ids in one excerpt."""
    text = _BEARER_RE.sub("Bearer [REDACTED]", text or "")
    text = _SECRET_ASSIGN_RE.sub(r"\1: [REDACTED]", text)
    text = _UUID_RE.sub(lambda match: match.group(0)[:8] + "…", text)
    text = _HEX_TOKEN_RE.sub(lambda match: match.group(0)[:8] + "…", text)
    return text


def excerpt(text: str | None) -> str | None:
    """Sanitise and cap one stored response excerpt (None when empty)."""
    if not (text or "").strip():
        return None
    return sanitize(text.strip())[:EXCERPT_CHARS]


def _batch_excerpt(db_path) -> str | None:
    """Newest non-live stored batch response, sanitised and capped."""
    recordings = recordings_repo.list_recordings(db_path=db_path)
    for recording in reversed(recordings):
        raw = recording.get("transcription_raw_json")
        if not raw or recording.get("capture_source") == "live":
            continue
        try:
            payload = json.loads(raw)
        except ValueError:
            return excerpt(raw)
        if isinstance(payload, dict):
            session = payload.get("sessionId")
            session_bit = f"session {session} · " if session else ""
            text = payload.get("transcript") or ""
            if not text:
                turns = payload.get("turns") or []
                if turns and isinstance(turns[0], dict):
                    text = turns[0].get("transcript") or ""
            return excerpt(session_bit + text)
        return excerpt(raw)
    return None


def _realtime_excerpt(db_path) -> str | None:
    """Newest live stored turns, sanitised and capped."""
    recordings = recordings_repo.list_recordings(db_path=db_path)
    for recording in reversed(recordings):
        raw = recording.get("transcription_raw_json")
        if not raw or recording.get("capture_source") != "live":
            continue
        try:
            turns = json.loads(raw)
        except ValueError:
            return excerpt(raw)
        if isinstance(turns, list) and turns:
            first = turns[0] if isinstance(turns[0], dict) else {}
            speaker = first.get("speaker") or "UNKNOWN"
            return excerpt(f"{speaker}: {first.get('text') or ''}")
        return excerpt(raw)
    return None


def _spark_excerpt(db_path) -> str | None:
    """Newest stored Spark run reply, sanitised and capped."""
    for run in ai_runs_repo.list_recent_ai_runs(limit=50, db_path=db_path):
        if run.get("raw_json"):
            return excerpt(run["raw_json"])
    return None


def _call_status(call: dict) -> str:
    """Human-readable status for one attempt row (no secrets)."""
    if call.get("http_status") is not None:
        return f"HTTP {call['http_status']}"
    return call.get("error_code") or "unknown"


def _error_cases(rows: list[dict]) -> str:
    """Summarise observed error-handling cases for one category."""
    successful = sum(1 for row in rows if row.get("ok"))
    rate_limited = sum(
        1
        for row in rows
        if row.get("http_status") == 429 or row.get("error_code") == "HTTP_429"
    )
    bad_request = sum(
        1
        for row in rows
        if row.get("http_status") == 400 or row.get("error_code") == "HTTP_400"
    )
    timeouts = sum(1 for row in rows if row.get("error_code") == "TIMEOUT")
    return (
        f"{len(rows)} calls observed ({successful} successful) · "
        f"429 responses: {rate_limited} · 400 responses: {bad_request} · "
        f"timeouts: {timeouts}"
    )


def _latest(rows: list[dict]) -> dict | None:
    """Newest row of a newest-first list, or None when empty."""
    return rows[0] if rows else None


def render_evidence_markdown(db_path) -> str:
    """Build the evidence document from the local tables."""
    calls = api_calls_repo.list_recent_api_calls(limit=500, db_path=db_path)
    batch = [c for c in calls if c["endpoint_path"] == VOICE_BATCH_PATH]
    realtime = [c for c in calls if c["endpoint_path"] == VOICE_REALTIME_PATH]
    spark = [
        c
        for c in calls
        if c["endpoint_path"] not in (VOICE_BATCH_PATH, VOICE_REALTIME_PATH)
    ]
    sections = [
        (
            "Voice batch",
            f"`{VOICE_BATCH_PATH}`",
            batch,
            _batch_excerpt(db_path),
        ),
        (
            "Voice realtime",
            f"`{VOICE_REALTIME_PATH}`",
            realtime,
            _realtime_excerpt(db_path),
        ),
        ("Spark", "chat / messages / responses style endpoint", spark,
         _spark_excerpt(db_path)),
    ]
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Meta API evidence (from the local database)",
        "",
        f"Generated {generated} from the local `api_calls` and `ai_runs` "
        "tables. Excerpts are truncated to 200 characters; API keys are "
        "removed and session ids are shortened.",
        "",
    ]
    for label, endpoint, rows, text in sections:
        lines.append(f"## {label} ({endpoint})")
        lines.append("")
        latest = _latest(rows)
        if latest is None:
            lines.append("No calls recorded yet.")
            lines.append("")
            continue
        latency = (
            f"{latest['latency_ms']:.0f} ms"
            if latest.get("latency_ms") is not None
            else "n/a"
        )
        lines.append(
            f"- Latest call: {latest.get('created_at')} · "
            f"model {latest.get('model')} · mode {latest.get('mode')} · "
            f"{_call_status(latest)} · {latency}"
        )
        if text:
            lines.append(f"- Stored response excerpt: `{text}`")
        else:
            lines.append("- Stored response excerpt: none stored yet.")
        lines.append(f"- {_error_cases(rows)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """CLI entry: render the evidence doc; int exit code."""
    parser = argparse.ArgumentParser(
        description="Render Meta API evidence from the local database."
    )
    parser.add_argument("--db", default=None)
    parser.add_argument(
        "--out", default=str(_REPO_ROOT / "docs" / "API-EVIDENCE.md")
    )
    args = parser.parse_args(argv[1:])
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        render_evidence_markdown(args.db), encoding="utf-8"
    )
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
