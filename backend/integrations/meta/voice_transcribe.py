"""Muse Voice Transcribe via Meta Model API.

Only V2 module that calls the transcription endpoint. Posts the prepared
WAV with a DIARIZATION request, maps documented turns to segments, and
falls back to clearly marked synthetic mock turns when offline. Turn
text is always preserved exactly — English/Kiswahili mixing is never
translated. Only documented response fields are read; anything else
raises. The API returns no confidence scores, so confidence is NULL.
"""

import json
import re
import tempfile
import time
from pathlib import Path

import requests

from backend.core import config
from backend.core.errors import HakiScribeError
from backend.integrations.meta.audio_prep import prepare_wav, wav_duration_sec

REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRIES = 3
RETRY_BASE_SECONDS = 1.0
ENDPOINT_PATH = "/asr/transcribe"
NO_TURNS_WARNING = "no turn timestamps returned"

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

# Synthetic mock turns: (speaker letter, startMs, endMs, text). Same
# courtroom lines as before, mapped through the real turn parser so the
# mock shape matches DIARIZATION exactly (Speaker A/B, NULL confidence).
_MOCK_TURNS = (
    ("A", 400, 4200, "Court is now in session. Case number CR 123 of 2026."),
    ("B", 4500, 8100, "Mheshimiwa, mlalamikaji yupo kotini leo."),
    ("A", 8300, 12500, "Mheshimiwa, nilifika nyumbani saa mbili, and then I saw the accused."),
    ("B", 12700, 16000, "Si kweli, mimi sikuwa hapo."),
    ("A", 16200, 20000, "I was at the shop, halafu nikaona accused akikimbia."),
)


class TranscriptionError(HakiScribeError):
    """Raised when the transcription endpoint call or response fails."""

    code = "transcription_failed"


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


def build_request_payload(
    model: str | None = None,
    mode: str | None = None,
    language_bias: list[str] | None = None,
    keywords: list[str] | None = None,
) -> dict:
    """Build the multipart "request" JSON from config plus overrides.

    languageBias and keywords are sent only when their lists are
    non-empty. None means "read from config".
    """
    payload = {
        "mode": mode or config.get_voice_mode(),
        "model": model or config.META_VOICE_MODEL,
        "audioEncoding": "WAV",
    }
    bias = config.get_language_bias() if language_bias is None else language_bias
    if bias:
        payload["languageBias"] = list(bias)
    terms = config.get_keywords() if keywords is None else keywords
    if terms:
        payload["keywords"] = list(terms)
    return payload


def _turn_to_segment(turn: dict, idx: int) -> dict:
    """Map one documented turn to a segment; verbatim text, NULL confidence."""
    if not isinstance(turn, dict):
        raise ValueError(f"bad API turn {idx}: {turn!r}")
    for field in ("startMs", "endMs", "transcript"):
        if turn.get(field) is None:
            raise ValueError(f"API turn {idx} missing {field}")
    try:
        start_sec = float(turn["startMs"]) / 1000
        end_sec = float(turn["endMs"]) / 1000
    except (TypeError, ValueError):
        raise ValueError(f"bad timestamps in API turn {idx}: {turn!r}") from None
    text = turn["transcript"]
    if not isinstance(text, str):
        raise ValueError(f"bad transcript in API turn {idx}: {text!r}")
    letter = str(turn.get("speaker") or "").strip()
    if letter:
        speaker, label = f"Speaker {letter}", letter
    else:
        speaker, label = "UNKNOWN", None
    return {
        "idx": idx,
        "start_sec": start_sec,
        "end_sec": end_sec,
        "speaker": speaker,
        "speaker_label": label,
        "confidence": None,
        "language": detect_language(text),
        "text_original": text,
    }


def _turn_start_ms(turn: object) -> float:
    """Sort key for turns; unparseable entries sort first and then raise."""
    if isinstance(turn, dict):
        start = turn.get("startMs")
        if isinstance(start, (int, float)):
            return float(start)
    return -1.0


