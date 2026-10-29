"""Shared error contract: coded, user-safe backend exceptions.

Every error carries a short machine-readable code and a plain-English
user_message with no stack traces and no secrets. Frontend code renders
these via frontend.components.errors.
"""

from __future__ import annotations


class HakiScribeError(Exception):
    """Base error for expected backend failures."""

    code: str = "hakiscribe_error"

    def __init__(self, message: str = "", *, user_message: str | None = None) -> None:
        super().__init__(message)
        self.user_message = (
            user_message or message or "Something went wrong. Please try again."
        )


class UploadValidationError(HakiScribeError, ValueError):
    """An upload failed validation (stays catchable as ValueError)."""

    code = "upload_validation_failed"


class EditConflictError(HakiScribeError, ValueError):
    """A segment changed since the reviewer opened it (stale write)."""

    code = "edit_conflict"


class AudioCaptureError(HakiScribeError):
    """Microphone or audio-file capture failed (exact message shown)."""

    code = "audio_capture_failed"


class RealtimeError(HakiScribeError):
    """Realtime transcription failed (exact message shown, key scrubbed)."""

    code = "realtime_failed"

    def __init__(
        self,
        message: str = "",
        *,
        user_message: str | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message, user_message=user_message)
        self.error_code = error_code
