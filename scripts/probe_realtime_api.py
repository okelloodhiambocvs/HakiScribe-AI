"""Stream a WAV to Meta's realtime endpoint at real-time pace (debug tool).

Usage: python scripts/probe_realtime_api.py <wav_file>

Prints each event type and text, ending with a turn/speaker summary.
Never prints the API key. Exits non-zero on failure.
"""

import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.core import config  # noqa: E402
from backend.core.errors import HakiScribeError  # noqa: E402
from backend.integrations.audio_capture import FileSource  # noqa: E402
from backend.integrations.meta.realtime_transcribe import RealtimeClient  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: probe_realtime_api.py <wav_file>")
        return 2
    if not config.is_configured():
        print("error: META_API_KEY is not set; cannot probe the realtime API")
        return 1
    return asyncio.run(_probe(Path(argv[1])))


async def _probe(path: Path) -> int:
    events: list[dict] = []

    def on_event(event) -> None:
        events.append(
            {
                "type": event.type,
                "turn_id": event.turn_id,
                "text": event.text,
                "speaker": event.speaker,
            }
        )
        line = f"event: {event.type}"
        if event.turn_id is not None:
            line += f" turn={event.turn_id}"
        if event.speaker:
            line += f" speaker={event.speaker}"
        if event.text:
            line += f" text={event.text[:120]}"
        print(line, flush=True)

    source = FileSource(path, realtime=True)
    client = RealtimeClient(
        api_key=config.get_meta_key(),
        model=config.META_VOICE_MODEL,
        mode="DIARIZATION",
        language_bias=config.get_language_bias(),
        keywords=config.get_keywords(),
        on_event=on_event,
    )
    print(f"streaming {path} to the realtime endpoint ...", flush=True)
    try:
        source.start()
        summary = await client.run(source.frames())
    except HakiScribeError as exc:
        print(f"error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("stopped.")
        return 1
    finally:
        source.stop()
    turns = [item for item in events if item["type"] == "speechComplete"]
    speakers = sorted({item["speaker"] for item in events if item["speaker"]})
    print(
        f"summary: {len(turns)} turns, "
        f"speakers={speakers or ['none']}, "
        f"frames_sent={summary['frames_sent']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
