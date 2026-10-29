"""Review Desk step: human review with full traceability (service-backed)."""

import difflib

import streamlit as st

from backend.services import workflow_service
from backend.services.workflow_service import WorkflowSnapshot
from frontend import state
from frontend.components.errors import show_error
from frontend.components.transcript_card import LOW_CONFIDENCE_THRESHOLD


def _log_event_quietly(recording_id: int, reviewer: str, event: str) -> None:
    """Best-effort review event log; telemetry must not break the flow."""
    try:
        workflow_service.record_review_event(recording_id, reviewer.strip(), event)
    except Exception:
        pass


def _format_range(start_sec, end_sec) -> str:
    """Render a segment time range, noting missing timestamps."""
    if start_sec is None or end_sec is None:
        return "no timestamps"
    return f"{float(start_sec):.1f}s – {float(end_sec):.1f}s"


def _render_flag_controls(
    box, flag: dict, selected: dict, reviewer: str, recording_id: int
) -> None:
    """Render Accept/Edit/Dismiss/Keep controls for one OPEN/RETAINED flag."""
    fid = flag["id"]
    if flag.get("suggestion"):
        if box.button("Accept suggestion", key=f"flag_accept_{fid}"):
            try:
                workflow_service.decide_flag(
                    fid, "ACCEPT_SUGGESTION", reviewer.strip(), None
                )
            except Exception as exc:
                show_error(exc)
            else:
                _log_event_quietly(recording_id, reviewer, "decision")
                st.rerun()
    box.text_area(
        "Edited text",
        value=selected["text_current"] or "",
        key=f"flag_edit_text_{fid}",
    )
    edit_reason = box.text_input(
        "Reason (required for edit)", key=f"flag_edit_reason_{fid}"
    )
    if box.button("Save edit", key=f"flag_edit_{fid}"):
        try:
            workflow_service.decide_flag(
                fid,
                "EDIT_TEXT",
                reviewer.strip(),
                edit_reason,
                st.session_state[f"flag_edit_text_{fid}"],
            )
        except Exception as exc:
            show_error(exc)
        else:
            _log_event_quietly(recording_id, reviewer, "decision")
            st.rerun()
    dismiss_reason = box.text_input(
        "Reason (required to dismiss)", key=f"flag_dismiss_reason_{fid}"
    )
    if box.button("Dismiss flag", key=f"flag_dismiss_{fid}"):
        try:
            workflow_service.decide_flag(
                fid, "DISMISS_FLAG", reviewer.strip(), dismiss_reason
            )
        except Exception as exc:
            show_error(exc)
        else:
            _log_event_quietly(recording_id, reviewer, "decision")
            st.rerun()
    keep_reason = box.text_input(
        "Reason (required to keep)", key=f"flag_keep_reason_{fid}"
    )
    if box.button("Keep as uncertain", key=f"flag_keep_{fid}"):
        try:
            workflow_service.decide_flag(
                fid, "RETAIN_UNCERTAIN", reviewer.strip(), keep_reason
            )
        except Exception as exc:
            show_error(exc)
        else:
            _log_event_quietly(recording_id, reviewer, "decision")
            st.rerun()


