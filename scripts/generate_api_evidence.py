"""Generate docs/API-EVIDENCE.md from the local api_calls/ai_runs tables.

For each of Voice batch, Voice realtime, and Spark: recorded attempts
split into HTTP-successful vs usable results, the latest call, observed
failure cases, and mock/incomplete/missing states spelled out. Metadata
only: no transcript text, response bodies, API keys, or session
identifiers are ever written to the report. Never claims verification
the ledger cannot support.
"""

import argparse
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
INVALID_CODES = frozenset({"PARSE_ERROR", "INVALID_RESPONSE"})


def _call_status(call: dict) -> str:
    """Human-readable status for one attempt row (no secrets)."""
    if call.get("http_status") is not None:
        return f"HTTP {call['http_status']}"
    return call.get("error_code") or "unknown"


def _outcome_word(call: dict) -> str:
    """Usable result, failure with code, or incomplete."""
    if call.get("ok"):
        return "usable result"
    if call.get("error_code"):
        return f"failed ({call['error_code']})"
    return "incomplete"


def _failure_line(rows: list[dict]) -> str:
    """Observed failure counts; phrasing kept stable for tests."""
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
    invalid = sum(
        1 for row in rows if (row.get("error_code") or "") in INVALID_CODES
    )
    return (
        f"429 responses: {rate_limited} · 400 responses: {bad_request} · "
        f"timeouts: {timeouts} · invalid responses: {invalid}"
    )


def _latest_line(latest: dict) -> str:
    """One-line latest-call summary with its outcome word."""
    latency = (
        f"{latest['latency_ms']:.0f} ms"
        if latest.get("latency_ms") is not None
        else "n/a"
    )
    return (
        f"- Latest recorded call: {latest.get('created_at')} · "
        f"model {latest.get('model')} · mode {latest.get('mode')} · "
        f"{_call_status(latest)} · {latency} · {_outcome_word(latest)}"
    )


def _http_successful(rows: list[dict]) -> int:
    """Rows with an HTTP status below 400 (transport success only)."""
    return sum(
        1
        for row in rows
        if row.get("http_status") is not None and row["http_status"] < 400
    )


def _usable(rows: list[dict]) -> int:
    """Rows with a validated, usable result."""
    return sum(1 for row in rows if row.get("ok"))


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
    recordings = recordings_repo.list_recordings(db_path=db_path)
    mock_transcripts = sum(
        1 for r in recordings if r.get("transcription_source") == "mock"
    )
    real_runs = ai_runs_repo.count_ai_runs_by_mode("real", db_path=db_path)
    mock_runs = ai_runs_repo.count_ai_runs_by_mode("mock", db_path=db_path)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Meta API evidence (from the local database)",
        "",
        f"Generated {generated} from this machine's local `api_calls`, "
        "`ai_runs`, and `recordings` tables. Rows record attempts made by "
        "this app — they are not independent verification of the Meta "
        "service. Metadata only: no transcript text, response bodies, "
        "API keys, or session identifiers.",
        "",
        "## Voice batch (`/asr/transcribe`)",
        "",
    ]
    if not batch:
        lines.append("No calls recorded yet — no provider evidence.")
    else:
        lines.append(
            f"- Recorded attempts: {len(batch)} "
            f"({_http_successful(batch)} HTTP-successful, "
            f"{_usable(batch)} usable results)"
        )
        lines.append(_latest_line(batch[0]))
        lines.append(f"- Failures observed: {_failure_line(batch)}")
    lines += ["", "## Voice realtime (`/asr/realtime`)", ""]
    if not realtime:
        lines.append("No calls recorded yet — no provider evidence.")
    else:
        handshakes = sum(1 for c in realtime if c.get("http_status") == 101)
        completed = _usable(realtime)
        lines.append(
            f"- Recorded sessions: {len(realtime)} "
            f"({handshakes} handshakes, {completed} completed sessions)"
        )
        lines.append(_latest_line(realtime[0]))
        done = next((c for c in realtime if c.get("ok")), None)
        if done is None:
            lines.append(
                "- No completed session recorded yet — a handshake "
                "(HTTP 101) alone is not a completed transcription."
            )
        else:
            latency = (
                f"{done['latency_ms']:.0f} ms"
                if done.get("latency_ms") is not None
                else "n/a"
            )
            lines.append(
                f"- Latest completed session: {done.get('created_at')} · "
                f"model {done.get('model')} · {latency}"
            )
        lines.append(f"- Failures observed: {_failure_line(realtime)}")
    lines += ["", "## Spark (chat / messages / responses style endpoint)", ""]
    if not spark:
        lines.append("No calls recorded yet — no provider evidence.")
    else:
        lines.append(
            f"- Recorded attempts: {len(spark)} "
            f"({_http_successful(spark)} HTTP-successful, "
            f"{_usable(spark)} usable results)"
        )
        lines.append(_latest_line(spark[0]))
        lines.append(f"- Failures observed: {_failure_line(spark)}")
    lines += [
        "",
        "## Mock executions (not provider evidence)",
        "",
        f"- Mock-mode transcripts persisted: {mock_transcripts}",
        f"- Mock review runs ledgered: {mock_runs} (real runs: {real_runs})",
        "- Mock mode makes no provider calls and proves nothing about "
        "the Meta service.",
        "",
        "## What this report does not prove",
        "",
        "- A configured API key alone proves nothing; only recorded "
        "attempts with usable results count.",
        "- A handshake (HTTP 101), an empty ledger, or a stopped session "
        "is not a successful integration.",
        "- Response content is deliberately omitted: transcript text, "
        "response bodies, API keys, and session identifiers never appear "
        "in this report.",
        "- The repository's tests use isolated databases and fake "
        "servers; their rows never appear in this ledger.",
    ]
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
