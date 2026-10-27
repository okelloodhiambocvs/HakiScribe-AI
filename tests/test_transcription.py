def test_mock_structure_and_human_lock():
    from src.transcription.client import transcribe_audio, needs_human_review, CONFIDENCE_THRESHOLD
    res = transcribe_audio("demo-data/synthetic/cr-123-mock.mp3", force_mock=True)
    assert "segments" in res
    assert len(res["segments"]) == 3
    assert res["needs_human_review"] is True
    assert any(s.get("confidence", 1) < CONFIDENCE_THRESHOLD for s in res["segments"])

def test_human_rule_always_true():
    from src.transcription.client import needs_human_review
    # Even perfect AI still needs human certify
    assert needs_human_review({"segments": [{"confidence": 0.99}]}) is True