def parse_transcription_response(payload: object) -> tuple[list[dict], str | None]:
    """Map {transcript, audioDurationMs, turns} to (segments, warning).

    Turns sort by startMs and take idx in order. Empty turns with a
    non-empty transcript yield one UNKNOWN segment spanning the whole
    audio plus the no-turns warning; empty everything raises.
    """
    if not isinstance(payload, dict):
        raise TranscriptionError(
            "transcription response is not a JSON object (top-level keys: [])"
        )
    top_keys = sorted(payload.keys())
    turns = payload.get("turns") or []
    transcript = payload.get("transcript") or ""
    if not isinstance(turns, list):
        raise TranscriptionError(
            "transcription response turns is not a list "
            f"(top-level keys: {top_keys})"
        )
    if turns:
        try:
            segments = [
                _turn_to_segment(turn, idx)
                for idx, turn in enumerate(sorted(turns, key=_turn_start_ms))
            ]
        except ValueError as exc:
            raise TranscriptionError(str(exc)) from exc
        return segments, None
    if isinstance(transcript, str) and transcript != "":
        try:
            end_sec = float(payload.get("audioDurationMs") or 0) / 1000
        except (TypeError, ValueError):
            end_sec = 0.0
        return (
            [
                {
                    "idx": 0,
                    "start_sec": 0.0,
                    "end_sec": end_sec,
                    "speaker": "UNKNOWN",
                    "speaker_label": None,
                    "confidence": None,
                    "language": detect_language(transcript),
                    "text_original": transcript,
                }
            ],
            NO_TURNS_WARNING,
        )
    raise TranscriptionError(
        "no turns or transcript in transcription response "
        f"(top-level keys: {top_keys})"
    )


def _mock_result() -> dict:
    segments = [
        _turn_to_segment(
            {"startMs": start, "endMs": end, "transcript": text, "speaker": letter},
            idx,
        )
        for idx, (letter, start, end, text) in enumerate(_MOCK_TURNS)
    ]
    return {
        "model": "muse-voice-transcribe-mock",
        "status": "mock-no-key",
        "needs_human_review": True,
        "segments": segments,
        "warning": None,
    }


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


def html_title(body: str) -> str | None:
    """Return the <title> text of an HTML body, else None."""
    match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    text = re.sub(r"\s+", " ", match.group(1)).strip()
    return text[:200] if text else None


def is_html_body(body: str, content_type: str = "") -> bool:
    """True when a response body looks like an HTML page, not an API payload."""
    if "html" in (content_type or "").lower():
        return True
    lowered = (body or "").lstrip().lower()
    return lowered.startswith("<!doctype html") or lowered.startswith("<html")


def _format_http_error(response: requests.Response) -> str:
    """Short key-free message; HTML bodies collapse to title + base hint."""
    status = response.status_code
    headers = getattr(response, "headers", None) or {}
    content_type = headers.get("Content-Type", "") or ""
    body = response.text or ""
    if is_html_body(body, content_type):
        title = html_title(body) or "(no title found)"
        return (
            f"transcription request failed: HTTP {status}: {title} "
            "(HTML page, not an API response: check META_API_BASE)"
        )
    return f"transcription request failed: HTTP {status}: {_scrub_key(body[:500])}"


def _request_id_of(response: requests.Response | None) -> str | None:
    """Read the request id from response headers when present."""
    headers = getattr(response, "headers", None) or {}
    try:
        return headers.get("x-request-id") or headers.get("request-id")
    except Exception:
        return None


def _notify_attempt(
    on_attempt,
    response: requests.Response | None,
    ok: bool,
    error_code: str | None,
    latency_ms: float,
    audio_bytes: int | None,
    audio_ms: int | None,
) -> None:
    """Report one HTTP attempt; logging failures never break transcription."""
    if on_attempt is None:
        return
    info = {
        "http_status": response.status_code if response is not None else None,
        "ok": ok,
        "error_code": error_code,
        "latency_ms": latency_ms,
        "audio_bytes": audio_bytes,
        "audio_ms": audio_ms,
        "request_id": _request_id_of(response),
    }
    try:
        on_attempt(info)
    except Exception:
        pass


