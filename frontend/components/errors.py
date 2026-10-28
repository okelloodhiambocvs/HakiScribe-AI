"""Safe error rendering: coded messages, generic fallback, no tracebacks."""

import logging

import streamlit as st

from backend.core.errors import HakiScribeError

logger = logging.getLogger(__name__)

_INFO_CODES = frozenset({"already_transcribed", "transcription_in_progress"})
_WARNING_CODES = frozenset({"transcription_locked"})


def show_error(exc: BaseException) -> None:
    """Render any exception safely in the UI. Never shows a traceback."""
    if isinstance(exc, HakiScribeError):
        if exc.code in _INFO_CODES:
            st.info(exc.user_message)
        elif exc.code in _WARNING_CODES:
            st.warning(exc.user_message)
        else:
            st.error(exc.user_message)
    elif isinstance(exc, ValueError):
        st.error(str(exc))
    else:
        logger.exception("unexpected frontend error: %s", type(exc).__name__)
        st.error("Something went wrong. Please try again.")
