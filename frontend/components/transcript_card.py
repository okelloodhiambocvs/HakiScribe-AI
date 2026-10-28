"""Transcript segment card: read-only display, no services or database."""

import streamlit as st

from frontend.theme import confidence_style, speaker_badge_html

LOW_CONFIDENCE_THRESHOLD = 0.75
SELECTED_ACCENT = "#C9A86A"


def _format_time_range(start_sec: float, end_sec: float) -> str:
    return f"{float(start_sec):.1f}s – {float(end_sec):.1f}s"


def _format_confidence(confidence: float | None) -> str:
    if confidence is None:
        return "n/a"
    return f"{float(confidence) * 100:.0f}%"


def render_segment_card(segment: dict, is_selected: bool = False) -> None:
    """Render one transcript segment in a bordered container.

    Shows the speaker badge, time range, confidence with text label,
    language, and the exact text_current. Never edits data.
    """
    card = st.container(border=True)
    if is_selected:
        card.markdown(
            f'<div style="height:4px;background-color:{SELECTED_ACCENT};'
            'border-radius:2px;margin-bottom:0.5rem;"></div>'
            f'<span style="display:inline-block;border:2px solid {SELECTED_ACCENT};'
            "border-radius:9999px;padding:0.1rem 0.6rem;"
            'font-size:0.8rem;font-weight:700;">Selected</span>',
            unsafe_allow_html=True,
        )
    card.markdown(speaker_badge_html(segment.get("speaker")), unsafe_allow_html=True)
    card.write(_format_time_range(segment["start_sec"], segment["end_sec"]))
    confidence = segment.get("confidence")
    label, color = confidence_style(confidence)
    card.markdown(
        f"Confidence: {_format_confidence(confidence)} "
        f'<span style="color:{color};font-weight:600;">({label})</span>',
        unsafe_allow_html=True,
    )
    card.write(f"Language: {segment.get('language', 'mixed')}")
    card.write(segment.get("text_current", ""))
    if confidence is not None and float(confidence) < LOW_CONFIDENCE_THRESHOLD:
        card.warning("Low confidence - Needs human review")
