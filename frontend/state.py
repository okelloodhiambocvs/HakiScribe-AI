"""Frontend session-state keys (single source of truth) plus initializer."""

import streamlit as st

RECORDING_ID = "recording_id"
RECORDING = "recording"
TRANSCRIPT_STATUS = "transcript_status"
CURRENT_STEP = "current_step"
SELECTED_SEGMENT_IDX = "selected_segment_idx"
SPEAKER_FILTER = "speaker_filter"
SHOW_LOW_CONFIDENCE_ONLY = "show_low_confidence_only"
UPLOAD_NOTICE = "upload_notice"
TRANSCRIPT_SEARCH = "transcript_search"
DRAFT_EDITS = "draft_edits"
HEARING_UPLOAD = "hearing_upload"
TRANSCRIBING = "transcribing"


def init_state() -> None:
    """Initialize default session keys; preserves any preset values."""
    if RECORDING_ID not in st.session_state:
        st.session_state[RECORDING_ID] = None
    if RECORDING not in st.session_state:
        st.session_state[RECORDING] = None
    if TRANSCRIPT_STATUS not in st.session_state:
        st.session_state[TRANSCRIPT_STATUS] = None
    if CURRENT_STEP not in st.session_state:
        st.session_state[CURRENT_STEP] = "upload"
    if SELECTED_SEGMENT_IDX not in st.session_state:
        st.session_state[SELECTED_SEGMENT_IDX] = None
    if SPEAKER_FILTER not in st.session_state:
        st.session_state[SPEAKER_FILTER] = "ALL"
    if SHOW_LOW_CONFIDENCE_ONLY not in st.session_state:
        st.session_state[SHOW_LOW_CONFIDENCE_ONLY] = False
