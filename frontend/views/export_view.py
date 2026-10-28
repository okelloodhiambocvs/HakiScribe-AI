"""Draft & Evaluation step: watermarked draft preview (interactive preview)."""

import streamlit as st

from frontend import state


def render() -> None:
    """Render the Draft & Evaluation preview with empty-state guards."""
    has_recording = st.session_state.get(state.RECORDING_ID) is not None
    has_transcript = st.session_state.get(state.TRANSCRIPT_STATUS) is not None
    st.header("4. Draft & Evaluation")
    st.info("Interactive preview - backend workflow connects in the next backend step.")
    if not has_recording:
        st.info("No recording yet. Upload a synthetic hearing first.")
        if st.button("Go to Upload", type="primary", key="export_empty_go_upload"):
            st.session_state[state.CURRENT_STEP] = "upload"
            st.rerun()
    elif not has_transcript:
        st.info("No transcript yet. Transcribe the recording first.")
        if st.button("Go to Transcribe", type="primary", key="export_empty_go_transcribe"):
            st.session_state[state.CURRENT_STEP] = "transcribe"
            st.rerun()
    else:
        st.markdown(
            '<div class="draft-watermark">'
            "DRAFT - NOT AN OFFICIAL COURT RECORD - HUMAN REVIEWED"
            "</div>",
            unsafe_allow_html=True,
        )
        st.subheader("Original vs Reviewed (preview)")
        eval_box = st.container(border=True)
        eval_wer, eval_cer, eval_changed, eval_flags = eval_box.columns(4)
        eval_wer.metric("Word Error Rate", "—")
        eval_cer.metric("Character Error Rate", "—")
        eval_changed.metric("Segments changed", "—")
        eval_flags.metric("Flags resolved", "—")
        eval_box.caption("Preview placeholders — real scores connect with the backend evaluation step.")
        st.divider()
        st.subheader("Actions")
        if st.button("Generate DOCX Draft (Backend Next)", type="secondary"):
            st.info("DOCX generation connects in the backend step. No file is generated in this preview.")
