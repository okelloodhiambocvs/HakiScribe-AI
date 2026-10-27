"""V2 config home (migration shim).

Thin re-export of `src.utils.config` so V2 code has one import path without
duplicating .env loading or Meta API keys during migration.
"""

from src.utils.config import (
    META_API_BASE,
    META_API_KEY,
    META_REASONING_MODEL,
    META_VOICE_MODEL,
    META_WONDER_MODEL,
    get_api_base,
    get_meta_key,
    is_configured,
)

__all__ = [
    "META_API_KEY",
    "META_API_BASE",
    "META_VOICE_MODEL",
    "META_REASONING_MODEL",
    "META_WONDER_MODEL",
    "is_configured",
    "get_meta_key",
    "get_api_base",
]
