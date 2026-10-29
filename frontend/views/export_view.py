"""Draft & Evaluation step: DOCX draft generation and metrics (service-backed)."""

import streamlit as st

from backend.services import workflow_service
from backend.services.workflow_service import WorkflowSnapshot
from frontend import state
from frontend.components.errors import show_error

_EXPORT_MIME = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document"
)


def _render_metric(name: str, envelope: dict) -> None:
    """Render one metric envelope or its not-available reason."""
    if not envelope["values"]:
        st.write(f"{name}: Not available: {envelope['reason']}")
        return
    parts = ", ".join(
        f"{key}={value}" for key, value in envelope["values"].items()
    )
    st.write(f"{name}: {parts} (n={envelope['sample_size']})")
    st.caption(f"How computed: {envelope['how_computed']}")


def render(snapshot: WorkflowSnapshot | None, reviewer: str) -> None:
    """Render draft generation, download, and the evaluation panel."""
    has_recording = snapshot is not None
    has_transcript = bool(snapshot and snapshot.transcript_status == "present")
    st.header("4. Draft & Evaluation")
    if not has_recording:
        st.info("No recording yet. Upload a synthetic hearing first.")
        if st.button("Go to Upload", type="primary", key="export_empty_go_upload"):
            st.session_state[state.CURRENT_STEP] = "upload"
            st.rerun()
        return
    if not has_transcript:
        st.info("No transcript yet. Transcribe the recording first.")
        if st.button("Go to Transcribe", type="primary", key="export_empty_go_transcribe"):
            st.session_state[state.CURRENT_STEP] = "transcribe"
            st.rerun()
        return

    has_reviewer = bool(reviewer.strip())
    st.warning(
        "Draft only \u2014 this document is not certified. "
        "AI proposes, HUMAN REVIEWS."
    )
    if not has_reviewer:
        st.warning("Enter your reviewer name in the sidebar to generate a draft.")

    recording_id = snapshot.recording["id"]
    try:
        metrics = workflow_service.evaluate_recording(recording_id)
        unresolved = workflow_service.get_unresolved(recording_id)
        latest = workflow_service.get_latest_export(recording_id)
    except Exception as exc:
        show_error(exc)
        return

    st.subheader("Evaluation")
    _render_metric("Human changes (AI vs reviewed)", metrics["ai_vs_reviewed"])
    _render_metric("Accuracy vs reference", metrics["reference"])
    _render_metric("Speaker attribution", metrics["speaker"])
    _render_metric("Traceability", metrics["traceability"])
    _render_metric("Review time", metrics["review_time"])
    st.write(f"Unresolved flags: {len(unresolved)}")

    if unresolved:
        st.warning(
            f"Exporting with {len(unresolved)} unresolved flags. "
            "Every issue stays listed in the draft."
        )
        for flag in unresolved:
            st.write(f"Segment {flag['segment_idx']}: {flag['message']}")

    st.subheader("Draft document")
    notice = st.session_state.pop(state.EXPORT_NOTICE, None)
    if notice:
        st.success(f"Draft saved: {notice}")
    if st.button(
        "Generate draft DOCX",
        type="primary",
        key="generate_draft_docx",
        disabled=not has_reviewer,
    ):
        try:
            result = workflow_service.generate_draft_docx(
                recording_id, reviewer.strip()
            )
        except Exception as exc:
            show_error(exc)
        else:
            st.session_state[state.EXPORT_NOTICE] = result["docx_filename"]
            st.rerun()
    if latest is None:
        st.info("No draft yet \u2014 press Generate draft DOCX.")
        return
    docx_path = workflow_service.export_file_path(latest["docx_filename"])
    if not docx_path.is_file():
        st.info("The latest draft file is missing \u2014 generate it again.")
        return
    st.download_button(
        "Download DOCX draft",
        data=docx_path.read_bytes(),
        file_name=latest["docx_filename"],
        mime=_EXPORT_MIME,
        key="download_draft_docx",
    )
