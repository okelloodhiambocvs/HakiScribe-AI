import os
from dotenv import load_dotenv

load_dotenv()

META_API_KEY = os.getenv("META_API_KEY", "")
META_API_BASE = os.getenv("META_API_BASE", "https://dev.meta.ai/model-api/v1")
META_VOICE_MODEL = os.getenv("META_VOICE_MODEL", "muse-voice-transcribe")
META_REASONING_MODEL = os.getenv("META_REASONING_MODEL", "muse-spark")
META_WONDER_MODEL = os.getenv("META_WONDER_MODEL", "muse-wonder")

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