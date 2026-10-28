"""Probe Muse Voice Transcribe once and dump the raw response (debug tool).

Usage: python scripts/probe_voice_api.py <audio_file>
Prints HTTP status, top-level JSON keys, and the first 1500 characters of
the pretty-printed response. Never prints the API key. Exits non-zero
on failure.
"""

import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import requests

from backend.core.config import META_VOICE_MODEL, get_api_base, get_meta_key, is_configured
from backend.integrations.meta.audio_prep import prepare_wav
from backend.integrations.meta.voice_transcribe import html_title, is_html_body


def _scrub(text: str) -> str:
    key = get_meta_key()
    if key:
        text = text.replace(key, "[REDACTED]")
    return text


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: probe_voice_api.py <audio_file>", file=sys.stderr)
        return 2
    src = Path(argv[1])
    if not src.is_file():
        print(f"audio file not found: {src}", file=sys.stderr)
        return 1
    if not is_configured():
        print("META_API_KEY not configured", file=sys.stderr)
        return 1
    try:
        with tempfile.TemporaryDirectory(prefix="hakiscribe-probe-") as tmp_dir:
            wav_path = prepare_wav(src, Path(tmp_dir) / "probe.wav")
            # Same wire shape as voice_transcribe.py (canonical reference).
            url = f"{get_api_base()}/asr/transcribe"
            headers = {"Authorization": f"Bearer {get_meta_key()}"}
            print(f"request URL: {url}")
            payload = {"mode": "PUSH_TO_TALK", "model": META_VOICE_MODEL, "audioEncoding": "WAV"}
            with open(wav_path, "rb") as handle:
                files = {
                    "request": (None, json.dumps(payload), "application/json"),
                    "audio": (wav_path.name, handle, "audio/wav"),
                }
                response = requests.post(url, headers=headers, files=files, timeout=120)
    except Exception as exc:
        print(_scrub(f"probe failed: {exc}"), file=sys.stderr)
        return 1

    print(f"HTTP status: {response.status_code}")
    content_type = response.headers.get("Content-Type", "") or ""
    print(f"Content-Type: {content_type or '<missing>'}")
    for name in ("x-request-id", "retry-after", "server"):
        value = response.headers.get(name)
        if value is not None:
            print(f"{name}: {value}")
    body = response.text or ""
    if is_html_body(body, content_type):
        print(html_title(body) or "(no title found)")
        print("(HTML page, not an API response: check META_API_BASE)")
        return 0 if response.ok else 1
    try:
        data = response.json()
    except ValueError:
        print("top-level keys: <not JSON>")
        print(_scrub(body[:1500]))
        return 0 if response.ok else 1
    keys = sorted(data.keys()) if isinstance(data, dict) else []
    print(f"top-level keys: {keys}")
    print(_scrub(json.dumps(data, indent=2, ensure_ascii=False)[:1500]))
    return 0 if response.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
