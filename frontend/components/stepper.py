"""Workflow stepper: visual state only, driven by st.session_state."""

import streamlit as st

STEPS = [
    ("upload", "1. Upload"),
    ("transcribe", "2. Transcribe"),
    ("review", "3. Review Desk"),
    ("export", "4. Draft & Evaluation"),
]

_ACTIVE_BG = "#0B3D2C"
_ACTIVE_BORDER = "#C9A86A"
_COMPLETED_BG = "#E8D9B8"
_COMPLETED_TEXT = "#1F2A24"
_UPCOMING_BG = "#FFFFFF"
_UPCOMING_TEXT = "#5F6F66"


def get_step_index(step_key: str) -> int:
    """Return the STEPS index for a key, defaulting to 0 when unknown."""
    order = [key for key, _ in STEPS]
    return order.index(step_key) if step_key in order else 0


def can_access_step(
    step_key: str, has_recording: bool, has_transcript: bool
) -> tuple[bool, str]:
    """Return (allowed, reason) for navigating to a workflow step.

    The reason names the missing prerequisite, or "" when allowed.
    Unknown steps are denied.
    """
    if step_key == "upload":
        return (True, "")
    if step_key == "transcribe":
        if has_recording:
            return (True, "")
        return (False, "Upload a synthetic recording first")
    if step_key == "review":
        if has_transcript:
            return (True, "")
        return (False, "Transcribe the recording first")
    if step_key == "export":
        if has_transcript:
            return (True, "")
        return (False, "Complete transcription and review first")
    return (False, f"Unknown step: {step_key}")


def can_access_snapshot(step_key: str, snapshot) -> tuple[bool, str]:
    """Guard navigation from snapshot booleans; None snapshot denies all.

    Takes the WorkflowSnapshot without importing it, so this component
    stays backend-free. Reasons match can_access_step exactly.
    """
    if step_key == "upload":
        return (True, "")
    if snapshot is None:
        return can_access_step(step_key, False, False)
    if step_key == "transcribe":
        if snapshot.can_transcribe:
            return (True, "")
        return (False, "Upload a synthetic recording first")
    if step_key == "review":
        if snapshot.can_review:
            return (True, "")
        return (False, "Transcribe the recording first")
    if step_key == "export":
        if snapshot.can_export:
            return (True, "")
        return (False, "Complete transcription and review first")
    return (False, f"Unknown step: {step_key}")


def _step_style(key: str, current_step: str) -> tuple[str, str, str]:
    """Return (background, text color, border) for a step pill."""
    current_idx = get_step_index(current_step)
    idx = get_step_index(key)
    if idx == current_idx:
        return (_ACTIVE_BG, "#FFFFFF", f"2px solid {_ACTIVE_BORDER}")
    if idx < current_idx:
        return (_COMPLETED_BG, _COMPLETED_TEXT, "1px solid #C9A86A")
    return (_UPCOMING_BG, _UPCOMING_TEXT, "1px solid #D6D3D1")


def render_stepper(current_step: str) -> None:
    """Render 4 equally spaced step pills; active/completed/upcoming styled."""
    columns = st.columns(4)
    for column, (key, label) in zip(columns, STEPS):
        background, color, border = _step_style(key, current_step)
        column.markdown(
            f'<div style="background-color:{background};color:{color};'
            f"border:{border};border-radius:0.5rem;padding:0.5rem;"
            f'text-align:center;font-weight:600;">{label}</div>',
            unsafe_allow_html=True,
        )
