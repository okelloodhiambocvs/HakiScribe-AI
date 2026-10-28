"""V2 config home: .env loading, Meta model names, key validation."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

META_API_KEY = os.getenv("META_API_KEY", "")
META_API_BASE = os.getenv("META_API_BASE", "https://api.meta.ai/v1")
META_VOICE_MODEL = os.getenv("META_VOICE_MODEL", "muse-voice-transcribe-1.0")
META_VOICE_MODE = os.getenv("META_VOICE_MODE", "DIARIZATION")
META_LANGUAGE_BIAS = os.getenv("META_LANGUAGE_BIAS", "")
META_REASONING_MODEL = os.getenv("META_REASONING_MODEL", "muse-spark")
META_WONDER_MODEL = os.getenv("META_WONDER_MODEL", "muse-wonder")
META_SAM_MODEL = os.getenv("META_SAM_MODEL", "sam-3.1")
META_IMAGE_MODEL = os.getenv("META_IMAGE_MODEL", "muse-image")
META_OPEN_MODEL = os.getenv("META_OPEN_MODEL", "muse-glimmer")
GLIMMER_MODEL_PATH = os.getenv("GLIMMER_MODEL_PATH", "")

def is_configured() -> bool:
    key = (META_API_KEY or "").strip()
    if not key or len(key) < 10:
        return False
    low = key.lower()
    if "your_key" in low or "placeholder" in low or "here_from" in low:
        return False
    return True

def get_meta_key() -> str:
    if not is_configured():
        return ""
    return META_API_KEY

def get_api_base() -> str:
    return (META_API_BASE or "").rstrip("/")


VOICE_MODES = ("PUSH_TO_TALK", "ENDPOINTING", "DIARIZATION")
KEYWORDS_PATH = Path(__file__).with_name("keywords.txt")
MAX_KEYWORDS = 50
MAX_KEYWORD_LEN = 40


def get_voice_mode() -> str:
    """Validated voice mode; default DIARIZATION, ValueError when invalid."""
    mode = (META_VOICE_MODE or "").strip().upper()
    if not mode:
        return "DIARIZATION"
    if mode not in VOICE_MODES:
        raise ValueError(
            f"invalid META_VOICE_MODE: {META_VOICE_MODE!r} "
            "(use PUSH_TO_TALK, ENDPOINTING, or DIARIZATION)"
        )
    return mode


def get_language_bias() -> list[str]:
    """Comma-separated languageBias list; empty list means not sent."""
    return [
        part.strip()
        for part in (META_LANGUAGE_BIAS or "").split(",")
        if part.strip()
    ]


def get_keywords(path: str | Path | None = None) -> list[str]:
    """Court terms from keywords.txt; capped, missing file means not sent.

    Skips blank lines and # comments, drops terms over 40 characters,
    and caps the list at 50 terms.
    """
    file_path = Path(path) if path else KEYWORDS_PATH
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    terms = []
    for line in lines:
        term = line.strip()
        if not term or term.startswith("#") or len(term) > MAX_KEYWORD_LEN:
            continue
        terms.append(term)
        if len(terms) >= MAX_KEYWORDS:
            break
    return terms

__all__ = [
    "META_API_KEY",
    "META_API_BASE",
    "META_VOICE_MODEL",
    "META_VOICE_MODE",
    "META_LANGUAGE_BIAS",
    "VOICE_MODES",
    "KEYWORDS_PATH",
    "MAX_KEYWORDS",
    "MAX_KEYWORD_LEN",
    "get_voice_mode",
    "get_language_bias",
    "get_keywords",
    "META_REASONING_MODEL",
    "META_WONDER_MODEL",
    "META_SAM_MODEL",
    "META_IMAGE_MODEL",
    "META_OPEN_MODEL",
    "GLIMMER_MODEL_PATH",
    "is_configured",
    "get_meta_key",
    "get_api_base",
]
