"""AI review orchestration: prompt, validate, persist. Never edits transcripts.

Flags are suggestions for a human reviewer, never proof of error. Every
flag's evidence must quote the transcript verbatim or the flag is
dropped; hallucinated flags can never reach the database.
"""

import json
import re
from pathlib import Path

from backend.core import config
from backend.integrations.meta import spark_client
from backend.integrations.meta.spark_client import SparkError  # noqa: F401 (re-export)
from backend.repositories import ai_runs_repo, api_calls_repo, flags_repo
from backend.repositories import corrections_repo, segments_repo
from backend.repositories import review_events_repo, speaker_roles_repo
from backend.services import review_prompt
from backend.services.ingestion_service import get_recording_or_raise
from backend.services.review_prompt import PROMPT_VERSION

__all__ = [
    "run_review",
    "get_flags",
    "get_review_summary",
    "parse_and_validate",
    "edit_segment",
    "decide_flag",
    "assign_speaker_role",
    "get_segment_history",
    "get_unresolved",
    "get_speaker_roles",
    "record_review_event",
    "SparkError",
]

FLAG_TYPES = frozenset(review_prompt.FLAG_TYPES)
SEVERITIES = frozenset({"LOW", "MEDIUM", "HIGH"})
MAX_FLAGS_PER_SEGMENT = 5
MOCK_MODEL = "muse-spark-mock"
HINT_EVIDENCE_CHARS = 80

_REPEAT_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d[\d,]*\b")
_SECTION_RE = re.compile(r"\bsection\s+\d+\b", re.IGNORECASE)


def _strip_fences(text: str) -> str:
    """Remove one surrounding markdown code fence, if present."""
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _optional_text(value: object) -> str | None:
    """Coerce an optional string field; None stays None."""
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _validate_flag(item: object, by_idx: dict[int, dict]) -> dict | None:
    """Validate one model flag; None means drop it."""
    if not isinstance(item, dict):
        return None
    idx = item.get("segment_idx")
    if isinstance(idx, bool) or not isinstance(idx, int):
        return None
    segment = by_idx.get(idx)
    if segment is None:
        return None
    flag_type = str(item.get("type") or "").strip().upper()
    if flag_type not in FLAG_TYPES:
        return None
    evidence = item.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        return None
    if evidence.lower() not in (segment["text_original"] or "").lower():
        return None
    severity = str(item.get("severity") or "").strip().upper()
    if severity not in SEVERITIES:
        severity = "MEDIUM"
    related = item.get("related_segment_idx")
    related_id = None
    if isinstance(related, int) and not isinstance(related, bool):
        related_segment = by_idx.get(related)
        if related_segment is not None:
            related_id = related_segment["id"]
    return {
        "segment_id": segment["id"],
        "segment_idx": idx,
        "flag_type": flag_type,
        "severity": severity,
        "message": str(item.get("message") or "AI suggests a human check."),
        "evidence": evidence,
        "suggestion": _optional_text(item.get("suggestion")),
        "related_segment_id": related_id,
        "prompt_version": PROMPT_VERSION,
        "evidence_verified": 1,
    }


def _match_speaker(candidate: object, by_idx: dict[int, dict]) -> dict | None:
    """Find the first segment for a hinted speaker ("Speaker A" or "A")."""
    if not isinstance(candidate, str):
        return None
    name = candidate.strip()
    for idx in sorted(by_idx):
        if name == by_idx[idx]["speaker"]:
            return by_idx[idx]
    for idx in sorted(by_idx):
        segment = by_idx[idx]
        if f"Speaker {name}" == segment["speaker"]:
            return segment
        if name and name == (segment.get("speaker_label") or ""):
            return segment
    return None


def _validate_hint(hint: object, by_idx: dict[int, dict]) -> dict | None:
    """Validate one speaker role hint into a SPEAKER_ATTRIBUTION flag."""
    if not isinstance(hint, dict):
        return None
    role = (
        str(hint.get("likely_role") or "")
        .strip()
        .upper()
        .replace(" ", "_")
        .replace("-", "_")
    )
    if role not in review_prompt.TAXONOMY_ROLES:
        return None
    segment = _match_speaker(hint.get("speaker"), by_idx)
    if segment is None:
        return None
    return {
        "segment_id": segment["id"],
        "segment_idx": segment["idx"],
        "flag_type": "SPEAKER_ATTRIBUTION",
        "severity": "LOW",
        "message": str(
            hint.get("reason") or "AI suggests a speaker role; verify from audio."
        ),
        "evidence": (segment["text_original"] or "")[:HINT_EVIDENCE_CHARS],
        "suggestion": role,
        "related_segment_id": None,
        "prompt_version": PROMPT_VERSION,
        "evidence_verified": 1,
    }


