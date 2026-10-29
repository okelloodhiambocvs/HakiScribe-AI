"""Evaluation metrics: WER/CER, review impact, reference accuracy and more.

Pure Python (standard library only): no network, no new dependencies.
Reads recording data through repositories; never writes.

NORMALISATION (applied before every WER/CER comparison; also noted in
docs/architecture/ARCHITECTURE-V2.md section 4):
- Unicode NFC composition, then lower-casing.
- Punctuation and symbols removed (Unicode categories P* and S*).
- Non-whitespace control characters removed; remaining whitespace
  collapsed to one space and trimmed.
- Diacritics are KEPT (e with acute never becomes plain e).
- No translation, no spell-correction, no stemming: Kiswahili words stay
  Kiswahili and misspellings stay misspellings.

Every recording-level metric returns an envelope:
{"values": {name: float | None}, "sample_size": int,
 "how_computed": str, "reason": str | None}.
Uncomputable metrics return empty values with a reason — never a
placeholder number.
"""

import json
import re
import unicodedata
from datetime import datetime
from itertools import permutations
from pathlib import Path

from backend.repositories import (
    corrections_repo,
    flags_repo,
    review_events_repo,
    segments_repo,
)
from backend.services.ingestion_service import get_recording_or_raise

DEMO_REFERENCE_PATH = Path("demo-data/synthetic/case-cr-123-2026.reference.json")
IDLE_GAP_SECONDS = 120

_HOW_AI_VS_REVIEWED = (
    "WER/CER between the joined original AI texts and the joined reviewed "
    "texts (segments in idx order); changed % counts segments whose current "
    "text differs from the original."
)
_HOW_REFERENCE = (
    "WER/CER between the joined reference script texts and the joined "
    "original AI transcript texts."
)
_HOW_SPEAKER = (
    "API speaker labels are mapped one-to-one to reference voices by best "
    "total time overlap; attribution % is the share of reference speech "
    "time covered by the matching speaker; boundary error is the mean over "
    "reference turns of the distance to the nearest transcript segment start."
)
_HOW_TRACEABILITY = (
    "Share of correction rows having a non-empty reviewer, timestamp and "
    "reason."
)
_HOW_REVIEW_TIME = (
    "Sum of gaps between consecutive review events, excluding gaps over "
    "120 s; per-flag divides by the number of RESOLVED flags."
)


def normalize_text(text: str | None) -> str:
    """Normalize for comparison: NFC, lower, de-punctuated, collapsed."""
    lowered = unicodedata.normalize("NFC", text or "").lower()
    kept = []
    for char in lowered:
        category = unicodedata.category(char)
        if category.startswith(("P", "S")):
            continue
        if category.startswith("C") and not char.isspace():
            continue
        kept.append(char)
    return re.sub(r"\s+", " ", "".join(kept)).strip()


def _edit_distance(ref_seq, hyp_seq) -> int:
    """Levenshtein distance over two token sequences."""
    previous = list(range(len(hyp_seq) + 1))
    for i, ref_token in enumerate(ref_seq, 1):
        current = [i]
        for j, hyp_token in enumerate(hyp_seq, 1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (ref_token != hyp_token),
                )
            )
        previous = current
    return previous[-1]


def wer(reference: str | None, hypothesis: str | None) -> float:
    """Word error rate: word edits divided by reference word count.

    Empty reference with empty hypothesis scores 0.0; empty reference
    with any hypothesis scores 1.0. Insertions can push WER above 1.0.
    """
    ref_tokens = normalize_text(reference).split()
    hyp_tokens = normalize_text(hypothesis).split()
    if not ref_tokens:
        return 0.0 if not hyp_tokens else 1.0
    return _edit_distance(ref_tokens, hyp_tokens) / len(ref_tokens)


def cer(reference: str | None, hypothesis: str | None) -> float:
    """Character error rate (spaces included), same empty rules as WER."""
    ref_chars = list(normalize_text(reference))
    hyp_chars = list(normalize_text(hypothesis))
    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0
    return _edit_distance(ref_chars, hyp_chars) / len(ref_chars)


def _envelope(
    values: dict, sample_size: int, how_computed: str, reason: str | None = None
) -> dict:
    """Build the standard metric envelope."""
    return {
        "values": values,
        "sample_size": sample_size,
        "how_computed": how_computed,
        "reason": reason,
    }


