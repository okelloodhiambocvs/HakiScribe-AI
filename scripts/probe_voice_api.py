"""Probe Muse Voice Transcribe once and dump the raw response (debug tool).

Usage: python scripts/probe_voice_api.py <audio_file> [--mode MODE]
       [--language-bias LANG ...] [--keywords-file PATH]
Prints HTTP status, top-level JSON keys, turn stats, and the first 1500
characters of the pretty-printed response. Never prints the API key.
Exits non-zero on failure.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import requests

from backend.core.config import (
    META_VOICE_MODEL,
    VOICE_MODES,
    get_api_base,
    get_keywords,
    get_meta_key,
    is_configured,
)
from backend.integrations.meta.audio_prep import prepare_wav
from backend.integrations.meta.voice_transcribe import (
    build_request_payload,
    html_title,
    is_html_body,
)


def _scrub(text: str) -> str:
    key = get_meta_key()
    if key:
        text = text.replace(key, "[REDACTED]")
    return text


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="probe_voice_api.py",
        description="Probe Muse Voice Transcribe once.",
    )
    parser.add_argument("audio_file")
    parser.add_argument(
        "--mode", default=None,
        help=f"voice mode (default: config, one of {', '.join(VOICE_MODES)})",
    )
    parser.add_argument(
        "--language-bias", action="append", default=None,
        help="languageBias entry; repeat for several (default: config)",
    )
    parser.add_argument(
        "--keywords-file", default=None,
        help="keywords file, one term per line (default: config file)",
    )
    return parser.parse_args(argv[1:])


def _print_turn_stats(data: dict) -> None:
    turns = data.get("turns")
    if not isinstance(turns, list):
        return
    print(f"turns: {len(turns)}")
    speakers = sorted(
        {str(turn.get("speaker")) for turn in turns
         if isinstance(turn, dict) and turn.get("speaker") is not None}
    )
    print(f"speakers: {speakers if speakers else '<none>'}")
    for turn in turns[:3]:
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("transcript") or "")[:80]
        print(
            f"turn: startMs={turn.get('startMs')} "
            f"endMs={turn.get('endMs')} speaker={turn.get('speaker')} "
            f"text={text!r}"
        )


def main(argv: list[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)
    src = Path(args.audio_file)
    if not src.is_file():
        print(f"audio file not found: {src}", file=sys.stderr)
        return 1
    if not is_configured():
        print("META_API_KEY not configured", file=sys.stderr)
        return 1
    mode = args.mode.upper() if args.mode else None
    if mode is not None and mode not in VOICE_MODES:
        print(
            f"invalid --mode: {args.mode} (use {', '.join(VOICE_MODES)})",
            file=sys.stderr,
        )
        return 2
    try:
        keywords = get_keywords(args.keywords_file) if args.keywords_file else None
        payload = build_request_payload(
            model=META_VOICE_MODEL,
            mode=mode,
            language_bias=args.language_bias,
            keywords=keywords,
        )
        with tempfile.TemporaryDirectory(prefix="hakiscribe-probe-") as tmp_dir:
            wav_path = prepare_wav(src, Path(tmp_dir) / "probe.wav")
            # Same wire shape as voice_transcribe.py (canonical reference).
            url = f"{get_api_base()}/asr/transcribe"
            headers = {"Authorization": f"Bearer {get_meta_key()}"}
            print(f"request URL: {url}")
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
    if isinstance(data, dict):
        _print_turn_stats(data)
    print(_scrub(json.dumps(data, indent=2, ensure_ascii=False)[:1500]))
    return 0 if response.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
