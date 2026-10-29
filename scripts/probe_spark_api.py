"""Probe Muse Spark review in each API style (debug tool).

Usage: python scripts/probe_spark_api.py
Sends "Reply with the single word OK" via chat, messages, and responses,
printing status, resolved URL, and the first 300 reply characters per
style. Never prints the API key. Exits 0 when at least one style works.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.core.config import is_configured
from backend.integrations.meta.spark_client import SPARK_STYLES, complete

_PROBE_SYSTEM = "You are a connectivity probe."
_PROBE_USER = "Reply with the single word OK"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: probe_spark_api.py", file=sys.stderr)
        return 2
    if not is_configured():
        print("META_API_KEY not configured", file=sys.stderr)
        return 1
    worked = False
    for style in SPARK_STYLES:
        try:
            result = complete(_PROBE_SYSTEM, _PROBE_USER, style=style)
        except Exception as exc:
            print(f"style: {style}\n  ERROR: {exc}")
            continue
        worked = True
        print(
            f"style: {style}\n"
            f"  URL: {result['url']}\n"
            f"  HTTP status: {result['http_status']}\n"
            f"  reply: {result['text'][:300]}"
        )
    return 0 if worked else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
