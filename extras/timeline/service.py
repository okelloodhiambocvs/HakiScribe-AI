from datetime import datetime, timezone
from src.timeline.image_client import call_muse_image

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def generate_case_timeline(session: dict, force_mock: bool = False) -> dict:
    if not session.get("certified"):
        raise ValueError("BLOCKED: Only CERTIFIED transcript can have a public timeline - Magistrate must certify first")
    if not session.get("final_text"):
        raise ValueError("BLOCKED: No final certified text found")

    image = call_muse_image(
        f"Visual timeline for certified Kenyan case {session['case_number']}",
        force_mock=force_mock
    )
    deadline = session.get("deadline") or {}

    timeline = {
        "case_number": session["case_number"],
        "title": f"Case Journey: {session['case_number']}",
        "steps": [
            {"label": "Hearing Transcribed - AI Draft v1", "status": "DONE"},
            {"label": "Clerk Verified Each Flagged Segment", "status": "DONE"},
            {"label": "Magistrate Certified Official Record", "status": "DONE"},
            {"label": f"Notice of Appeal Due: {deadline.get('notice_of_appeal_due', 'HUMAN TO CONFIRM')}", "status": "UPCOMING - HUMAN CONFIRM"},
            {"label": f"Record of Appeal Due: {deadline.get('record_of_appeal_due', 'HUMAN TO CONFIRM')}", "status": "UPCOMING - HUMAN CONFIRM"},
        ],
        "image_prompt": f"Infographic timeline for {session['case_number']}",
        "image_status": image.get("status"),
        "status": "AI_DRAFT_TIMELINE",
        "needs_human_review": True,
        "approved": False,
        "approved_by": None,
    }
    session["timeline"] = timeline
    session["audit_log"].append(
        {"ts": _now(), "actor": "AI (Muse Image)", "action": "TIMELINE_DRAFT_CREATED", "details": "Visual timeline draft only - NOT approved"}
    )
    return timeline

def human_approve_timeline(session: dict, approver_name: str) -> dict:
    timeline = session.get("timeline")
    if not timeline:
        raise ValueError("BLOCKED: Generate timeline first")
    if not approver_name or not approver_name.strip():
        raise ValueError("Approver name is required - human must be accountable")

    timeline["approved"] = True
    timeline["approved_by"] = approver_name.strip()
    timeline["status"] = "HUMAN_APPROVED_TIMELINE"
    timeline["needs_human_review"] = False
    session["audit_log"].append(
        {"ts": _now(), "actor": approver_name.strip(), "action": "TIMELINE_HUMAN_APPROVED", "details": "Visual timeline approved by human"}
    )
    return session