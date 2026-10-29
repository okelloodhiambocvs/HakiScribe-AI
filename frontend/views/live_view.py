"""Live microphone view: consented realtime capture (side tab).

Twenty-four kHz mono PCM streams from the microphone to Meta's realtime
endpoint; completed turns plus the current partial render while the
session runs. Any mic/API failure shows the exact error and no text is
ever invented. After stopping, the saved WAV can run the normal
guarded batch pass ("Finalise with batch pass").
"""

import streamlit as st

from backend.core.config import is_configured
from backend.services import workflow_service
from frontend import state
from frontend.components.errors import show_error
from frontend.components.privacy import render_privacy_notice

_RUNNING = ("connecting", "live")


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as MM:SS."""
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def _render_live_transcript() -> None:
    """Auto-refreshing live area: completed turns + current partial."""
    try:
        live = workflow_service.get_live_state()
    except Exception as exc:
        show_error(exc)
        return
    st.write(f"Elapsed: {_format_elapsed(live['elapsed_s'])}")
    for turn in live["turns"]:
        st.write(
            f"[{turn['start_s']:.1f}-{turn['end_s']:.1f}] "
            f"{turn['speaker']}: {turn['text']}"
        )
    if live["partial"]:
        st.caption(live["partial"])


if hasattr(st, "fragment"):
    _render_live_transcript = st.fragment(run_every=1)(_render_live_transcript)


def render(reviewer: str) -> None:
    """Render the Live microphone tab (reviewer comes from the sidebar)."""
    st.header("Live microphone")
    st.warning(
        "Synthetic demo only. AI proposes, HUMAN REVIEWS. "
        "This is not an official court record."
    )
    if st.button("Back to workflow", key="live_back_to_workflow"):
        st.session_state[state.CURRENT_STEP] = "upload"
        st.rerun()
    try:
        live = workflow_service.get_live_state()
    except Exception as exc:
        show_error(exc)
        return
    status = live["status"]
    if live["last_error"]:
        st.error(live["last_error"])
    if live["note"]:
        st.info(live["note"])
    if status in _RUNNING:
        st.info("LIVE (approximate timestamps)")
        if st.button("Stop", key="live_stop"):
            try:
                workflow_service.stop_live_session()
            except Exception as exc:
                show_error(exc)
            st.rerun()
        _render_live_transcript()
        return
    _render_setup(reviewer)
    _render_summary(live)


def _render_setup(reviewer: str) -> None:
    """Consent + device selector + Start for a new session."""
    st.subheader("New live session")
    render_privacy_notice()
    try:
        devices = workflow_service.list_microphones()
    except Exception as exc:
        show_error(exc)
        devices = None
    consent = st.checkbox(
        "All speakers have consented; this is a synthetic or consented session",
        key="live_consent",
    )
    if not consent:
        st.caption("Consent is required to start.")
    device = None
    if devices:
        options = [("Default microphone", None)] + [
            (f"{item['name']} (index {item['index']})", item["index"])
            for item in devices
        ]
        choice = st.selectbox(
            "Microphone",
            options,
            format_func=lambda option: option[0],
            key="live_device",
        )
        device = choice[1]
    elif devices is not None:
        st.warning("No microphone found. Connect a microphone to go live.")
    if not (reviewer or "").strip():
        st.warning("Enter your reviewer name in the sidebar first.")
    start_disabled = (
        not (reviewer or "").strip() or not consent or not devices
    )
    if st.button(
        "Start live session", disabled=start_disabled, key="live_start"
    ):
        try:
            workflow_service.start_live_session(
                reviewer, consent, device=device
            )
        except Exception as exc:
            show_error(exc)
        else:
            st.rerun()


def _render_summary(live: dict) -> None:
    """Post-session summary, badges, finalise, and review handoff."""
    if live["status"] not in ("ended", "error"):
        return
    st.subheader("Session summary")
    st.write(
        f"Turns: {live['turn_count']} | "
        f"Elapsed: {_format_elapsed(live['elapsed_s'])}"
    )
    recording_id = live["recording_id"]
    if recording_id is None:
        return
    final = False
    try:
        snapshot = workflow_service.get_snapshot(recording_id)
    except Exception as exc:
        show_error(exc)
        snapshot = None
    if snapshot is not None and snapshot.transcript_status == "present":
        final = bool(snapshot.segments) and all(
            not segment.get("is_approximate") for segment in snapshot.segments
        )
        if final:
            st.success("FINAL (batch pass)")
        else:
            st.info("LIVE (approximate timestamps)")
    if not final:
        mock = st.checkbox(
            "Use mock demo mode (no Meta API call)",
            value=not is_configured(),
            key="live_finalise_mock",
        )
        if st.button("Finalise with batch pass", key="live_finalise"):
            try:
                workflow_service.finalise_live_session(
                    recording_id, force_mock=mock
                )
            except Exception as exc:
                show_error(exc)
            else:
                st.success("Batch pass complete.")
                st.rerun()
    if st.button("Open in Review Desk", key="live_open_workflow"):
        st.session_state[state.RECORDING_ID] = recording_id
        st.session_state[state.CURRENT_STEP] = "review"
        st.rerun()
