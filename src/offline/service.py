import re
from datetime import datetime, timezone
from src.offline.glimmer_client import call_muse_glimmer_local

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def create_offline_redaction(text: str, force_mock: bool = False) -> dict:
    if not text or not text.strip():
        raise ValueError("Text is required for offline redaction")

    glimmer = call_muse_glimmer_local("Redact PII offline", force_mock=force_mock)

    redacted = text
    findings = []
    rules = [
        ("PHONE", r"\b0[17]\d{8}\b", "[REDACTED_PHONE]"),
        ("EMAIL", r"[\w\.-]+@[\w\.-]+\.\w+", "[REDACTED_EMAIL]"),
        ("ID_NUMBER", r"\b\d{8}\b", "[REDACTED_ID]"),
    ]
    for label, pattern, replacement in rules:
        matches = re.findall(pattern, redacted)
        if matches:
            findings.append({"type": label, "count": len(matches), "requires_human": True})
            redacted = re.sub(pattern, replacement, redacted)

    return {
        "original_length": len(text),
        "redacted_text": redacted,
        "findings": findings,
        "glimmer_status": glimmer.get("status"),
        "mode": "offline",
        "status": "AI_DRAFT_OFFLINE_REDACTION",
        "needs_human_review": True,
        "approved": False,
        "approved_by": None,
    }

def human_approve_offline_redaction(draft: dict, approver_name: str, session: dict | None = None) -> dict:
    if not approver_name or not approver_name.strip():
        raise ValueError("Approver name is required - human must be accountable for offline redaction")
    if draft is None:
        raise ValueError("BLOCKED: Create offline redaction draft first")

    draft["approved"] = True
    draft["approved_by"] = approver_name.strip()
    draft["status"] = "HUMAN_APPROVED_OFFLINE_REDACTION"
    draft["needs_human_review"] = False

    if session is not None:
        session["audit_log"].append(
            {"ts": _now(), "actor": approver_name.strip(), "action": "OFFLINE_REDACTION_HUMAN_APPROVED", "details": f"Findings: {draft.get('findings')}"}
        )
    return draft