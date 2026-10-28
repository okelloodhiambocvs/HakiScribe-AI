"""V2 config home: .env loading, Meta model names, key validation."""

import os
from dotenv import load_dotenv

load_dotenv()

META_API_KEY = os.getenv("META_API_KEY", "")
META_API_BASE = os.getenv("META_API_BASE", "https://api.meta.ai/v1")
META_VOICE_MODEL = os.getenv("META_VOICE_MODEL", "muse-voice-transcribe-1.0")
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

__all__ = [
    "META_API_KEY",
    "META_API_BASE",
    "META_VOICE_MODEL",
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