def parse_and_validate(
    reply_text: str, segments_by_idx: dict[int, dict]
) -> tuple[list[dict], int]:
    """Parse one batch reply; return (valid flag dicts, dropped count).

    Raises SparkError when the reply is not JSON. Drops flags with an
    unknown segment, an unknown type, or evidence that does not quote
    the segment verbatim, plus hints outside the speaker taxonomy.
    Caps flags per segment at 5.
    """
    try:
        payload = json.loads(_strip_fences(reply_text))
    except (ValueError, TypeError):
        raise SparkError("Spark reply is not valid JSON") from None
    if not isinstance(payload, dict):
        raise SparkError("Spark reply JSON is not an object")
    valid: list[dict] = []
    dropped = 0
    per_segment: dict[int, int] = {}

    def _accept(candidate: dict | None) -> None:
        nonlocal dropped
        if candidate is None:
            dropped += 1
            return
        count = per_segment.get(candidate["segment_id"], 0)
        if count >= MAX_FLAGS_PER_SEGMENT:
            dropped += 1
            return
        per_segment[candidate["segment_id"]] = count + 1
        valid.append(candidate)

    raw_flags = payload.get("flags") or []
    if isinstance(raw_flags, list):
        for item in raw_flags:
            _accept(_validate_flag(item, segments_by_idx))
    raw_hints = payload.get("speaker_role_hints") or []
    if isinstance(raw_hints, list):
        for hint in raw_hints:
            _accept(_validate_hint(hint, segments_by_idx))
    return valid, dropped


def _mock_flag(
    segment: dict, flag_type: str, severity: str, evidence: str, message: str
) -> dict:
    """Build one deterministic mock flag quoting an exact match."""
    return {
        "segment_id": segment["id"],
        "segment_idx": segment["idx"],
        "flag_type": flag_type,
        "severity": severity,
        "message": message,
        "evidence": evidence,
        "suggestion": None,
        "related_segment_id": None,
        "prompt_version": PROMPT_VERSION,
        "evidence_verified": 1,
    }


def _mock_review(segments: list[dict]) -> tuple[list[dict], int]:
    """Deterministic rule flags: repeats, numbers/dates, section refs."""
    valid: list[dict] = []
    dropped = 0
    for segment in segments:
        text = segment["text_original"] or ""
        candidates = [
            _mock_flag(
                segment,
                "REPETITION_OR_DISFLUENCY",
                "LOW",
                match.group(0),
                f"Repeated word {match.group(1)!r}; confirm against the audio.",
            )
            for match in _REPEAT_RE.finditer(text)
        ]
        candidates.extend(
            _mock_flag(
                segment,
                "NUMBER_OR_DATE",
                "MEDIUM",
                match.group(0),
                "Confirm the number is transcribed correctly.",
            )
            for match in _NUMBER_RE.finditer(text)
        )
        candidates.extend(
            _mock_flag(
                segment,
                "LEGAL_TERM",
                "MEDIUM",
                match.group(0),
                "Confirm the legal reference is transcribed correctly.",
            )
            for match in _SECTION_RE.finditer(text)
        )
        valid.extend(candidates[:MAX_FLAGS_PER_SEGMENT])
        dropped += max(0, len(candidates) - MAX_FLAGS_PER_SEGMENT)
    return valid, dropped


def _spark_attempt_recorder(recording_id: int, db_path, model: str, style: str):
    """Build the Spark client's per-attempt callback (persists via repo)."""
    def record(info: dict) -> None:
        api_calls_repo.create_api_call(
            provider="meta",
            model=model,
            endpoint_path=spark_client.STYLE_PATHS[style],
            mode=style,
            recording_id=recording_id,
            http_status=info.get("http_status"),
            ok=bool(info.get("ok")),
            latency_ms=info.get("latency_ms"),
            audio_bytes=info.get("audio_bytes"),
            audio_ms=info.get("audio_ms"),
            request_id=info.get("request_id"),
            error_code=info.get("error_code"),
            db_path=db_path,
        )

    return record


