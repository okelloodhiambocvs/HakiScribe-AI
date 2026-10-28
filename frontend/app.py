"""HakiScribe-AI V2 Review Desk: entry point (shell, stepper, router).

Streamlit UI only. Step content lives in frontend/views/; this module owns
page config, theme, sidebar, session init, stepper, progress, and routing.
"""

import streamlit as st

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from frontend import state
from frontend.components.about_page import render_about
from frontend.components.stepper import can_access_step, render_stepper
from frontend.theme import apply_theme
from frontend.views import export_view, review_view, transcribe_view, upload_view


def _safe_toast(message: str) -> None:
    """Show a toast when supported; never crash older Streamlit versions."""
    try:
        toast = getattr(st, "toast", None)
        if callable(toast):
            toast(message)
    except Exception:
        pass


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
st.sidebar.divider()
if st.sidebar.button("About Us", key="about_us_button"):
    st.session_state[state.SHOW_ABOUT] = True
    st.rerun()

state.init_state()

if st.session_state.get(state.SHOW_ABOUT, False):
    render_about()
    st.stop()

render_stepper(st.session_state[state.CURRENT_STEP])

has_recording = st.session_state.get(state.RECORDING_ID) is not None
has_transcript = st.session_state.get(state.TRANSCRIPT_STATUS) is not None

if has_transcript and st.session_state[state.CURRENT_STEP] == "export":
    workflow_progress, workflow_step_num = 1.0, 4
elif has_transcript:
    workflow_progress, workflow_step_num = 0.75, 3
elif has_recording:
    workflow_progress, workflow_step_num = 0.50, 2
else:
    workflow_progress, workflow_step_num = 0.25, 1
st.write(f"Workflow progress: Step {workflow_step_num} of 4")
st.progress(workflow_progress)
st.caption("Workflow position only — not transcription accuracy.")

nav_targets = [
    ("upload", "Upload"),
    ("transcribe", "Transcribe"),
    ("review", "Review Desk"),
    ("export", "Draft & Evaluation"),
]
nav_columns = st.columns(4)
for nav_column, (target_step, nav_label) in zip(nav_columns, nav_targets):
    if nav_column.button(nav_label):
        allowed, reason = can_access_step(target_step, has_recording, has_transcript)
        if allowed:
            st.session_state[state.CURRENT_STEP] = target_step
            st.rerun()
        else:
            st.warning(reason)

st.divider()

notice = st.session_state.get(state.UPLOAD_NOTICE)
if notice:
    st.success("Recording validated and stored.")
    _safe_toast("Recording stored successfully")
    st.info(
        f"File: {notice['filename']} | "
        f"Size: {notice['size_bytes']} bytes | "
        f"SHA256: {notice['sha256'][:12]}…"
    )
    del st.session_state[state.UPLOAD_NOTICE]


def _render_upload_and_transcribe() -> None:
    """Upload and transcribe steps share the card + recording panels."""
    upload_view.render(reviewer)
    transcribe_view.render()


VIEWS = {
    "upload": _render_upload_and_transcribe,
    "transcribe": _render_upload_and_transcribe,
    "review": review_view.render,
    "export": export_view.render,
}

step = st.session_state[state.CURRENT_STEP]
VIEWS.get(step, lambda: None)()
