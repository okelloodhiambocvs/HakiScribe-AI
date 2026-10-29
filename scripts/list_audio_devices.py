"""Print microphone input devices (debug tool).

Usage: python scripts/list_audio_devices.py
Exits non-zero with a friendly message when sounddevice is missing.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.core.errors import AudioCaptureError  # noqa: E402
from backend.integrations.audio_capture import list_input_devices  # noqa: E402


def main() -> int:
    try:
        devices = list_input_devices()
    except AudioCaptureError as exc:
        print(f"error: {exc}")
        return 1
    if not devices:
        print("No microphone input devices found.")
        return 0
    for device in devices:
        print(f"{device['index']}: {device['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
