import hashlib
from datetime import datetime, timezone

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def create_review_session(agent_output: dict) -> dict:
    """Create AI DRAFT session. certified is ALWAYS False here."""
    structured = agent_output.get("structured", {})
    guardian = agent_output.get("guardian", {})

    segments = []
    for s in structured.get("structured_segments", []):
        segments.append({
            **s,
            "clerk_text": s.get("text", ""),
            "review_status": "PENDING",
            "reviewed_by": None,
        })

    return {
        "case_number": structured.get("case_number", "UNKNOWN - HUMAN TO CONFIRM"),
        "status": "AI_DRAFT",
        "certified": False,
        "segments": segments,
        "flags": guardian.get("flags", []),
        "deadline": agent_output.get("deadline"),
        "agent_trace": agent_output.get("agent_trace", []),
        "audit_log": [
            {"ts": _now(), "actor": "AI (Muse)", "action": "AI_DRAFT_CREATED", "details": "AI draft v1 only - NOT certified"}
        ],
        "clerk": None,
        "magistrate": None,
        "final_hash": None,
        "final_text": None,
    }

def _flagged_indexes(session: dict) -> set:
    return {f["segment_index"] for f in session.get("flags", [])}

def clerk_review_segment(session: dict, index: int, clerk_name: str, edited_text: str | None = None, confirmed_speaker: str | None = None) -> dict:
    """HUMAN 1: Clerk reviews ONE segment. No bulk approve."""
    if not clerk_name or not clerk_name.strip():
        raise ValueError("Clerk name is required - human must be accountable")

    seg = session["segments"][index]
    action = "CLERK_EDIT" if edited_text is not None else "CLERK_CONFIRM"

    if edited_text is not None:
        seg["clerk_text"] = edited_text
    if confirmed_speaker:
        seg["speaker"] = confirmed_speaker.strip().upper()
        seg["speaker_uncertain"] = False

    seg["review_status"] = "REVIEWED"
    seg["reviewed_by"] = clerk_name.strip()
    session["clerk"] = clerk_name.strip()
    session["status"] = "CLERK_REVIEW"
    session["audit_log"].append(
        {"ts": _now(), "actor": clerk_name.strip(), "action": action, "details": f"Segment {index} reviewed"}
    )
    return session

def can_clerk_complete(session: dict) -> tuple[bool, list[int]]:
    flagged = _flagged_indexes(session)
    pending = []
    for i, seg in enumerate(session["segments"]):
        needs = seg.get("needs_verify") or i in flagged or seg.get("speaker_uncertain")
        if needs and seg["review_status"] != "REVIEWED":
            pending.append(i)
    return (len(pending) == 0, pending)

def clerk_complete_review(session: dict, clerk_name: str) -> dict:
    ok, pending = can_clerk_complete(session)
    if not ok:
        raise ValueError(f"BLOCKED: Human review incomplete. Segments pending: {pending}")
    session["status"] = "CLERK_REVIEWED"
    session["clerk"] = clerk_name.strip()
    session["audit_log"].append(
        {"ts": _now(), "actor": clerk_name.strip(), "action": "CLERK_REVIEW_COMPLETE", "details": "All flagged segments reviewed by human"}
    )
    return session

def build_final_text(session: dict) -> str:
    lines = [
        "REPUBLIC OF KENYA - THE JUDICIARY (SYNTHETIC DEMO)",
        f"Case: {session['case_number']}",
        "",
    ]
    for seg in session["segments"]:
        lines.append(f"{seg['speaker']}: {seg['clerk_text']}")
    return "\n".join(lines)

def magistrate_certify(session: dict, magistrate_name: str) -> dict:
    """HUMAN 2: Only Magistrate can certify, only after Clerk, and must be different person."""
    if session["status"] != "CLERK_REVIEWED":
        raise ValueError("BLOCKED: Clerk must complete review before Magistrate can certify")
    if not magistrate_name or not magistrate_name.strip():
        raise ValueError("Magistrate name is required")
    if magistrate_name.strip().lower() == (session.get("clerk") or "").lower():
        raise ValueError("BLOCKED: Separation of duties - Magistrate must be different from Clerk")

    final_text = build_final_text(session)
    raw = f"{final_text}|{session['clerk']}|{magistrate_name.strip()}"
    session["final_text"] = final_text
    session["final_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    session["magistrate"] = magistrate_name.strip()
    session["status"] = "CERTIFIED"
    session["certified"] = True
    session["audit_log"].append(
        {"ts": _now(), "actor": magistrate_name.strip(), "action": "MAGISTRATE_CERTIFIED", "details": f"Hash: {session['final_hash']}"}
    )
    return session