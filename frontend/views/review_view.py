"""Review Desk step: session summary and flag preview (interactive preview)."""

import streamlit as st

from backend.services.workflow_service import WorkflowSnapshot
from frontend import state
from frontend.components.transcript_card import LOW_CONFIDENCE_THRESHOLD


def render(snapshot: WorkflowSnapshot | None) -> None:
    """Render the Review Desk preview from the workflow snapshot."""
    st.header("3. Review Desk")
    st.info("Interactive preview - backend workflow connects in the next backend step.")
    review_recording = snapshot.recording if snapshot is not None else None
    review_segments = list(snapshot.segments) if snapshot is not None else []
    if not review_recording:
        st.info("No recording yet. Upload a synthetic hearing first.")
        if st.button("Go to Upload", type="primary", key="review_empty_go_upload"):
            st.session_state[state.CURRENT_STEP] = "upload"
            st.rerun()
    elif not review_segments:
        st.info("No transcript yet. Transcribe the recording first.")
        if st.button("Go to Transcribe", type="primary", key="review_empty_go_transcribe"):
            st.session_state[state.CURRENT_STEP] = "transcribe"
            st.rerun()
    else:
        st.subheader("Session summary")
        low_confidence = [
            segment
            for segment in review_segments
            if segment["confidence"] is not None
            and float(segment["confidence"]) < LOW_CONFIDENCE_THRESHOLD
        ]
        unknown_speaker = [
            segment
            for segment in review_segments
            if (segment["speaker"] or "UNKNOWN") == "UNKNOWN"
        ]
        draft_count = len(st.session_state.get(state.DRAFT_EDITS, {}))
        metric_total, metric_low, metric_speakers, metric_drafts = st.columns(4)
        metric_total.metric("Total segments", len(review_segments))
        metric_low.metric("Low confidence segments", len(low_confidence))
        metric_speakers.metric(
            "Speakers detected",
            len({segment["speaker"] for segment in review_segments}),
        )
        metric_drafts.metric("Draft edits (local count)", draft_count)
        st.divider()
        st.subheader("Flag preview")
        st.caption("Preview only — backend flag workflow connects in the next backend step.")
        flagged = {}
        for segment in review_segments:
            reasons = []
            if (segment["speaker"] or "UNKNOWN") == "UNKNOWN":
                reasons.append("UNKNOWN speaker")
            if segment["confidence"] is not None and float(segment["confidence"]) < LOW_CONFIDENCE_THRESHOLD:
                reasons.append(f"low confidence {float(segment['confidence']):.0%}")
            if reasons:
                flagged[segment["id"]] = (segment, reasons)
        if not flagged:
            st.info("No flags in this preview — every segment looks clean.")
        for seg_id in sorted(flagged, key=lambda i: flagged[i][0]["idx"]):
            segment, reasons = flagged[seg_id]
            text = f"Segment {segment['idx']} ({segment['speaker']}): " + "; ".join(reasons)
            if (segment["speaker"] or "UNKNOWN") == "UNKNOWN":
                st.error(text)
            else:
                st.warning(text)
            if st.button("Select", key=f"flag_select_{seg_id}"):
                st.session_state[state.SELECTED_SEGMENT_IDX] = segment["idx"]
                st.session_state[state.CURRENT_STEP] = "transcribe"
                st.rerun()
        st.divider()
        st.subheader("Actions")
        if st.button("Save Correction to History (Backend Next)", type="secondary"):
            st.info("Correction history saving is the next backend step. Draft edits stay local for now.")
