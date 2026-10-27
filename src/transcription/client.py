from pathlib import Path
import requests
from src.utils.config import META_API_KEY, META_VOICE_MODEL, get_api_base, is_configured

CONFIDENCE_THRESHOLD = 0.75

# SYNTHETIC ONLY - no real litigants. Used when no key, so tests pass offline.
MOCK_RESULT = {
    "model": "muse-voice-transcribe-mock",
    "status": "mock-no-key",
    "language": "en-KE/sw-KE mix SYNTHETIC",
    "segments": [
        {"start": 0.4, "end": 4.2, "speaker": "MAGISTRATE?", "text": "Court is now in session. Case number CR 123 of 2026.", "confidence": 0.96},
        {"start": 4.5, "end": 8.1, "speaker": "CLERK?", "text": "Mheshimiwa, mshtakiwa yupo kotini.", "confidence": 0.82},
        {"start": 8.3, "end": 12.0, "speaker": "ACCUSED?", "text": "Si kweli, mimi sikuwa hapo tarehe kumi na mbili.", "confidence": 0.61},
    ],
}

def needs_human_review(result: dict) -> bool:
    """HUMAN RULE: AI never final. Always True in v1. Clerk + Magistrate must act."""
    for s in result.get("segments", []):
        if s.get("confidence", 0) < CONFIDENCE_THRESHOLD:
            return True
    return True

def transcribe_audio(audio_path: str | Path, force_mock: bool = False) -> dict:
    """
    LOCKED: Muse Voice Transcribe via Meta Model API.
    If no key or force_mock=True -> return synthetic mock.
    Else -> POST to real endpoint.
    """
    if force_mock or not is_configured():
        out = dict(MOCK_RESULT)
        out["audio"] = str(audio_path)
        out["needs_human_review"] = True
        return out

    # REAL PATH - update URL to match YOUR dev.meta.ai portal docs exactly
    base = get_api_base()
    url = f"{base}/{META_VOICE_MODEL}/transcribe"
    headers = {"Authorization": f"Bearer {META_API_KEY}"}

    with open(audio_path, "rb") as f:
        files = {"audio": (Path(audio_path).name, f)}
        data = {"language_hints": "en-KE,sw-KE", "word_confidence": "true", "diarize": "true"}
        r = requests.post(url, headers=headers, files=files, data=data, timeout=120)
    r.raise_for_status()
    payload = r.json()
    segments = payload.get("segments", payload.get("results", []))
    return {
        "model": META_VOICE_MODEL,
        "status": "real",
        "segments": segments,
        "raw": payload,
        "needs_human_review": True,
    }