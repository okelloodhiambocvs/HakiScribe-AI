"""Upload step: synthetic hearing validation and storage card."""

import streamlit as st

from backend.services import workflow_service
from backend.services.workflow_service import WorkflowSnapshot
from frontend import state
from frontend.components.errors import show_error
from frontend.components.privacy import PRIVACY_NOTICE


def _format_file_size(num_bytes: int) -> str:
    """Render a byte count as B, KB, or MB."""
    size = float(num_bytes or 0)
    if size < 1024:
        return f"{size:.0f} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _clear_upload_state() -> None:
    """Clear upload-related session state (disk and database untouched)."""
    for key in (
        state.RECORDING_ID,
        state.SNAPSHOT,
        state.SELECTED_SEGMENT_IDX,
        state.HEARING_UPLOAD,
        state.UPLOAD_NOTICE,
        state.STALE_NOTICE,
        state.TRANSCRIPT_WARNING,
    ):
        st.session_state.pop(key, None)
    st.session_state[state.CURRENT_STEP] = "upload"


def render(reviewer: str, snapshot: WorkflowSnapshot | None) -> None:
    """Render the upload card (shared by the upload and transcribe steps)."""
    has_recording = snapshot is not None
    st.header("Step 1 - Upload Synthetic Hearing Recording")
    upload_box = st.container(border=True)
    uploaded = upload_box.file_uploader(
        "Choose a synthetic hearing file",
        type=["mp3", "wav", "m4a", "aac", "adts", "ogg", "opus", "webm"],
        key=state.HEARING_UPLOAD,
    )
    upload_box.caption(
        "MP3, WAV, M4A, AAC, ADTS, OGG, OPUS, WEBM - synthetic recordings only"
    )
    upload_box.info(PRIVACY_NOTICE)
    attested = upload_box.checkbox(
        "I confirm this is a synthetic demo recording with no real litigants"
    )
    if uploaded is None and not has_recording:
        upload_box.info("No recording yet.")
        if upload_box.button("Load demo recording", type="primary", key="load_demo_recording"):
            if not reviewer.strip():
                upload_box.warning("Add a reviewer name first, then load the demo.")
            else:
                try:
                    recording = workflow_service.load_demo(reviewer)
                except Exception as exc:
                    show_error(exc)
                else:
                    st.session_state[state.RECORDING_ID] = recording["id"]
                    st.session_state.pop(state.TRANSCRIPT_WARNING, None)
                    st.session_state[state.UPLOAD_NOTICE] = {
                        "filename": recording["filename"],
                        "size_bytes": recording["size_bytes"],
                        "sha256": recording["sha256"],
                    }
                    st.session_state[state.CURRENT_STEP] = "transcribe"
                    st.rerun()
    elif uploaded is not None and not has_recording:
        upload_size = getattr(uploaded, "size", None)
        if upload_size is None:
            try:
                upload_size = len(uploaded.getvalue())
            except Exception:
                upload_size = 0
        upload_box.info(
            f"Selected: {uploaded.name} ({_format_file_size(upload_size)})"
        )
    can_upload = (
        uploaded is not None and attested and bool(reviewer.strip())
    )
    if not can_upload:
        upload_box.warning(
            "Add a reviewer name, choose a file, and tick the attestation to enable upload."
        )
    btn_upload, btn_clear = upload_box.columns(2)
    if btn_upload.button(
        "Upload and Validate Recording", type="primary", disabled=not can_upload
    ):
        with st.spinner("Validating and storing synthetic recording..."):
            try:
                recording = workflow_service.upload_recording(
                    uploaded.name, uploaded.getvalue(), reviewer, attested
                )
            except Exception as exc:
                show_error(exc)
            else:
                st.session_state[state.RECORDING_ID] = recording["id"]
                st.session_state.pop(state.TRANSCRIPT_WARNING, None)
                st.session_state[state.UPLOAD_NOTICE] = {
                    "filename": recording["filename"],
                    "size_bytes": recording["size_bytes"],
                    "sha256": recording["sha256"],
                }
                st.session_state[state.CURRENT_STEP] = "transcribe"
                st.rerun()
    btn_clear.button("Clear Upload", type="secondary", on_click=_clear_upload_state)