def run_review(
    recording_id: int,
    force_mock: bool = False,
    db_path: str | Path | None = None,
) -> dict:
    """Run AI review over a transcript; validate, persist, and ledger it.

    Raises ValueError when the recording is missing or has no transcript.
    Never modifies transcript rows — flags and runs are separate tables.
    """
    get_recording_or_raise(recording_id, db_path=db_path)
    segments = segments_repo.list_segments(recording_id, db_path=db_path)
    if not segments:
        raise ValueError("Transcribe the recording before running AI review.")
    by_idx = {segment["idx"]: segment for segment in segments}
    if force_mock or not config.is_configured():
        model, mode, raw_json = MOCK_MODEL, "mock", None
        valid, dropped = _mock_review(segments)
    else:
        model, mode = config.META_REASONING_MODEL, "real"
        style = spark_client.get_api_style()
        recorder = _spark_attempt_recorder(recording_id, db_path, model, style)
        valid, dropped, raws = [], 0, []
        for user_text in review_prompt.build_review_batches(segments):
            reply = spark_client.complete(
                review_prompt.SYSTEM_PROMPT,
                user_text,
                model=model,
                style=style,
                on_attempt=recorder,
            )
            raws.append(reply["raw"])
            batch_valid, batch_dropped = parse_and_validate(reply["text"], by_idx)
            valid.extend(batch_valid)
            dropped += batch_dropped
        raw_json = json.dumps(raws, ensure_ascii=False)
    _ids, skipped = flags_repo.replace_review_flags(
        recording_id, valid, created_by_model=model, db_path=db_path
    )
    created = len(valid) - skipped
    dropped += skipped
    ai_runs_repo.create_ai_run(
        recording_id,
        model,
        PROMPT_VERSION,
        mode,
        "complete",
        created,
        dropped,
        raw_json,
        db_path=db_path,
    )
    return {
        "recording_id": recording_id,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "mode": mode,
        "flags_created": created,
        "flags_dropped": dropped,
        "flags": flags_repo.list_flags_by_recording(recording_id, db_path=db_path),
    }


def get_flags(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """Return a recording's flags with segment_idx, ordered by idx."""
    return flags_repo.list_flags_by_recording(recording_id, db_path=db_path)


def get_review_summary(
    recording_id: int, db_path: str | Path | None = None
) -> dict | None:
    """Return the latest review run row; None when never reviewed."""
    return ai_runs_repo.get_latest_ai_run(recording_id, db_path=db_path)


def edit_segment(
    segment_id: int,
    new_text: str | None,
    reviewer: str,
    reason: str | None,
    expected_current: str | None,
    db_path: str | Path | None = None,
) -> dict:
    """Apply a reviewer text edit with stale-write protection.

    expected_current is the text the reviewer saw; a mismatch raises
    EditConflictError. Exactly one correction row is written, and only
    text_current changes — text_original is never touched.
    """
    result = corrections_repo.apply_text_edit(
        segment_id,
        expected_current,
        new_text,
        reviewer,
        "EDIT_TEXT",
        reason,
        field="text",
        flag_id=None,
        db_path=db_path,
    )
    return {"segment_id": segment_id, **result}


def decide_flag(
    flag_id: int,
    decision: str,
    reviewer: str,
    reason: str | None,
    new_text: str | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """Apply one flag decision atomically and resolve the flag.

    ACCEPT_SUGGESTION runs through the same edit path for text
    suggestions, or the role path for SPEAKER_ATTRIBUTION hints.
    """
    result = corrections_repo.apply_decision(
        flag_id, decision, reviewer, reason, new_text=new_text, db_path=db_path
    )
    return {"flag_id": flag_id, "decision": decision, **result}


def assign_speaker_role(
    recording_id: int,
    speaker_label: str,
    role: str,
    reviewer: str,
    reason: str | None,
    db_path: str | Path | None = None,
) -> dict:
    """Assign a locked-taxonomy role to a speaker label, traced by correction.

    The role applies to every segment of the label. ValueError when the
    role is outside the locked taxonomy or the label has no segments.
    """
    normalized = (
        (role or "").strip().upper().replace(" ", "_").replace("-", "_")
    )
    if normalized not in review_prompt.TAXONOMY_ROLES:
        raise ValueError(f"role {role!r} is not in the locked speaker taxonomy")
    get_recording_or_raise(recording_id, db_path=db_path)
    result = corrections_repo.apply_role_assignment(
        recording_id,
        speaker_label,
        normalized,
        reviewer,
        reason,
        decision="ASSIGN_SPEAKER_ROLE",
        db_path=db_path,
    )
    return {
        "recording_id": recording_id,
        "speaker_label": speaker_label,
        "role": normalized,
        **result,
    }


def get_segment_history(
    segment_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """Return a segment's corrections ordered by id (who/when/before/after)."""
    return corrections_repo.list_corrections_by_segment(segment_id, db_path=db_path)


def get_unresolved(
    recording_id: int, db_path: str | Path | None = None
) -> list[dict]:
    """Return OPEN and RETAINED flags with segment time and message."""
    return flags_repo.list_unresolved_by_recording(recording_id, db_path=db_path)


def get_speaker_roles(
    recording_id: int, db_path: str | Path | None = None
) -> dict[str, str]:
    """Map speaker labels to assigned court roles for a recording."""
    return speaker_roles_repo.list_roles_by_recording(recording_id, db_path=db_path)


def record_review_event(
    recording_id: int,
    reviewer: str,
    event: str,
    db_path: str | Path | None = None,
) -> int:
    """Log one review-time event (review_opened, edit, decision)."""
    get_recording_or_raise(recording_id, db_path=db_path)
    return review_events_repo.record_event(recording_id, reviewer, event, db_path)
