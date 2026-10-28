"""Transcribe step: recording panel, transcription run, transcript cards."""

import streamlit as st

from backend.core.config import is_configured
from backend.services.ingestion_service import get_recording_or_raise
from backend.services.transcription_service import (
    AlreadyTranscribedError,
    AudioPrepError,
    TranscriptionError,
    TranscriptionInProgressError,
    TranscriptionLockedError,
    get_transcript,
    transcribe_recording,
)
from frontend import state
from frontend.components.transcript_card import (
    LOW_CONFIDENCE_THRESHOLD,
    render_segment_card,
)


def _reset_draft_edit(segment_id: int) -> None:
    """Drop one segment's UI draft and its widget state (database untouched)."""
    drafts = st.session_state.get(state.DRAFT_EDITS, {})
    drafts.pop(segment_id, None)
    st.session_state.pop(f"draft_edit_{segment_id}", None)


def _render_source_badge(recording_id: int, status: str | None) -> None:
    """Show the transcript source from the recording row as a clear badge."""
    if status is None:
        return
    try:
        fresh = get_recording_or_raise(recording_id)
    except ValueError:
        fresh = {}
    source = (fresh.get("transcription_source") if fresh else None) or (
        "real" if status == "real" else "mock"
    )
    if source == "real":
        st.success("Real: Muse Voice Transcribe")
    else:
        st.info("MOCK: demo only")


def render() -> None:
    """Render the recording panel and transcript (upload/transcribe steps)."""
    step = st.session_state[state.CURRENT_STEP]
    recording = st.session_state[state.RECORDING]
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
        transcribing = st.session_state.get(state.TRANSCRIBING, False)
        if st.button("Transcribe Recording", type="primary", disabled=transcribing):
            st.session_state[state.TRANSCRIBING] = True
            try:
                result = transcribe_recording(
                    recording["id"], force_mock=use_mock
                )
            except TranscriptionInProgressError:
                st.info("A transcription for this recording is already running. Wait a moment, then retry.")
            except (AlreadyTranscribedError, TranscriptionLockedError) as exc:
                st.info(f"{exc} Showing saved segments.")
                st.session_state[state.TRANSCRIPT_STATUS] = "already_transcribed"
            except (ValueError, TranscriptionError, AudioPrepError) as exc:
                st.error(str(exc))
            else:
                st.session_state[state.TRANSCRIPT_STATUS] = result["status"]
            finally:
                st.session_state[state.TRANSCRIBING] = False

        status = st.session_state[state.TRANSCRIPT_STATUS]
        if status == "real":
            st.success("REAL Meta call — Muse Voice Transcribe via Meta Model API.")
        elif isinstance(status, str) and status.startswith("mock"):
            st.info("MOCK synthetic demo — no Meta API call was made.")
        elif status == "already_transcribed":
            st.info("Already transcribed — showing saved segments.")
        _render_source_badge(recording["id"], status)

        segments = get_transcript(recording["id"])
        if segments:
            st.info(
                "Original AI text is preserved. Draft edits in this UI preview "
                "are not yet written to the correction history."
            )
            active_filter = st.session_state.get(state.SPEAKER_FILTER, "ALL")
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
                    st.session_state[state.SPEAKER_FILTER] = speaker
                    st.rerun()
            st.session_state[state.SHOW_LOW_CONFIDENCE_ONLY] = st.checkbox(
                "Show low confidence only (<0.75)",
                value=st.session_state.get(state.SHOW_LOW_CONFIDENCE_ONLY, False),
            )
            st.session_state[state.TRANSCRIPT_SEARCH] = st.text_input(
                "Search transcript",
                value=st.session_state.get(state.TRANSCRIPT_SEARCH, ""),
            )
            query = st.session_state[state.TRANSCRIPT_SEARCH].strip().lower()
            low_only = st.session_state[state.SHOW_LOW_CONFIDENCE_ONLY]
            speaker_filter = st.session_state[state.SPEAKER_FILTER]
            filtered = [
                segment
                for segment in segments
                if (speaker_filter == "ALL" or segment["speaker"] == speaker_filter)
                and (
                    not low_only
                    or (
                        segment["confidence"] is not None
                        and float(segment["confidence"]) < LOW_CONFIDENCE_THRESHOLD
                    )
                )
                and (not query or query in (segment["text_current"] or "").lower())
            ]
            st.caption(f"Showing {len(filtered)} of {len(segments)} segments")
            st.caption("Listen buttons preview selection only; precise audio seeking connects later.")
            selected_idx = st.session_state.get(state.SELECTED_SEGMENT_IDX)
            for segment in filtered:
                render_segment_card(segment, is_selected=segment["idx"] == selected_idx)
                select_col, listen_col = st.columns(2)
                if select_col.button("Select", key=f"select_{segment['id']}"):
                    st.session_state[state.SELECTED_SEGMENT_IDX] = segment["idx"]
                    st.rerun()
                if listen_col.button("Listen (Preview)", key=f"listen_{segment['id']}"):
                    st.session_state[state.SELECTED_SEGMENT_IDX] = segment["idx"]
                    st.rerun()
            selected = next(
                (item for item in segments if item["idx"] == selected_idx), None
            )
            if selected is not None:
                detail_box = st.container(border=True)
                detail_box.subheader("Selected segment")
                detail_box.write(f"speaker: {selected['speaker']}")
                detail_box.write(f"start_sec: {selected['start_sec']}")
                detail_box.write(f"end_sec: {selected['end_sec']}")
                detail_box.write(f"confidence: {selected['confidence']}")
                detail_box.write(f"language: {selected['language']}")
                detail_box.text_area(
                    "Original AI text",
                    value=selected["text_original"],
                    disabled=True,
                    key=f"original_text_{selected['id']}",
                )
                drafts = st.session_state.setdefault(state.DRAFT_EDITS, {})
                detail_box.text_area(
                    "Current text (draft)",
                    value=drafts.get(selected["id"], selected["text_current"]),
                    key=f"draft_edit_{selected['id']}",
                )
                if detail_box.button("Save Draft Edit (UI only)"):
                    drafts[selected["id"]] = st.session_state[f"draft_edit_{selected['id']}"]
                    detail_box.success("Draft edit saved locally - backend correction saving connects in the next backend step")
                detail_box.button("Reset Edit", on_click=_reset_draft_edit, args=(selected["id"],))
        else:
            st.info("No transcript yet. Press Transcribe Recording to create one from this recording.")
            if st.button("Go to Upload", key="no_segments_go_upload"):
                st.session_state[state.CURRENT_STEP] = "upload"
                st.rerun()
    elif step == "transcribe":
        st.info("No recording yet. Upload and validate a synthetic recording first.")
        if st.button("Go to Upload", type="primary", key="no_recording_go_upload"):
            st.session_state[state.CURRENT_STEP] = "upload"
            st.rerun()
