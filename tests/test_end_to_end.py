def _uncertified_session():
    from src.transcription.client import transcribe_audio
    from src.agents.agents import run_all_agents
    from src.verification.service import create_review_session
    segs = transcribe_audio("x.mp3", force_mock=True)["segments"]
    out = run_all_agents(segs, "2026-10-27", force_mock=True)
    return create_review_session(out)

def test_no_human_no_certification_blocks_all_public_outputs():
    import pytest
    from src.explainer.service import generate_mwananchi_explainer
    from src.export.pdf_service import build_pdf_bytes
    from src.timeline.service import generate_case_timeline

    s = _uncertified_session()
    assert s["certified"] is False

    with pytest.raises(ValueError):
        generate_mwananchi_explainer(s, force_mock=True)
    with pytest.raises(ValueError):
        build_pdf_bytes(s, "Clerk Otieno")
    with pytest.raises(ValueError):
        generate_case_timeline(s, force_mock=True)

def test_full_human_journey_from_ai_draft_to_certified_outputs():
    from src.transcription.client import transcribe_audio
    from src.agents.agents import run_all_agents
    from src.verification.service import create_review_session, clerk_review_segment, clerk_complete_review, magistrate_certify
    from src.explainer.service import generate_mwananchi_explainer, human_approve_explainer
    from src.export.pdf_service import build_pdf_bytes
    from src.vision.service import create_redaction_draft, human_approve_redaction
    from src.timeline.service import generate_case_timeline, human_approve_timeline
    from src.offline.service import create_offline_redaction, human_approve_offline_redaction

    # 1. AI proposes - draft only
    segs = transcribe_audio("demo-data/synthetic/cr-123-mock.mp3", force_mock=True)["segments"]
    agent_out = run_all_agents(segs, judgment_date_str="2026-10-27", force_mock=True)
    session = create_review_session(agent_out)
    assert session["status"] == "AI_DRAFT"
    assert session["certified"] is False

    # 2. HUMAN 1 - Clerk reviews every segment individually
    for i in range(len(session["segments"])):
        clerk_review_segment(session, i, "Clerk Otieno", confirmed_speaker=session["segments"][i]["speaker"])
    clerk_complete_review(session, "Clerk Otieno")

    # 3. HUMAN 2 - Magistrate certifies, different person
    magistrate_certify(session, "Magistrate Achieng")
    assert session["certified"] is True
    assert session["final_hash"] and len(session["final_hash"]) == 64

    # 4. Public outputs - each still needs named human approval
    generate_mwananchi_explainer(session, force_mock=True)
    human_approve_explainer(session, "Clerk Otieno")

    pdf = build_pdf_bytes(session, "Clerk Otieno")
    assert pdf[:4] == b"%PDF"

    draft = create_redaction_draft("synthetic-charge-sheet.jpg", force_mock=True)
    human_approve_redaction(draft, "Clerk Otieno", session=session)
    assert draft["approved"] is True

    generate_case_timeline(session, force_mock=True)
    human_approve_timeline(session, "Clerk Otieno")

    offline = create_offline_redaction(session["final_text"] + " Witness phone 0712345678 ID 12345678", force_mock=True)
    assert "0712345678" not in offline["redacted_text"]
    human_approve_offline_redaction(offline, "Clerk Otieno", session=session)

    # 5. Audit log proves who did what
    actions = [a["action"] for a in session["audit_log"]]
    assert "AI_DRAFT_CREATED" in actions
    assert "CLERK_REVIEW_COMPLETE" in actions
    assert "MAGISTRATE_CERTIFIED" in actions
    assert "EXPLAINER_HUMAN_APPROVED" in actions
    assert "PDF_EXPORTED" in actions
    assert "TIMELINE_HUMAN_APPROVED" in actions
    assert "OFFLINE_REDACTION_HUMAN_APPROVED" in actions