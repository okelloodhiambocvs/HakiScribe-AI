def _make_session():
    from src.transcription.client import transcribe_audio
    from src.agents.agents import run_all_agents
    from src.verification.service import create_review_session
    segs = transcribe_audio("x.mp3", force_mock=True)["segments"]
    out = run_all_agents(segs, "2026-10-27", force_mock=True)
    return create_review_session(out)

def test_session_starts_uncertified():
    s = _make_session()
    assert s["status"] == "AI_DRAFT"
    assert s["certified"] is False
    assert s["audit_log"][0]["action"] == "AI_DRAFT_CREATED"

def test_magistrate_blocked_before_clerk():
    import pytest
    from src.verification.service import magistrate_certify
    s = _make_session()
    with pytest.raises(ValueError):
        magistrate_certify(s, "Magistrate Achieng")

def test_clerk_cannot_complete_until_flagged_reviewed():
    import pytest
    from src.verification.service import clerk_complete_review, can_clerk_complete
    s = _make_session()
    ok, pending = can_clerk_complete(s)
    assert ok is False
    assert len(pending) >= 1
    with pytest.raises(ValueError):
        clerk_complete_review(s, "Clerk Otieno")

def test_full_human_flow_certifies_with_hash():
    from src.verification.service import clerk_review_segment, clerk_complete_review, magistrate_certify
    s = _make_session()
    # Human must review every segment individually - no bulk approve
    for i in range(len(s["segments"])):
        clerk_review_segment(s, i, "Clerk Otieno", confirmed_speaker=s["segments"][i]["speaker"])
    clerk_complete_review(s, "Clerk Otieno")
    magistrate_certify(s, "Magistrate Achieng")
    assert s["certified"] is True
    assert s["status"] == "CERTIFIED"
    assert s["final_hash"] and len(s["final_hash"]) == 64
    actions = [a["action"] for a in s["audit_log"]]
    assert "CLERK_REVIEW_COMPLETE" in actions
    assert "MAGISTRATE_CERTIFIED" in actions