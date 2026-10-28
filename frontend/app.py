"""HakiScribe-AI V2 Review Desk frontend — Priority 1: Upload and Transcribe.

Streamlit UI only. Every action calls backend services; this module makes no
Meta API calls and touches no database directly.
"""

import streamlit as st

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.core.config import is_configured
from backend.services.ingestion_service import validate_and_store_upload
from backend.integrations.meta.audio_prep import AudioPrepError
from backend.services.transcription_service import (
    TranscriptionError,
    get_transcript,
    transcribe_recording,
)
from frontend.components.stepper import render_stepper
from frontend.components.transcript_card import render_segment_card
from frontend.theme import apply_theme

CONFIDENCE_THRESHOLD = 0.75


def _format_time_range(start_sec: float, end_sec: float) -> str:
    """Render a segment time range in seconds."""
    return f"{float(start_sec):.1f}s – {float(end_sec):.1f}s"


def _format_confidence(confidence: float | None) -> str:
    """Render confidence as a percentage, or n/a when missing."""
    if confidence is None:
        return "n/a"
    return f"{float(confidence) * 100:.0f}%"


def _format_file_size(num_bytes: int) -> str:
    """Render a byte count as B, KB, or MB."""
    size = float(num_bytes or 0)
    if size < 1024:
        return f"{size:.0f} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _reset_draft_edit(segment_id: int) -> None:
    """Drop one segment's UI draft and its widget state (database untouched)."""
    drafts = st.session_state.get("draft_edits", {})
    drafts.pop(segment_id, None)
    st.session_state.pop(f"draft_edit_{segment_id}", None)


def _clear_upload_state() -> None:
    """Clear upload-related session state (disk and database untouched)."""
    for key in (
        "recording_id",
        "recording",
        "transcript_status",
        "selected_segment_idx",
        "hearing_upload",
        "upload_notice",
    ):
        st.session_state.pop(key, None)
    st.session_state["current_step"] = "upload"


st.set_page_config(page_title="HakiScribe-AI Review Desk", layout="wide")
apply_theme()

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
if "current_step" not in st.session_state:
    st.session_state["current_step"] = "upload"
if "selected_segment_idx" not in st.session_state:
    st.session_state["selected_segment_idx"] = None
if "speaker_filter" not in st.session_state:
    st.session_state["speaker_filter"] = "ALL"
if "show_low_confidence_only" not in st.session_state:
    st.session_state["show_low_confidence_only"] = False

render_stepper(st.session_state["current_step"])

nav_upload, nav_transcribe, nav_review, nav_export = st.columns(4)
if nav_upload.button("Upload"):
    st.session_state["current_step"] = "upload"
    st.rerun()
if nav_transcribe.button("Transcribe"):
    st.session_state["current_step"] = "transcribe"
    st.rerun()
if nav_review.button("Review Desk"):
    st.session_state["current_step"] = "review"
    st.rerun()
if nav_export.button("Draft & Evaluation"):
    st.session_state["current_step"] = "export"
    st.rerun()

st.divider()

step = st.session_state["current_step"]

notice = st.session_state.get("upload_notice")
if notice:
    st.success("Recording validated and stored.")
    st.info(
        f"File: {notice['filename']} | "
        f"Size: {notice['size_bytes']} bytes | "
        f"SHA256: {notice['sha256'][:12]}…"
    )
    del st.session_state["upload_notice"]

if step in ("upload", "transcribe"):
    st.header("Step 1 - Upload Synthetic Hearing Recording")
    upload_box = st.container(border=True)
    uploaded = upload_box.file_uploader(
        "Choose a synthetic hearing file",
        type=["mp3", "wav", "m4a", "aac", "adts", "ogg", "opus", "webm"],
        key="hearing_upload",
    )
    upload_box.caption(
        "MP3, WAV, M4A, AAC, ADTS, OGG, OPUS, WEBM - synthetic recordings only"
    )
    attested = upload_box.checkbox(
        "I confirm this is a synthetic demo recording with no real litigants"
    )
    has_recording = st.session_state.get("recording_id") is not None
    if uploaded is None and not has_recording:
        upload_box.info(
            "No recording yet. Upload a short synthetic hearing, "
            "for example CR 123/2026 read from demo-data/synthetic."
        )
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
                recording = validate_and_store_upload(
                    uploaded.name, uploaded.getvalue(), reviewer,
                    synthetic_attestation=True,
                )
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                st.error("Upload failed unexpectedly. Please try a different file.")
            else:
                st.session_state["recording_id"] = recording["id"]
                st.session_state["recording"] = recording
                st.session_state["transcript_status"] = None
                st.session_state["upload_notice"] = {
                    "filename": recording["filename"],
                    "size_bytes": recording["size_bytes"],
                    "sha256": recording["sha256"],
                }
                st.session_state["current_step"] = "transcribe"
                st.rerun()
    btn_clear.button("Clear Upload", type="secondary", on_click=_clear_upload_state)

