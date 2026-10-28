"""HakiScribe-AI V2 Review Desk frontend — Priority 1: Upload and Transcribe.

Streamlit UI only. Every action calls backend services; this module makes no
Meta API calls and touches no database directly.
"""

import streamlit as st

from backend.core.config import is_configured
from backend.services.ingestion_service import validate_and_store_upload
from backend.services.transcription_service import get_transcript, transcribe_recording

CONFIDENCE_THRESHOLD = 0.75


def _format_time_range(start_sec: float, end_sec: float) -> str:
    """Render a segment time range in seconds."""
    return f"{float(start_sec):.1f}s – {float(end_sec):.1f}s"


def _format_confidence(confidence: float | None) -> str:
    """Render confidence as a percentage, or n/a when missing."""
    if confidence is None:
        return "n/a"
    return f"{float(confidence) * 100:.0f}%"


st.set_page_config(page_title="HakiScribe-AI Review Desk", layout="wide")

st.title("HakiScribe-AI")
st.subheader("Clarity in Every Proceeding")
st.warning(
    "Synthetic demo only. AI proposes, HUMAN REVIEWS. "
    "This is not an official court record."
)

reviewer = st.sidebar.text_input("Reviewer name", value="")
st.sidebar.markdown(
    "**Workflow**\n"
    "1. Upload\n"
    "2. Transcribe\n"
    "3. Review Desk (next)\n"
    "4. Draft Export (next)"
)

if "recording_id" not in st.session_state:
    st.session_state["recording_id"] = None
if "recording" not in st.session_state:
    st.session_state["recording"] = None
if "transcript_status" not in st.session_state:
    st.session_state["transcript_status"] = None

st.header("1. Upload synthetic hearing")
upload_box = st.container()
uploaded = upload_box.file_uploader(
    "Choose a synthetic hearing file", type=["mp3", "wav", "m4a"]
)
attested = upload_box.checkbox(
    "I confirm this is a synthetic demo recording (no real litigants)."
)
if upload_box.button("Upload and Validate Recording"):
    if uploaded is None:
        st.error("Choose an audio file first.")
    elif not attested:
        st.error("Tick the synthetic attestation checkbox to continue.")
    elif not reviewer.strip():
        st.error("Enter your reviewer name in the sidebar first.")
    else:
        try:
            recording = validate_and_store_upload(
                uploaded.name, uploaded.getvalue(), reviewer,
                synthetic_attestation=True,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state["recording_id"] = recording["id"]
            st.session_state["recording"] = recording
            st.session_state["transcript_status"] = None
            st.success(
                f"Stored {recording['filename']} "
                f"({recording['size_bytes']} bytes, "
                f"sha256 {recording['sha256'][:12]}…)."
            )

recording = st.session_state["recording"]
if recording is not None:
    st.header("Recording")
    meta_left, meta_right = st.columns(2)
    meta_left.write(f"File: {recording['filename']}")
    meta_left.write(f"Size: {recording['size_bytes']} bytes")
    meta_right.write(f"Uploaded by: {recording['uploaded_by']}")
    meta_right.write(f"SHA256: {recording['sha256'][:16]}…")
    try:
        st.audio(recording["stored_path"])
    except Exception:
        st.info("Audio preview is unavailable for this recording.")

    st.header("2. Transcribe")
    use_mock = st.checkbox(
        "Use mock demo mode (no Meta API call)", value=not is_configured()
    )
    if st.button("Transcribe Recording"):
        try:
            result = transcribe_recording(
                recording["id"], force_mock=use_mock
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state["transcript_status"] = result["status"]

    status = st.session_state["transcript_status"]
    if status == "real":
        st.success("REAL Meta call — Muse Voice Transcribe via Meta Model API.")
    elif isinstance(status, str) and status.startswith("mock"):
        st.info("MOCK synthetic demo — no Meta API call was made.")
    elif status == "already_transcribed":
        st.info("Already transcribed — showing saved segments.")

    segments = get_transcript(recording["id"])
    if segments:
        st.subheader(f"Transcript — {len(segments)} segments")
        for segment in segments:
            card = st.container()
            card.write(
                    f"{_format_time_range(segment['start_sec'], segment['end_sec'])}"
                )
            info_left, info_right, info_third = st.columns(3)
            info_left.write(f"Speaker: {segment['speaker']}")
            info_right.write(f"Confidence: {_format_confidence(segment['confidence'])}")
            info_third.write(f"Language: {segment['language']}")
            card.write(segment["text_current"])
            confidence = segment["confidence"]
            if confidence is not None and float(confidence) < CONFIDENCE_THRESHOLD:
                card.warning("Needs human review")
            details = st.expander(f"Segment {segment['idx']} details")
            details.write(f"Row id: {segment['id']}")
            details.write(f"Original: {segment['text_original']}")
