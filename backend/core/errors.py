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
