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

def test_explainer_blocked_before_certification():
    import pytest
    from src.explainer.service import generate_mwananchi_explainer
    s = _uncertified_session()
    with pytest.raises(ValueError):
        generate_mwananchi_explainer(s, force_mock=True)

def test_explainer_generates_en_sw_after_certification():
    from src.explainer.service import generate_mwananchi_explainer
    s = _certified_session()
    e = generate_mwananchi_explainer(s, force_mock=True)
    assert "CR 123" in e["explainer_en"]
    assert "Kesi yako" in e["explainer_sw"]
    assert e["approved"] is False
    assert e["needs_human_review"] is True

def test_explainer_approval_requires_name():
    import pytest
    from src.explainer.service import generate_mwananchi_explainer, human_approve_explainer
    s = _certified_session()
    generate_mwananchi_explainer(s, force_mock=True)
    with pytest.raises(ValueError):
        human_approve_explainer(s, "")

def test_human_approves_explainer_and_audit_logs():
    from src.explainer.service import generate_mwananchi_explainer, human_approve_explainer
    s = _certified_session()
    generate_mwananchi_explainer(s, force_mock=True)
    human_approve_explainer(s, "Clerk Otieno")
    assert s["explainer"]["approved"] is True
    assert s["explainer"]["approved_by"] == "Clerk Otieno"
    actions = [a["action"] for a in s["audit_log"]]
    assert "EXPLAINER_HUMAN_APPROVED" in actions