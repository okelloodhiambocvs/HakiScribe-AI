def _certified_session():
    from src.transcription.client import transcribe_audio
    from src.agents.agents import run_all_agents
    from src.verification.service import create_review_session, clerk_review_segment, clerk_complete_review, magistrate_certify
    segs = transcribe_audio("x.mp3", force_mock=True)["segments"]
    out = run_all_agents(segs, "2026-10-27", force_mock=True)
    s = create_review_session(out)
    for i in range(len(s["segments"])):
        clerk_review_segment(s, i, "Clerk Otieno", confirmed_speaker=s["segments"][i]["speaker"])
    clerk_complete_review(s, "Clerk Otieno")
    magistrate_certify(s, "Magistrate Achieng")
    return s

def _uncertified_session():
    from src.transcription.client import transcribe_audio
    from src.agents.agents import run_all_agents
    from src.verification.service import create_review_session
    segs = transcribe_audio("x.mp3", force_mock=True)["segments"]
    out = run_all_agents(segs, "2026-10-27", force_mock=True)
    return create_review_session(out)

def test_timeline_blocked_before_certification():
    import pytest
    from src.timeline.service import generate_case_timeline
    with pytest.raises(ValueError):
        generate_case_timeline(_uncertified_session(), force_mock=True)

def test_timeline_generates_after_certification():
    from src.timeline.service import generate_case_timeline
    s = _certified_session()
    t = generate_case_timeline(s, force_mock=True)
    assert "CR 123" in t["title"]
    assert len(t["steps"]) == 5
    assert t["approved"] is False
    assert t["needs_human_review"] is True

def test_timeline_approval_requires_name_and_audits():
    import pytest
    from src.timeline.service import generate_case_timeline, human_approve_timeline
    s = _certified_session()
    generate_case_timeline(s, force_mock=True)
    with pytest.raises(ValueError):
        human_approve_timeline(s, "")
    human_approve_timeline(s, "Clerk Otieno")
    assert s["timeline"]["approved"] is True
    assert "TIMELINE_HUMAN_APPROVED" in [a["action"] for a in s["audit_log"]]

def test_offline_redaction_masks_id_and_phone():
    from src.offline.service import create_offline_redaction
    d = create_offline_redaction("Witness ID 12345678 phone 0712345678 email a@b.co.ke", force_mock=True)
    assert "12345678" not in d["redacted_text"]
    assert "0712345678" not in d["redacted_text"]
    assert "[REDACTED_ID]" in d["redacted_text"]
    assert "[REDACTED_PHONE]" in d["redacted_text"]
    assert d["approved"] is False
    assert d["mode"] == "offline"

def test_offline_redaction_approval_requires_name():
    import pytest
    from src.offline.service import create_offline_redaction, human_approve_offline_redaction
    d = create_offline_redaction("ID 12345678", force_mock=True)
    with pytest.raises(ValueError):
        human_approve_offline_redaction(d, "")

def test_human_approves_offline_redaction():
    from src.offline.service import create_offline_redaction, human_approve_offline_redaction
    d = create_offline_redaction("ID 12345678", force_mock=True)
    human_approve_offline_redaction(d, "Clerk Otieno")
    assert d["approved"] is True
    assert d["approved_by"] == "Clerk Otieno"