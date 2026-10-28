from datetime import datetime, timezone
from extras.explainer.wonder_client import call_muse_wonder

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def generate_mwananchi_explainer(session: dict, force_mock: bool = False) -> dict:
    """Muse Wonder draft. BLOCKED until Magistrate has certified."""
    if not session.get("certified"):
        raise ValueError("BLOCKED: Only CERTIFIED transcript can be explained to litigant - human certification required first")
    if not session.get("final_text"):
        raise ValueError("BLOCKED: No final certified text found")

    wonder = call_muse_wonder(
        f"Explain certified Kenyan case {session['case_number']} in plain English and Kiswahili",
        force_mock=force_mock
    )

    deadline = session.get("deadline") or {}
    notice = deadline.get("notice_of_appeal_due", "ask court clerk")
    record_due = deadline.get("record_of_appeal_due", "ask court clerk")

    explainer = {
        "case_number": session["case_number"],
        "explainer_en": f"Your case {session['case_number']} has been certified by the Magistrate. This means the official court record is ready. If you want to appeal, tell the court before {notice}. This is not legal advice - please ask the court clerk or a lawyer.",
        "explainer_sw": f"Kesi yako {session['case_number']} imethibitishwa na Hakimu. Hii inamaanisha rekodi rasmi ya mahakama iko tayari. Ikiwa unataka kukata rufaa, ijulishe mahakama kabla ya {notice}. Habari hii si ushauri wa kisheria - tafadhali uliza karani wa mahakama au wakili.",
        "notice_of_appeal_due": notice,
        "record_of_appeal_due": record_due,
        "wonder_status": wonder.get("status"),
        "status": "AI_DRAFT_EXPLAINER",
        "needs_human_review": True,
        "approved": False,
        "approved_by": None,
    }
    session["explainer"] = explainer
    session["audit_log"].append(
        {"ts": _now(), "actor": "AI (Muse Wonder)", "action": "EXPLAINER_DRAFT_CREATED", "details": "Mwananchi explainer draft only - NOT approved for litigant"}
    )
    return explainer

def human_approve_explainer(session: dict, approver_name: str) -> dict:
    """HUMAN must approve explainer by name before sharing."""
    explainer = session.get("explainer")
    if not explainer:
        raise ValueError("BLOCKED: Generate explainer first")
    if not approver_name or not approver_name.strip():
        raise ValueError("Approver name is required - human must be accountable")

    explainer["approved"] = True
    explainer["approved_by"] = approver_name.strip()
    explainer["status"] = "HUMAN_APPROVED_EXPLAINER"
    explainer["needs_human_review"] = False
    session["audit_log"].append(
        {"ts": _now(), "actor": approver_name.strip(), "action": "EXPLAINER_HUMAN_APPROVED", "details": "Explainer approved by human for litigant"}
    )
    return session