"""Print system health checks; exit non-zero on any FAIL.

Usage: python scripts/check_setup.py
Offline-safe: no network calls. Never prints the API key.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.health_service import check_system  # noqa: E402


def main() -> int:
    lines = []
    failed = False
    for check in check_system():
        lines.append(f"{check.status:4} {check.name}: {check.message}")
        if check.status == "FAIL":
            failed = True
    output = "\n".join(lines)
    print(output)
    key = os.environ.get("META_API_KEY", "")
    if len(key) >= 8 and key in output:
        print("ERROR: API key leaked into output", file=sys.stderr)
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
