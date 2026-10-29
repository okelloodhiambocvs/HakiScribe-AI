"""Demo data + docs honesty tests: script, wav, loader, README claims."""

import hashlib
import json
import re
import struct
import wave
from pathlib import Path

import pytest

from backend.services import ingestion_service
from backend.services.ingestion_service import (
    DEMO_RECORDING_PATH,
    load_demo_recording,
    validate_and_store_upload,
)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "demo-data" / "synthetic" / "case-cr-123-2026-script.md"
ARCH_PATH = ROOT / "docs" / "architecture" / "ARCHITECTURE-V2.md"
README_PATH = ROOT / "README.md"

_SPEAKER_LINE = re.compile(r"^([A-Z][A-Z0-9_]+):\s*(.+)$")


def _allowed_speakers() -> set[str]:
    for line in ARCH_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if (
            "MAGISTRATE" in stripped
            and "UNKNOWN" in stripped
            and re.fullmatch(r"[A-Z0-9_, ]+", stripped)
        ):
            return {part.strip() for part in stripped.split(",") if part.strip()}
    raise AssertionError("speaker taxonomy line not found in architecture doc")


def _script_turns():
    turns = []
    for line in SCRIPT_PATH.read_text(encoding="utf-8").splitlines():
        match = _SPEAKER_LINE.match(line.strip())
        if match:
            turns.append((match.group(1), match.group(2)))
    return turns


def _require_demo_wav() -> Path:
    demo = Path(DEMO_RECORDING_PATH)
    if not demo.is_absolute():
        demo = ROOT / demo
    if not demo.is_file():
        pytest.skip("demo wav not generated yet (run scripts/make_demo_audio.ps1)")
    return demo


def _require_reference() -> Path:
    ref = ROOT / "demo-data" / "synthetic" / "case-cr-123-2026.reference.json"
    if not ref.is_file():
        pytest.skip("demo reference not generated yet (run scripts/make_demo_audio.ps1)")
    return ref


def test_reference_json_valid_and_consistent_with_wav():
    demo = _require_demo_wav()
    ref_path = _require_reference()
    reference = json.loads(ref_path.read_text(encoding="utf-8-sig"))
    turns = reference["turns"]
    assert len(turns) >= 5
    allowed = _allowed_speakers()
    previous_end = 0
    for position, turn in enumerate(turns):
        assert turn["turn_idx"] == position
        assert turn["role"] in allowed
        assert turn["voice"]
        assert turn["start_ms"] < turn["end_ms"]
        assert turn["start_ms"] >= previous_end
        assert turn["text"].strip()
        previous_end = turn["end_ms"]
    assert (
        hashlib.sha256(demo.read_bytes()).hexdigest()
        == reference["audio_sha256"]
    )
    with wave.open(str(demo), "rb") as wav_file:
        duration = wav_file.getnframes() / wav_file.getframerate()
    assert abs(turns[-1]["end_ms"] / 1000 - duration) < 1.0


def test_script_uses_only_allowed_speaker_labels():
    allowed = _allowed_speakers()
    assert len(allowed) == 11
    turns = _script_turns()
    assert len(turns) >= 5
    for speaker, _text in turns:
        assert speaker in allowed, speaker


def test_demo_wav_is_valid_16k_mono():
    demo = _require_demo_wav()
    with wave.open(str(demo), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16000
        count = wav.getnframes()
        duration = count / wav.getframerate()
        assert 15 <= duration <= 600
        frames = wav.readframes(count)
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    assert mean_square ** 0.5 > 300


def test_load_demo_recording_stores_like_normal_upload(tmp_path):
    upload_dir = tmp_path / "uploads"
    db_path = tmp_path / "t.db"
    demo_bytes = _require_demo_wav().read_bytes()
    demo_rec = load_demo_recording(
        "Reviewer Amina", upload_dir=upload_dir, db_path=db_path
    )
    normal_rec = validate_and_store_upload(
        "case-cr-123-2026.wav", demo_bytes, "Reviewer Amina",
        synthetic_attestation=True, upload_dir=upload_dir, db_path=db_path,
    )
    assert set(demo_rec) == set(normal_rec)
    assert demo_rec["sha256"] == hashlib.sha256(demo_bytes).hexdigest()
    assert demo_rec["sha256"] == normal_rec["sha256"]
    assert demo_rec["size_bytes"] == len(demo_bytes)
    assert demo_rec["uploaded_by"] == "Reviewer Amina"
    assert Path(demo_rec["stored_path"]).read_bytes() == demo_bytes


def test_load_demo_recording_missing_file_friendly_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ingestion_service, "DEMO_RECORDING_PATH", tmp_path / "nope.wav"
    )
    with pytest.raises(ValueError, match="Demo recording not found"):
        load_demo_recording(
            "Reviewer Amina", upload_dir=tmp_path / "u", db_path=tmp_path / "t.db"
        )


def test_readme_live_claims_are_backed():
    text = README_PATH.read_text(encoding="utf-8")
    assert "Planned" in text
    lowered = text.lower()
    assert re.search(r"spark[^.\n]{0,60}\blive\b", lowered)
    assert re.search(r"docx[^.\n]{0,60}\blive\b", lowered)
