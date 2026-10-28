from datetime import datetime, timezone
from src.vision.sam_client import call_sam_segment

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def create_redaction_draft(image_name: str, force_mock: bool = False) -> dict:
    sam = call_sam_segment(image_name, force_mock=force_mock)
    segments = sam.get("segments", [])
    masks = [s["label"] for s in segments if s.get("sensitive")]
    return {
        "image_name": image_name,
        "segments": segments,
        "mask_labels": masks,
        "sam_status": sam.get("status"),
        "status": "AI_DRAFT_REDACTION",
        "needs_human_review": True,
        "approved": False,
        "approved_by": None,
    }

def human_approve_redaction(draft: dict, approver_name: str, session: dict | None = None) -> dict:
    if not approver_name or not approver_name.strip():
        raise ValueError("Approver name is required - human must be accountable for redaction")
    if not draft.get("segments"):
        raise ValueError("BLOCKED: No SAM segments to approve")

    draft["approved"] = True
    draft["approved_by"] = approver_name.strip()
    draft["status"] = "HUMAN_APPROVED_REDACTION"
    draft["needs_human_review"] = False

    if session is not None:
        session["audit_log"].append(
            {"ts": _now(), "actor": approver_name.strip(), "action": "REDACTION_HUMAN_APPROVED", "details": f"Masks approved: {draft['mask_labels']}"}
        )
    return draft