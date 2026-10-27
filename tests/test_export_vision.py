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

def test_pdf_blocked_before_certification():
    import pytest
    from src.export.pdf_service import build_pdf_bytes
    with pytest.raises(ValueError):
        build_pdf_bytes(_uncertified_session(), "Clerk Otieno")

def test_pdf_requires_exporter_name():
    import pytest
    from src.export.pdf_service import build_pdf_bytes
    with pytest.raises(ValueError):
        build_pdf_bytes(_certified_session(), "")

def test_pdf_generates_after_certification_and_audits():
    from src.export.pdf_service import build_pdf_bytes
    s = _certified_session()
    pdf = build_pdf_bytes(s, "Clerk Otieno")
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 500
    assert "PDF_EXPORTED" in [a["action"] for a in s["audit_log"]]

def test_sam_mock_segments_include_sensitive_masks():
    from src.vision.service import create_redaction_draft
    d = create_redaction_draft("synthetic-charge-sheet.jpg", force_mock=True)
    labels = [s["label"] for s in d["segments"]]
    assert "SIGNATURE" in labels
    assert "ID_NUMBER" in d["mask_labels"]
    assert d["approved"] is False

def test_redaction_approval_requires_name():
    import pytest
    from src.vision.service import create_redaction_draft, human_approve_redaction
    d = create_redaction_draft("x.jpg", force_mock=True)
    with pytest.raises(ValueError):
        human_approve_redaction(d, "")

def test_human_approves_redaction():
    from src.vision.service import create_redaction_draft, human_approve_redaction
    d = create_redaction_draft("x.jpg", force_mock=True)
    human_approve_redaction(d, "Clerk Otieno")
    assert d["approved"] is True
    assert d["approved_by"] == "Clerk Otieno"
    assert d["status"] == "HUMAN_APPROVED_REDACTION"