def _mock_segments():
    from src.transcription.client import transcribe_audio
    return transcribe_audio("x.mp3", force_mock=True)["segments"]

def test_structurer_extracts_case_and_never_certifies():
    from src.agents.agents import structure_transcript
    res = structure_transcript(_mock_segments(), force_mock=True)
    assert "CR 123" in res["case_number"]
    assert res["needs_human_review"] is True
    assert res["certified"] is False

def test_guardian_flags_for_human():
    from src.agents.agents import structure_transcript, guardian_check
    structured = structure_transcript(_mock_segments(), force_mock=True)
    guard = guardian_check(structured)
    assert guard["flag_count"] >= 1
    assert all(f["requires_human"] for f in guard["flags"])

def test_deadline_14_and_60_days():
    from src.agents.agents import calculate_deadlines
    d = calculate_deadlines("2026-10-27")
    assert d["notice_of_appeal_due"] == "2026-11-10"
    assert d["record_of_appeal_due"] == "2026-12-26"
    assert d["requires_human_confirmation"] is True

def test_orchestrator_trace_and_human_lock():
    from src.agents.agents import run_all_agents
    out = run_all_agents(_mock_segments(), judgment_date_str="2026-10-27", force_mock=True)
    assert len(out["agent_trace"]) == 3
    assert out["needs_human_review"] is True
    assert out["certified"] is False