def render(snapshot: WorkflowSnapshot | None, reviewer: str) -> None:
    """Render the two-pane human review workbench."""
    st.header("3. Review Desk")
    st.info("AI flags are suggestions for a human reviewer, not proof of error.")
    review_recording = snapshot.recording if snapshot is not None else None
    review_segments = list(snapshot.segments) if snapshot is not None else []
    if not review_recording:
        st.info("No recording yet. Upload a synthetic hearing first.")
        if st.button("Go to Upload", type="primary", key="review_empty_go_upload"):
            st.session_state[state.CURRENT_STEP] = "upload"
            st.rerun()
        return
    if not review_segments:
        st.info("No transcript yet. Transcribe the recording first.")
        if st.button("Go to Transcribe", type="primary", key="review_empty_go_transcribe"):
            st.session_state[state.CURRENT_STEP] = "transcribe"
            st.rerun()
        return

    has_reviewer = bool(reviewer.strip())
    if not has_reviewer:
        st.warning(
            "Enter your reviewer name in the sidebar to record edits and decisions."
        )

    st.subheader("Session summary")
    low_confidence = [
        segment
        for segment in review_segments
        if segment["confidence"] is not None
        and float(segment["confidence"]) < LOW_CONFIDENCE_THRESHOLD
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

    st.subheader("AI review")
    if st.button(
        "Run AI review",
        type="primary",
        key="run_ai_review",
        disabled=not has_reviewer,
    ):
        try:
            workflow_service.run_review(review_recording["id"])
        except Exception as exc:
            show_error(exc)
        else:
            st.rerun()
    try:
        summary = workflow_service.get_review_summary(review_recording["id"])
        flags = workflow_service.get_flags(review_recording["id"])
        unresolved = workflow_service.get_unresolved(review_recording["id"])
        roles = workflow_service.get_speaker_roles(review_recording["id"])
    except Exception as exc:
        show_error(exc)
        return
    if summary is None:
        st.info("No AI review yet — press Run AI review to get suggestions.")
    else:
        if summary["mode"] == "real":
            st.success("Real: Muse Spark")
        else:
            st.info("MOCK: demo only")
        st.write(
            f"Model: {summary['model']} · "
            f"Prompt: {summary['prompt_version']} · "
            f"Flags: {summary['flags_created']} created, "
            f"{summary['flags_dropped']} dropped"
        )
    st.divider()

    if has_reviewer:
        logged = st.session_state.setdefault(state.REVIEW_OPEN_EVENTS, [])
        if review_recording["id"] not in logged:
            _log_event_quietly(review_recording["id"], reviewer, "review_opened")
            logged.append(review_recording["id"])

    st.subheader(f"Unresolved issues ({len(unresolved)})")
    if not unresolved:
        st.info("No unresolved issues — every flag has a decision.")
    else:
        open_count = sum(1 for flag in unresolved if flag["status"] == "OPEN")
        st.write(
            f"{open_count} open · {len(unresolved) - open_count} retained as uncertain"
        )
        by_segment: dict[int, list] = {}
        for flag in unresolved:
            by_segment.setdefault(flag["segment_idx"], []).append(flag)
        idxs = sorted(by_segment)
        for start in range(0, len(idxs), 4):
            chunk = idxs[start : start + 4]
            jump_cols = st.columns(4)
            for column, idx in zip(jump_cols, chunk):
                count = len(by_segment[idx])
                if column.button(
                    f"Segment {idx} · {count}",
                    key=f"unresolved_jump_{idx}",
                ):
                    st.session_state[state.SELECTED_SEGMENT_IDX] = idx
                    st.rerun()
    st.divider()

    valid_idx = {segment["idx"] for segment in review_segments}
    selected_idx = st.session_state.get(state.SELECTED_SEGMENT_IDX)
    if selected_idx not in valid_idx:
        first_unresolved = sorted({flag["segment_idx"] for flag in unresolved})
        if first_unresolved:
            selected_idx = first_unresolved[0]
        else:
            selected_idx = review_segments[0]["idx"]
        st.session_state[state.SELECTED_SEGMENT_IDX] = selected_idx
    selected = next(
        segment for segment in review_segments if segment["idx"] == selected_idx
    )

    left, right = st.columns([1, 2])
    with left:
        st.subheader("Segments")
        for segment in review_segments:
            label = segment.get("speaker_label")
            role = roles.get(label) if label else None
            speaker_display = (
                f"{segment['speaker']} ({role})" if role else segment["speaker"]
            )
            seg_flag_count = sum(
                1 for flag in flags if flag["segment_id"] == segment["id"]
            )
            marker = "▶ " if segment["idx"] == selected_idx else ""
            if st.button(
                f"{marker}{speaker_display}",
                key=f"review_segment_{segment['id']}",
            ):
                st.session_state[state.SELECTED_SEGMENT_IDX] = segment["idx"]
                st.rerun()
            meta = (
                f"{_format_range(segment['start_sec'], segment['end_sec'])} · "
                f"{seg_flag_count} flags"
            )
            if segment["text_current"] != segment["text_original"]:
                meta += " · edited"
            st.caption(meta)

    with right:
        st.subheader(f"Segment {selected['idx']}")
        start, end = selected["start_sec"], selected["end_sec"]
        if start is None or end is None:
            st.info("No timestamps for this segment — passage audio unavailable.")
        else:
            try:
                st.audio(
                    review_recording["stored_path"],
                    start_time=int(start),
                    end_time=int(end),
                )
            except Exception:
                st.info("Audio preview is unavailable for this passage.")

        original = selected["text_original"] or ""
        current = selected["text_current"] or ""
        orig_col, curr_col = st.columns(2)
        orig_col.text_area(
            "Original (read-only)",
            value=original,
            disabled=True,
            key=f"review_original_{selected['id']}",
        )
        curr_col.text_area(
            "Current text",
            value=current,
            key=f"review_edit_{selected['id']}",
            disabled=not has_reviewer,
        )
        if original != current:
            diff = "".join(
                difflib.unified_diff(
                    [original], [current], "original", "current", lineterm=""
                )
            )
            st.code(diff, language="diff")
        edit_reason = st.text_input(
            "Reason for edit (required)",
            key=f"review_edit_reason_{selected['id']}",
            disabled=not has_reviewer,
        )
        if st.button(
            "Save edit",
            type="primary",
            key=f"review_save_{selected['id']}",
            disabled=not has_reviewer,
        ):
            try:
                workflow_service.edit_segment(
                    selected["id"],
                    st.session_state[f"review_edit_{selected['id']}"],
                    reviewer.strip(),
                    edit_reason,
                    selected["text_current"],
                )
            except Exception as exc:
                show_error(exc)
            else:
                _log_event_quietly(review_recording["id"], reviewer, "edit")
                st.rerun()

        st.subheader("Flags")
        seg_flags = [
            flag for flag in flags if flag["segment_id"] == selected["id"]
        ]
        if not seg_flags:
            st.info("No flags on this segment.")
        for flag in seg_flags:
            flag_box = st.container(border=True)
            flag_box.write(
                f"{flag['flag_type']} · {flag['severity']} · {flag['status']}"
            )
            flag_box.write(f"Quote: {flag['evidence']}")
            flag_box.write(flag["message"])
            if flag.get("suggestion"):
                flag_box.write(f"Suggestion: {flag['suggestion']}")
            if flag["status"] in ("OPEN", "RETAINED"):
                if not has_reviewer:
                    flag_box.caption("Add a reviewer name to decide this flag.")
                else:
                    _render_flag_controls(
                        flag_box,
                        flag,
                        selected,
                        reviewer,
                        review_recording["id"],
                    )
            else:
                decided_by = flag.get("resolved_by") or "unknown reviewer"
                flag_box.caption(f"Decided: {flag['status']} by {decided_by}")

        st.subheader("Speaker role")
        speaker_label = selected.get("speaker_label")
        if not speaker_label:
            st.info(
                "No speaker label on this segment — role assignment unavailable."
            )
        else:
            current_role = roles.get(speaker_label)
            if current_role:
                st.write(
                    f"Label: {speaker_label} · Assigned: {current_role}"
                )
            else:
                st.write(f"Label: {speaker_label} · No role assigned")
            options = [
                role
                for role in workflow_service.get_taxonomy_roles()
                if role != "UNKNOWN"
            ]
            index = options.index(current_role) if current_role in options else 0
            choice = st.selectbox(
                "Role for all segments of this label",
                options,
                index=index,
                key=f"role_select_{speaker_label}",
                disabled=not has_reviewer,
            )
            role_reason = st.text_input(
                "Reason for assignment",
                key=f"role_reason_{speaker_label}",
                disabled=not has_reviewer,
            )
            if st.button(
                "Assign role",
                key=f"role_assign_{speaker_label}",
                disabled=not has_reviewer,
            ):
                try:
                    workflow_service.assign_speaker_role(
                        review_recording["id"],
                        speaker_label,
                        choice,
                        reviewer.strip(),
                        role_reason or None,
                    )
                except Exception as exc:
                    show_error(exc)
                else:
                    _log_event_quietly(review_recording["id"], reviewer, "decision")
                    st.rerun()

        st.subheader("History")
        try:
            history = workflow_service.get_segment_history(selected["id"])
        except Exception as exc:
            show_error(exc)
            history = []
        if not history:
            st.info("No edits yet.")
        for entry in history:
            st.caption(
                f"{entry['created_at']} · {entry['reviewer_name']} · "
                f"{entry['decision']} [{entry['field']}]"
            )
            st.write(f"{entry['before_text']} → {entry['after_text']}")
            if entry.get("reason"):
                st.write(f"Reason: {entry['reason']}")
