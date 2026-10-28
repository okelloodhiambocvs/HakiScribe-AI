"""Muse Voice Transcribe via Meta Model API.

Only V2 module that calls the transcription endpoint. Falls back to clearly
marked synthetic mock segments when offline. Original text is always
preserved exactly — English/Kiswahili mixing is never translated.
Only documented response fields are read; anything else raises.
"""

import json
import re
import tempfile
import time
from pathlib import Path

import requests

from backend.core import config
from backend.integrations.meta.audio_prep import prepare_wav

REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRIES = 3
RETRY_BASE_SECONDS = 1.0

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


class TranscriptionError(Exception):
    """Raised when the transcription endpoint call or response fails."""


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


def _request_payload(model: str) -> dict:
    return {"mode": "PUSH_TO_TALK", "model": model, "audioEncoding": "WAV"}


def _retry_delay_seconds(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    return RETRY_BASE_SECONDS * (2**attempt)


def _scrub_key(text: str) -> str:
    key = config.get_meta_key()
    if key:
        text = text.replace(key, "[REDACTED]")
    return text


def _post_with_retry(url: str, headers: dict, files: dict) -> requests.Response:
    last_response = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                url, headers=headers, files=files, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except requests.Timeout as exc:
            raise TranscriptionError(
                f"transcription request timed out after {REQUEST_TIMEOUT_SECONDS}s"
            ) from exc
        except requests.ConnectionError as exc:
            raise TranscriptionError(f"transcription connection failed: {exc}") from exc
        except requests.RequestException as exc:
            raise TranscriptionError(f"transcription request failed: {exc}") from exc
        if response.status_code != 429 or attempt == MAX_RETRIES:
            return response
        last_response = response
        time.sleep(_retry_delay_seconds(response, attempt))
    return last_response


def transcribe_audio_file(audio_path: str | Path, force_mock: bool = False) -> dict:
    """Transcribe audio via Muse Voice Transcribe (mock when offline).

    Mock needs no file. The real path prepares a 16 kHz mono WAV in a
    temporary directory, posts it once, and parses documented fields only.
    Raises RuntimeError when the audio file is missing, AudioPrepError when
    preparation fails, and TranscriptionError for request/response failures.
    """
    if force_mock or not config.is_configured():
        return _mock_result()

    path = Path(audio_path)
    if not path.is_file():
        raise RuntimeError(f"audio file does not exist: {audio_path}")

    url = f"{config.get_api_base()}/asr/transcribe"
    headers = {"Authorization": f"Bearer {config.get_meta_key()}"}
    with tempfile.TemporaryDirectory(prefix="hakiscribe-asr-") as tmp_dir:
        wav_path = prepare_wav(path, Path(tmp_dir) / "request.wav")
        wav_bytes = wav_path.read_bytes()
        files = {
            "request": (None, json.dumps(_request_payload(config.META_VOICE_MODEL)), "application/json"),
            "audio": (wav_path.name, wav_bytes, "audio/wav"),
        }
        response = _post_with_retry(url, headers, files)

    if response.status_code >= 400:
        body = _scrub_key(response.text[:500])
        raise TranscriptionError(
            f"transcription request failed: HTTP {response.status_code}: {body}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise TranscriptionError("transcription response is not valid JSON") from exc

    if isinstance(payload, dict):
        top_keys = sorted(payload.keys())
        raw_segments = payload.get("segments", payload.get("results", []))
    else:
        top_keys = []
        raw_segments = []
    if not isinstance(raw_segments, list) or len(raw_segments) == 0:
        raise TranscriptionError(
            "no recognisable segments in transcription response "
            f"(top-level keys: {top_keys})"
        )
    try:
        segments = _normalize_api_segments(raw_segments)
    except ValueError as exc:
        raise TranscriptionError(str(exc)) from exc
    return {
        "model": config.META_VOICE_MODEL,
        "status": "real",
        "needs_human_review": True,
        "segments": segments,
        "raw": payload,
    }
