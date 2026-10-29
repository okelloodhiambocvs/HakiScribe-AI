"""Local audio capture: microphone and paced-file sources.

sounddevice and any PortAudio interaction live ONLY in this module.
FileSource resamples any PCM WAV to the 24 kHz mono int16 wire format
with pure-Python linear interpolation (no new dependencies).
"""

import abc
import asyncio
import struct
import time
import wave
from pathlib import Path

from backend.core.errors import AudioCaptureError

SAMPLE_RATE = 24000
CHANNELS = 1
BLOCK_FRAMES = 1920
BLOCK_BYTES = BLOCK_FRAMES * 2  # int16 mono
BLOCK_SECONDS = BLOCK_FRAMES / SAMPLE_RATE  # 0.08


class AudioSource(abc.ABC):
    """Frame source lifecycle: start() then frames() until stop()."""

    @abc.abstractmethod
    def start(self) -> None:
        """Open the source. SoundDeviceSource needs a running loop."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Close the source; frames() ends promptly afterwards."""

    @abc.abstractmethod
    async def frames(self):
        """Yield 80 ms (3840 byte) int16 mono blocks until stopped."""
        yield b""  # pragma: no cover - interface only


class SoundDeviceSource(AudioSource):
    """Microphone capture at 24 kHz mono int16 via sounddevice.

    A full queue drops the oldest frame so the stream stays current.
    """

    def __init__(self, device=None, samplerate=SAMPLE_RATE,
                 blocksize=BLOCK_FRAMES):
        self.device = device
        self.samplerate = samplerate
        self.blocksize = blocksize
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=250)
        self._stream = None
        self._loop = None
        self._stopped = False

    def start(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise AudioCaptureError(
                "sounddevice is not installed; install it with "
                "'pip install sounddevice' to use the microphone"
            ) from exc
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            raise AudioCaptureError(
                "microphone start needs a running session"
            ) from exc
        self._stopped = False
        try:
            self._stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=CHANNELS,
                dtype="int16",
                blocksize=self.blocksize,
                device=self.device,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            raise AudioCaptureError(
                f"cannot open microphone (device {self.device!r}): {exc}"
            ) from exc

    def _callback(self, indata, frames, time_info, status):
        if self._stopped:
            return
        try:
            data = bytes(indata)
        except Exception:
            return
        if len(data) < BLOCK_BYTES:
            data += b"\x00" * (BLOCK_BYTES - len(data))
        elif len(data) > BLOCK_BYTES:
            data = data[:BLOCK_BYTES]
        loop = self._loop
        if loop is None:
            return

        def _deliver():
            try:
                self._queue.put_nowait(data)
            except asyncio.QueueFull:
                # Drop the oldest frame so the stream stays current.
                # Only non-blocking calls: the audio callback must
                # never wait, and the queue stays bounded.
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self._queue.put_nowait(data)
                except asyncio.QueueFull:
                    pass

        try:
            loop.call_soon_threadsafe(_deliver)
        except RuntimeError:
            pass

    async def frames(self):
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                return
            yield chunk

    def stop(self) -> None:
        self._stopped = True
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        loop = self._loop
        if loop is None:
            return

        def _finish():
            try:
                while True:
                    self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

        try:
            loop.call_soon_threadsafe(_finish)
        except RuntimeError:
            pass


def list_input_devices() -> list[dict]:
    """List microphone devices as [{index, name}]."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise AudioCaptureError(
            "sounddevice is not installed; install it with "
            "'pip install sounddevice' to list microphones"
        ) from exc
    try:
        devices = sd.query_devices()
    except Exception as exc:
        raise AudioCaptureError(f"cannot query audio devices: {exc}") from exc
    return [
        {"index": index, "name": device["name"]}
        for index, device in enumerate(devices)
        if device.get("max_input_channels", 0) > 0
    ]


class FileSource(AudioSource):
    """Paced WAV file source for probes and tests.

    Any PCM WAV (8/16-bit, mono/stereo, any rate) converts to 24 kHz
    mono int16 and yields 3840-byte blocks in real time unless
    realtime=False. A short final block is zero-padded to full size.
    Pacing follows an absolute monotonic schedule so send overhead
    never accumulates into drift.
    """

    def __init__(self, path: str | Path, realtime: bool = True):
        self.path = Path(path)
        self.realtime = realtime
        self._stopped = False

    def start(self) -> None:
        if not self.path.is_file():
            raise AudioCaptureError(f"audio file not found: {self.path}")
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def frames(self):
        pcm = self._load_wire_pcm()
        started = time.monotonic()
        for index, offset in enumerate(range(0, len(pcm), BLOCK_BYTES)):
            if self._stopped:
                return
            block = pcm[offset : offset + BLOCK_BYTES]
            if len(block) < BLOCK_BYTES:
                block += b"\x00" * (BLOCK_BYTES - len(block))
            if self.realtime:
                # Absolute schedule: frame n is due at started +
                # (n+1) frame durations, so read/send overhead never
                # accumulates into drift. Late frames go out at once;
                # the delay is never negative.
                delay = (
                    started
                    + (index + 1) * BLOCK_SECONDS
                    - time.monotonic()
                )
                if delay > 0:
                    await asyncio.sleep(delay)
            if self._stopped:
                return
            yield block

    def _load_wire_pcm(self) -> bytes:
        try:
            with wave.open(str(self.path), "rb") as wav_file:
                if wav_file.getcomptype() != "NONE":
                    raise AudioCaptureError(
                        f"unsupported WAV encoding in {self.path.name}: "
                        f"{wav_file.getcomptype()}"
                    )
                channels = wav_file.getnchannels()
                width = wav_file.getsampwidth()
                rate = wav_file.getframerate()
                raw = wav_file.readframes(wav_file.getnframes())
        except wave.Error as exc:
            raise AudioCaptureError(
                f"cannot read WAV file {self.path}: {exc}"
            ) from exc
        if width not in (1, 2):
            raise AudioCaptureError(
                f"unsupported sample width in {self.path.name}: {width} bytes"
            )
        if channels not in (1, 2):
            raise AudioCaptureError(
                f"unsupported channel count in {self.path.name}: {channels}"
            )
        if rate <= 0:
            raise AudioCaptureError(
                f"unsupported sample rate in {self.path.name}: {rate}"
            )
        samples = self._to_mono_float(raw, channels, width)
        target_len = int(round(len(samples) * SAMPLE_RATE / rate))
        return self._resample_pack(samples, target_len)

    @staticmethod
    def _to_mono_float(raw: bytes, channels: int, width: int) -> list[float]:
        count = len(raw) // (channels * width)
        if width == 2:
            values = struct.unpack(f"<{count * channels}h", raw[: count * channels * 2])
            scaled = [value / 32768.0 for value in values]
        else:
            values = struct.unpack(f"<{count * channels}B", raw[: count * channels])
            scaled = [(value - 128) / 128.0 for value in values]
        if channels == 1:
            return scaled
        return [
            (scaled[i] + scaled[i + 1]) / 2.0
            for i in range(0, len(scaled) - 1, 2)
        ]

    @staticmethod
    def _resample_pack(samples: list[float], target_len: int) -> bytes:
        if not samples or target_len <= 0:
            return b""
        if target_len == 1 or len(samples) == 1:
            positions = [0.0] * target_len
        else:
            step = (len(samples) - 1) / (target_len - 1)
            positions = [index * step for index in range(target_len)]
        packed = bytearray()
        last = len(samples) - 1
        for position in positions:
            low = int(position)
            high = min(low + 1, last)
            fraction = position - low
            value = samples[low] * (1 - fraction) + samples[high] * fraction
            packed += struct.pack(
                "<h", max(-32768, min(32767, int(round(value * 32767))))
            )
        return bytes(packed)
