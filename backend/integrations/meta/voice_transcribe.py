"""Muse Voice Transcribe via Meta Model API.

Only V2 module that calls the transcription endpoint. Falls back to clearly
marked synthetic mock segments when offline. Original text is always
preserved exactly — English/Kiswahili mixing is never translated.
"""

import re
from pathlib import Path

import requests

from backend.core import config

ALLOWED_SPEAKERS = {
    "MAGISTRATE",
    "PROSECUTOR",
    "ADVOCATE",
    "ACCUSED",
    "COMPLAINANT",
    "WITNESS_PW1",
    "WITNESS_PW2",
    "COURT_ASSISTANT",
    "INVESTIGATING_OFFICER",
    "INTERPRETER",
    "UNKNOWN",
}

_SWAHILI_MARKERS = frozenset(
    """mheshimiwa mlalamikaji mshtakiwa kotini nyumbani kesi mahakama hakimu
    yupo sikuwa nilikuwa nilifika nikaona akikimbia alisema alifika
    kweli si mimi hapo leo saa mbili tatu halafu na ya wa ni tarehe
    sasa hivyo kwamba lakini au kama huyu yule siye hapana ndiyo
    tafadhali asante sawa basi tena hata bado tayari vizuri habari sana""".split()
)

_MOCK_LINES = (
    ("MAGISTRATE", 0.4, 4.2, 0.96, "Court is now in session. Case number CR 123 of 2026."),
    ("PROSECUTOR", 4.5, 8.1, 0.88, "Mheshimiwa, mlalamikaji yupo kotini leo."),
    ("COMPLAINANT", 8.3, 12.5, 0.79, "Mheshimiwa, nilifika nyumbani saa mbili, and then I saw the accused."),
    ("ACCUSED", 12.7, 16.0, 0.61, "Si kweli, mimi sikuwa hapo."),
    ("WITNESS_PW1", 16.2, 20.0, 0.83, "I was at the shop, halafu nikaona accused akikimbia."),
)


def normalize_speaker(raw_speaker: str | None) -> str:
    """Map a raw speaker label to the V2 taxonomy; UNKNOWN when unmapped."""
    if not raw_speaker:
        return "UNKNOWN"
    name = str(raw_speaker).replace("?", "").upper().replace(" ", "_").replace("-", "_")
    if name == "WITNESS":
        name = "WITNESS_PW1"
    return name if name in ALLOWED_SPEAKERS else "UNKNOWN"


def detect_language(text: str) -> str:
    """Classify text as en-KE, sw-KE, or mixed. Never alters the text."""
    words = re.findall(r"[a-z]+", (text or "").lower())
    if not words:
        return "en-KE"
    swahili = sum(1 for word in words if word in _SWAHILI_MARKERS)
    if swahili == 0:
        return "en-KE"
    if swahili / len(words) > 0.5:
        return "sw-KE"
    return "mixed"


def _mock_result() -> dict:
    segments = [
        {
            "idx": idx,
            "start_sec": start,
            "end_sec": end,
            "speaker": speaker,
            "confidence": confidence,
            "language": detect_language(text),
            "text_original": text,
        }
        for idx, (speaker, start, end, confidence, text) in enumerate(_MOCK_LINES)
    ]
    return {
        "model": "muse-voice-transcribe-mock",
        "status": "mock-no-key",
        "needs_human_review": True,
        "segments": segments,
    }


def _to_float(value: object, index: int, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"bad {field} in API segment {index}: {value!r}") from None


def _to_confidence(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_api_segments(raw_segments: list) -> list[dict]:
    normalized = []
    for idx, seg in enumerate(raw_segments):
        if not isinstance(seg, dict):
            raise ValueError(f"bad API segment {idx}: {seg!r}")
        if "start" not in seg and "start_sec" not in seg:
            raise ValueError(f"API segment {idx} missing start/start_sec")
        if "end" not in seg and "end_sec" not in seg:
            raise ValueError(f"API segment {idx} missing end/end_sec")
        text = seg.get("text_original", seg.get("text", ""))
        normalized.append(
            {
                "idx": idx,
                "start_sec": _to_float(seg.get("start", seg.get("start_sec")), idx, "start"),
                "end_sec": _to_float(seg.get("end", seg.get("end_sec")), idx, "end"),
                "speaker": normalize_speaker(seg.get("speaker")),
                "confidence": _to_confidence(seg.get("confidence")),
                "language": detect_language(text),
                "text_original": text,
            }
        )
    return normalized


def transcribe_audio_file(audio_path: str | Path, force_mock: bool = False) -> dict:
    """Transcribe audio via Muse Voice Transcribe (mock when offline).

    Mock needs no file. The real path raises RuntimeError when the audio
    file does not exist, and posts to the Meta endpoint from config.
    """
    if force_mock or not config.is_configured():
        return _mock_result()

    path = Path(audio_path)
    if not path.is_file():
        raise RuntimeError(f"audio file does not exist: {audio_path}")

    # Same endpoint pattern as src/transcription/client.py; confirm against
    # dev.meta.ai portal docs before relying on exact paths/fields.
    url = f"{config.get_api_base()}/{config.META_VOICE_MODEL}/transcribe"
    headers = {"Authorization": f"Bearer {config.get_meta_key()}"}
    with open(path, "rb") as handle:
        files = {"audio": (path.name, handle)}
        data = {"language_hints": "en-KE,sw-KE", "word_confidence": "true", "diarize": "true"}
        response = requests.post(url, headers=headers, files=files, data=data, timeout=120)
    response.raise_for_status()
    payload = response.json()
    raw_segments = payload.get("segments", payload.get("results", []))
    return {
        "model": config.META_VOICE_MODEL,
        "status": "real",
        "needs_human_review": True,
        "segments": _normalize_api_segments(raw_segments),
        "raw": payload,
    }