recording = st.session_state["recording"]
if recording is not None and step in ("upload", "transcribe"):
    st.divider()
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
        except (ValueError, TranscriptionError, AudioPrepError) as exc:
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
        st.info(
            "Original AI text is preserved. Draft edits in this UI preview "
            "are not yet written to the correction history."
        )
        active_filter = st.session_state.get("speaker_filter", "ALL")
        filter_cols = st.columns(7)
        for column, speaker in zip(
            filter_cols,
            ["ALL", "MAGISTRATE", "PROSECUTOR", "ADVOCATE", "ACCUSED", "COMPLAINANT", "WITNESS_PW1"],
        ):
            if column.button(
                speaker,
                type="primary" if speaker == active_filter else "secondary",
                key=f"speaker_filter_{speaker}",
            ):
                st.session_state["speaker_filter"] = speaker
                st.rerun()
        st.session_state["show_low_confidence_only"] = st.checkbox(
            "Show low confidence only (<0.75)",
            value=st.session_state.get("show_low_confidence_only", False),
        )
        st.session_state["transcript_search"] = st.text_input(
            "Search transcript",
            value=st.session_state.get("transcript_search", ""),
        )
        query = st.session_state["transcript_search"].strip().lower()
        low_only = st.session_state["show_low_confidence_only"]
        speaker_filter = st.session_state["speaker_filter"]
        filtered = [
            segment
            for segment in segments
            if (speaker_filter == "ALL" or segment["speaker"] == speaker_filter)
            and (
                not low_only
                or (
                    segment["confidence"] is not None
                    and float(segment["confidence"]) < CONFIDENCE_THRESHOLD
                )
            )
            and (not query or query in (segment["text_current"] or "").lower())
        ]
        st.caption(f"Showing {len(filtered)} of {len(segments)} segments")
        st.caption("Listen buttons preview selection only; precise audio seeking connects later.")
        selected_idx = st.session_state.get("selected_segment_idx")
        for segment in filtered:
            render_segment_card(segment, is_selected=segment["idx"] == selected_idx)
            select_col, listen_col = st.columns(2)
            if select_col.button("Select", key=f"select_{segment['id']}"):
                st.session_state["selected_segment_idx"] = segment["idx"]
                st.rerun()
            if listen_col.button("Listen (Preview)", key=f"listen_{segment['id']}"):
                st.session_state["selected_segment_idx"] = segment["idx"]
                st.rerun()
        selected = next(
            (item for item in segments if item["idx"] == selected_idx), None
        )
        if selected is not None:
            st.subheader("Selected segment")
            st.write(f"speaker: {selected['speaker']}")
            st.write(f"start_sec: {selected['start_sec']}")
            st.write(f"end_sec: {selected['end_sec']}")
            st.write(f"confidence: {selected['confidence']}")
            st.write(f"language: {selected['language']}")
            st.text_area(
                "Original AI text",
                value=selected["text_original"],
                disabled=True,
                key=f"original_text_{selected['id']}",
            )
            drafts = st.session_state.setdefault("draft_edits", {})
            st.text_area(
                "Current text (draft)",
                value=drafts.get(selected["id"], selected["text_current"]),
                key=f"draft_edit_{selected['id']}",
            )
            if st.button("Save Draft Edit (UI only)"):
                drafts[selected["id"]] = st.session_state[f"draft_edit_{selected['id']}"]
                st.success("Draft edit saved locally - backend correction saving connects in the next backend step")
            st.button("Reset Edit", on_click=_reset_draft_edit, args=(selected["id"],))
    else:
        st.info("No transcript yet. Upload and transcribe a synthetic recording first.")
        if st.button("Go to Upload"):
            st.session_state["current_step"] = "upload"
            st.rerun()
elif step == "transcribe":
    st.info("Upload and validate a recording first.")

if step == "review":
    st.header("3. Review Desk")
    st.info("Interactive preview - backend workflow connects in the next backend step.")
    review_recording = st.session_state.get("recording")
    review_segments = (
        get_transcript(review_recording["id"]) if review_recording else []
    )
    if not review_recording or not review_segments:
        st.info("No transcript in this session yet. Upload and transcribe first.")
        if st.button("Go to Upload"):
            st.session_state["current_step"] = "upload"
            st.rerun()
    else:
        st.subheader("Session summary")
        low_confidence = [
            segment
            for segment in review_segments
            if segment["confidence"] is not None
            and float(segment["confidence"]) < CONFIDENCE_THRESHOLD
        ]
        unknown_speaker = [
            segment
            for segment in review_segments
            if (segment["speaker"] or "UNKNOWN") == "UNKNOWN"
        ]
        draft_count = len(st.session_state.get("draft_edits", {}))
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
            if segment["confidence"] is not None and float(segment["confidence"]) < CONFIDENCE_THRESHOLD:
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
                st.session_state["selected_segment_idx"] = segment["idx"]
                st.session_state["current_step"] = "transcribe"
                st.rerun()
        st.divider()
        st.subheader("Actions")
        if st.button("Save Correction to History (Backend Next)", type="secondary"):
            st.info("Correction history saving is the next backend step. Draft edits stay local for now.")

if step == "export":
    st.header("4. Draft & Evaluation")
    st.info("Interactive preview - backend workflow connects in the next backend step.")
    st.markdown(
        '<div class="draft-watermark">'
        "DRAFT - NOT AN OFFICIAL COURT RECORD - HUMAN REVIEWED"
        "</div>",
        unsafe_allow_html=True,
    )
    st.subheader("Original vs Reviewed (preview)")
    eval_wer, eval_cer, eval_changed, eval_flags = st.columns(4)
    eval_wer.metric("Word Error Rate", "—")
    eval_cer.metric("Character Error Rate", "—")
    eval_changed.metric("Segments changed", "—")
    eval_flags.metric("Flags resolved", "—")
    st.caption("Preview placeholders — real scores connect with the backend evaluation step.")
    st.divider()
    st.subheader("Actions")
    if st.button("Generate DOCX Draft (Backend Next)", type="secondary"):
        st.info("DOCX generation connects in the backend step. No file is generated in this preview.")