def _post_with_retry(
    url: str,
    headers: dict,
    files: dict,
    on_attempt=None,
    audio_bytes: int | None = None,
    audio_ms: int | None = None,
) -> requests.Response:
    """POST with 429 retries; every attempt is reported via on_attempt."""
    for attempt in range(MAX_RETRIES + 1):
        started = time.monotonic()
        try:
            response = requests.post(
                url, headers=headers, files=files, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except requests.Timeout as exc:
            _notify_attempt(
                on_attempt, None, False, "TIMEOUT",
                (time.monotonic() - started) * 1000, audio_bytes, audio_ms,
            )
            raise TranscriptionError(
                f"transcription request timed out after {REQUEST_TIMEOUT_SECONDS}s"
            ) from exc
        except requests.ConnectionError as exc:
            _notify_attempt(
                on_attempt, None, False, "CONNECTION_ERROR",
                (time.monotonic() - started) * 1000, audio_bytes, audio_ms,
            )
            raise TranscriptionError(f"transcription connection failed: {exc}") from exc
        except requests.RequestException as exc:
            _notify_attempt(
                on_attempt, None, False, "REQUEST_ERROR",
                (time.monotonic() - started) * 1000, audio_bytes, audio_ms,
            )
            raise TranscriptionError(f"transcription request failed: {exc}") from exc
        status = response.status_code
        latency_ms = (time.monotonic() - started) * 1000
        if status == 429 and attempt < MAX_RETRIES:
            _notify_attempt(
                on_attempt, response, False, "HTTP_429",
                latency_ms, audio_bytes, audio_ms,
            )
            time.sleep(_retry_delay_seconds(response, attempt))
            continue
        _notify_attempt(
            on_attempt, response, status < 400,
            None if status < 400 else f"HTTP_{status}",
            latency_ms, audio_bytes, audio_ms,
        )
        return response
    raise TranscriptionError("transcription retry loop exhausted")  # unreachable


def transcribe_audio_file(
    audio_path: str | Path,
    force_mock: bool = False,
    on_attempt=None,
) -> dict:
    """Transcribe audio via Muse Voice Transcribe (mock when offline).

    Mock needs no file. The real path prepares a 16 kHz mono WAV in a
    temporary directory, posts it with a config-driven request, parses
    documented turns only, and reports every HTTP attempt through the
    optional on_attempt callback (service persists it via the api_calls
    repository; the integration itself never touches the database).
    Raises RuntimeError when the audio file is missing, AudioPrepError
    when preparation fails, ValueError for invalid voice-mode config,
    and TranscriptionError for request/response failures.
    """
    if force_mock or not config.is_configured():
        return _mock_result()

    path = Path(audio_path)
    if not path.is_file():
        raise RuntimeError(f"audio file does not exist: {audio_path}")

    payload = build_request_payload()
    url = f"{config.get_api_base()}{ENDPOINT_PATH}"
    headers = {"Authorization": f"Bearer {config.get_meta_key()}"}
    with tempfile.TemporaryDirectory(prefix="hakiscribe-asr-") as tmp_dir:
        wav_path = prepare_wav(path, Path(tmp_dir) / "request.wav")
        wav_bytes = wav_path.read_bytes()
        try:
            audio_ms = int(wav_duration_sec(wav_path) * 1000)
        except Exception:
            audio_ms = None
        files = {
            "request": (None, json.dumps(payload), "application/json"),
            "audio": (wav_path.name, wav_bytes, "audio/wav"),
        }
        response = _post_with_retry(
            url, headers, files,
            on_attempt=on_attempt,
            audio_bytes=len(wav_bytes),
            audio_ms=audio_ms,
        )

    if response.status_code >= 400:
        raise TranscriptionError(_format_http_error(response))
    try:
        response_payload = response.json()
    except ValueError as exc:
        raise TranscriptionError("transcription response is not valid JSON") from exc

    segments, warning = parse_transcription_response(response_payload)
    return {
        "model": config.META_VOICE_MODEL,
        "status": "real",
        "needs_human_review": True,
        "segments": segments,
        "warning": warning,
        "raw": response_payload,
    }