def _load_reference(reference) -> dict:
    """Accept a path, a {"turns": [...]} dict, or a bare turns list."""
    if isinstance(reference, (str, Path)):
        path = Path(reference)
        if not path.is_file():
            raise ValueError(f"reference file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    elif isinstance(reference, dict):
        data = reference
    elif isinstance(reference, list):
        data = {"turns": reference}
    else:
        raise ValueError(f"unsupported reference: {type(reference).__name__}")
    turns = data.get("turns")
    if not isinstance(turns, list):
        raise ValueError("reference has no turns list")
    return {"turns": turns, "audio_sha256": data.get("audio_sha256")}


def _resolve_reference(recording_id, reference, db_path):
    """Return (reference dict | None, reason | None)."""
    if reference is not None:
        return _load_reference(reference), None
    recording = get_recording_or_raise(recording_id, db_path=db_path)
    if not DEMO_REFERENCE_PATH.is_file():
        return None, "no reference script for this recording"
    try:
        resolved = _load_reference(DEMO_REFERENCE_PATH)
    except ValueError as exc:
        return None, f"reference file unreadable: {exc}"
    expected = (recording.get("sha256") or "").lower()
    if resolved.get("audio_sha256") and resolved["audio_sha256"] != expected:
        return None, "no reference script for this recording"
    return resolved, None


def compare_ai_vs_reviewed(
    recording_id: int, db_path: str | Path | None = None
) -> dict:
    """Measure how much the human changed the AI transcript."""
    segments = segments_repo.list_segments(recording_id, db_path=db_path)
    if not segments:
        return _envelope({}, 0, _HOW_AI_VS_REVIEWED, "no transcript")
    original = "\n".join(segment["text_original"] or "" for segment in segments)
    current = "\n".join(segment["text_current"] or "" for segment in segments)
    changed = sum(
        1
        for segment in segments
        if (segment["text_current"] or "") != (segment["text_original"] or "")
    )
    return _envelope(
        {
            "wer": wer(original, current),
            "cer": cer(original, current),
            "segments_changed_pct": round(100 * changed / len(segments), 2),
        },
        len(segments),
        _HOW_AI_VS_REVIEWED,
    )


def compare_to_reference(
    recording_id: int,
    reference=None,
    db_path: str | Path | None = None,
) -> dict:
    """Measure AI transcript accuracy against the reference script."""
    segments = segments_repo.list_segments(recording_id, db_path=db_path)
    if not segments:
        return _envelope({}, 0, _HOW_REFERENCE, "no transcript")
    resolved, reason = _resolve_reference(recording_id, reference, db_path)
    if resolved is None:
        return _envelope({}, 0, _HOW_REFERENCE, reason)
    turns = resolved["turns"]
    if not turns:
        return _envelope({}, 0, _HOW_REFERENCE, "reference has no turns")
    ref_text = "\n".join(str(turn.get("text") or "") for turn in turns)
    hyp_text = "\n".join(
        segment["text_original"] or "" for segment in segments
    )
    return _envelope(
        {"wer": wer(ref_text, hyp_text), "cer": cer(ref_text, hyp_text)},
        len(turns),
        _HOW_REFERENCE,
    )


def _overlap_ms(start_a, end_a, start_b, end_b) -> int:
    """Overlapping milliseconds of two intervals."""
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def _best_label_voice_mapping(overlap, labels, voices) -> dict:
    """Best one-to-one label->voice mapping by total overlap (deterministic)."""
    size = max(len(labels), len(voices))
    if size == 0:
        return {}
    padded_labels = list(labels) + [None] * (size - len(labels))
    padded_voices = list(voices) + [None] * (size - len(voices))
    best, best_total = {}, -1
    for perm in permutations(range(size)):
        total = 0
        for label, slot in zip(padded_labels, perm):
            voice = padded_voices[slot]
            if label is not None and voice is not None:
                total += overlap.get((label, voice), 0)
        if total > best_total:
            best_total = total
            best = {
                label: padded_voices[slot]
                for label, slot in zip(padded_labels, perm)
                if label is not None and padded_voices[slot] is not None
            }
    return best


def _to_ms(seconds) -> int:
    """Convert float seconds to integer milliseconds."""
    return int(round(float(seconds or 0) * 1000))


def speaker_attribution_accuracy(
    recording_id: int,
    reference=None,
    db_path: str | Path | None = None,
) -> dict:
    """Attribute transcript speech to reference voices via time overlap."""
    segments = segments_repo.list_segments(recording_id, db_path=db_path)
    if not segments:
        return _envelope({}, 0, _HOW_SPEAKER, "no transcript")
    resolved, reason = _resolve_reference(recording_id, reference, db_path)
    if resolved is None:
        return _envelope({}, 0, _HOW_SPEAKER, reason)
    turns = [turn for turn in resolved["turns"] if isinstance(turn, dict)]
    if not turns:
        return _envelope({}, 0, _HOW_SPEAKER, "reference has no turns")
    ref_spans = [
        (
            int(turn.get("start_ms") or 0),
            int(turn.get("end_ms") or 0),
            turn.get("voice"),
        )
        for turn in turns
    ]
    total_ref_ms = sum(max(0, end - start) for start, end, _ in ref_spans)
    if total_ref_ms <= 0:
        return _envelope({}, len(turns), _HOW_SPEAKER, "reference has no speech time")
    voices = sorted({voice for _, _, voice in ref_spans if voice})
    if not voices:
        return _envelope({}, len(turns), _HOW_SPEAKER, "reference turns lack voice names")
    labeled = [
        (_to_ms(segment["start_sec"]), _to_ms(segment["end_sec"]),
         segment["speaker_label"])
        for segment in segments
        if segment.get("speaker_label")
        and segment.get("start_sec") is not None
        and segment.get("end_sec") is not None
    ]
    labels = sorted({label for _, _, label in labeled})
    overlap: dict[tuple, int] = {}
    for seg_start, seg_end, label in labeled:
        for ref_start, ref_end, voice in ref_spans:
            if voice is None:
                continue
            overlap[(label, voice)] = overlap.get((label, voice), 0) + _overlap_ms(
                seg_start, seg_end, ref_start, ref_end
            )
    mapping = _best_label_voice_mapping(overlap, labels, voices)
    attributed_ms = 0
    for ref_start, ref_end, voice in ref_spans:
        for seg_start, seg_end, label in labeled:
            if mapping.get(label) == voice:
                attributed_ms += _overlap_ms(seg_start, seg_end, ref_start, ref_end)
    starts = sorted(
        _to_ms(segment["start_sec"])
        for segment in segments
        if segment.get("start_sec") is not None
    )
    boundary_errors = [
        min(abs(ref_start - seg_start) for seg_start in starts)
        for ref_start, _, _ in ref_spans
    ]
    mean_error = sum(boundary_errors) / len(boundary_errors)
    return _envelope(
        {
            "attribution_pct": round(100 * attributed_ms / total_ref_ms, 2),
            "boundary_mae_ms": round(mean_error, 1),
        },
        len(turns),
        _HOW_SPEAKER,
    )


def traceability_completeness(
    recording_id: int, db_path: str | Path | None = None
) -> dict:
    """Share of corrections carrying reviewer, timestamp and reason."""
    rows = corrections_repo.list_corrections_by_recording(
        recording_id, db_path=db_path
    )
    if not rows:
        return _envelope({}, 0, _HOW_TRACEABILITY, "no corrections recorded")
    complete = sum(
        1
        for row in rows
        if (row.get("reviewer_name") or "").strip()
        and (row.get("created_at") or "")
        and (row.get("reason") or "").strip()
    )
    return _envelope(
        {"completeness_pct": round(100 * complete / len(rows), 2)},
        len(rows),
        _HOW_TRACEABILITY,
    )


def _parse_event_time(value):
    """Parse a review event timestamp; None when unparseable."""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def review_time(recording_id: int, db_path: str | Path | None = None) -> dict:
    """Active review seconds, excluding idle gaps over 120 seconds."""
    events = review_events_repo.list_events_by_recording(
        recording_id, db_path=db_path
    )
    if not events:
        return _envelope({}, 0, _HOW_REVIEW_TIME, "no review events recorded")
    stamps = sorted(
        stamp
        for stamp in (_parse_event_time(event.get("at")) for event in events)
        if stamp is not None
    )
    total = 0.0
    for previous, current in zip(stamps, stamps[1:]):
        gap = (current - previous).total_seconds()
        if 0 <= gap <= IDLE_GAP_SECONDS:
            total += gap
    flags = flags_repo.list_flags_by_recording(recording_id, db_path=db_path)
    resolved = sum(1 for flag in flags if flag["status"] == "RESOLVED")
    per_flag = round(total / resolved, 1) if resolved else None
    return _envelope(
        {"total_seconds": round(total, 1), "seconds_per_resolved_flag": per_flag},
        len(events),
        _HOW_REVIEW_TIME,
    )
