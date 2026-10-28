"""Audio preparation for Muse Voice Transcribe.

Converts any input audio to 16 kHz mono 16-bit PCM WAV with the ffmpeg
binary bundled in imageio-ffmpeg. No network, no API keys here.
"""

import subprocess
import wave
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from backend.core.errors import HakiScribeError

TARGET_SAMPLE_RATE_HZ = 16000
MAX_DURATION_SEC = 600
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
FFMPEG_TIMEOUT_SEC = 300


class AudioPrepError(HakiScribeError):
    """Raised when audio cannot be prepared for transcription."""

    code = "audio_prep_failed"


def wav_duration_sec(path: str | Path) -> float:
    """Return the duration of a WAV file in seconds (stdlib only)."""
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def prepare_wav(src: str | Path, dst: str | Path) -> Path:
    """Convert audio to 16 kHz mono 16-bit PCM WAV at dst; return dst.

    Raises AudioPrepError on conversion failure, duration over 600 seconds,
    or output over 32 MB.
    """
    src_path, dst_path = Path(src), Path(dst)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [
                get_ffmpeg_exe(),
                "-y",
                "-i",
                str(src_path),
                "-ar",
                str(TARGET_SAMPLE_RATE_HZ),
                "-ac",
                "1",
                "-sample_fmt",
                "s16",
                str(dst_path),
            ],
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SEC,
        )
    except FileNotFoundError as exc:
        raise AudioPrepError(f"ffmpeg binary not available: {exc}") from exc
    except subprocess.TimeoutExpired:
        raise AudioPrepError("ffmpeg conversion timed out") from None
    if proc.returncode != 0:
        raise AudioPrepError(f"ffmpeg conversion failed: {proc.stderr[-500:]}")
    if not dst_path.is_file():
        raise AudioPrepError("ffmpeg produced no output file")
    try:
        duration = wav_duration_sec(dst_path)
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioPrepError(f"converted file is not valid WAV: {exc}") from exc
    if duration > MAX_DURATION_SEC:
        raise AudioPrepError(
            f"audio too long: {duration:.1f}s exceeds {MAX_DURATION_SEC}s"
        )
    size = dst_path.stat().st_size
    if size > MAX_OUTPUT_BYTES:
        raise AudioPrepError(
            f"converted file too large: {size} bytes exceeds 32 MB"
        )
    return dst_path


def ffmpeg_available() -> bool:
    """True when the bundled ffmpeg executable exists (no audio needed)."""
    try:
        return Path(get_ffmpeg_exe()).is_file()
    except Exception:
        return False
