"""HakiScribe-AI brand theme: colors, badges, and Streamlit CSS.

Presentation only — no service calls, no business logic.
"""

import html
from string import Template

import streamlit as st

BRAND = {
    "primary_dark_green": "#0B3D2C",
    "deep_green": "#082E21",
    "accent_gold_brown": "#C9A86A",
    "accent_light": "#E8D9B8",
    "cream_bg": "#FAF7F0",
    "card_bg": "#FFFFFF",
    "text_dark": "#1F2A24",
    "warning": "#B45309",
    "danger": "#B91C1C",
    "success": "#137333",
}

SPEAKER_COLORS = {
    "MAGISTRATE": "#0B3D2C",
    "PROSECUTOR": "#1E4D2B",
    "ADVOCATE": "#2F5D33",
    "ACCUSED": "#7C2D12",
    "COMPLAINANT": "#8A6D2F",
    "WITNESS_PW1": "#5C6223",
    "WITNESS_PW2": "#57534E",
    "COURT_ASSISTANT": "#3F6212",
    "INVESTIGATING_OFFICER": "#44403C",
    "INTERPRETER": "#C9A86A",
    "UNKNOWN": "#78716C",
}

_CSS_TEMPLATE = Template(
    """
<style>
.stApp { background-color: $cream_bg; }
section[data-testid="stSidebar"] { background-color: $deep_green; }
section[data-testid="stSidebar"] * { color: $cream_bg !important; }
h1, h2 { color: $primary_dark_green !important; }
div[data-testid="stAppViewContainer"] p { color: $text_dark; }
button[kind="primary"] {
    background-color: $primary_dark_green;
    color: #FFFFFF;
    border: 1px solid $primary_dark_green;
    border-radius: 0.5rem;
}
button[kind="primary"]:hover {
    border: 2px solid $accent_gold_brown;
    color: #FFFFFF;
}
button[kind="secondary"] {
    background-color: $cream_bg;
    color: $primary_dark_green;
    border: 1px solid $accent_gold_brown;
    border-radius: 0.5rem;
}
.hakiscribe-card {
    background-color: $card_bg;
    border-radius: 0.75rem;
    box-shadow: 0 1px 4px rgba(8, 46, 33, 0.12);
    padding: 1rem 1.25rem;
    margin-bottom: 1rem;
}
details { border-radius: 0.5rem; }
div[data-testid="stMetric"] {
    background-color: $card_bg;
    border-top: 3px solid $accent_gold_brown;
    border-radius: 0.5rem;
    padding: 0.75rem;
    box-shadow: 0 1px 4px rgba(8, 46, 33, 0.12);
}
div[data-testid="stAlert"] {
    background-color: $cream_bg;
    border: 1px solid $accent_gold_brown;
    border-radius: 0.5rem;
}
div[data-testid="stAlert"] * {
    color: $primary_dark_green !important;
    font-weight: 600;
    text-align: center;
}
.draft-watermark {
    background-color: $cream_bg;
    border: 3px double $accent_gold_brown;
    color: $primary_dark_green;
    font-weight: 800;
    text-align: center;
    padding: 1rem;
    border-radius: 0.5rem;
    letter-spacing: 0.05em;
}
button[kind="secondary"]:hover {
    border: 2px solid $primary_dark_green;
}
button:focus-visible {
    outline: 3px solid $accent_gold_brown;
    outline-offset: 2px;
}
@media (max-width: 768px) {
    .block-container { padding: 1rem 0.75rem; }
    div[data-testid="column"] { min-width: 100% !important; }
    .hakiscribe-card { padding: 0.75rem; }
    h1 { font-size: 1.75rem !important; }
    h2 { font-size: 1.4rem !important; }
    button[kind="primary"], button[kind="secondary"] { width: 100%; }
}
</style>
"""
)


def apply_theme() -> None:
    """Inject the HakiScribe brand CSS into the Streamlit app."""
    st.markdown(_CSS_TEMPLATE.substitute(BRAND), unsafe_allow_html=True)


def confidence_style(confidence: float | None) -> tuple[str, str]:
    """Return (text label, color) for a confidence value.

    The label always carries the meaning; color is decoration only.
    """
    if confidence is None:
        return ("Unknown", BRAND["text_dark"])
    value = float(confidence)
    if value >= 0.90:
        return ("High", BRAND["success"])
    if value >= 0.75:
        return ("Medium", BRAND["warning"])
    return ("Low - Needs human review", BRAND["danger"])


def _relative_luminance(hex_color: str) -> float:
    rgb = tuple(int(hex_color[i : i + 2], 16) / 255.0 for i in (1, 3, 5))
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _text_on_background(hex_color: str) -> str:
    return "#FFFFFF" if _relative_luminance(hex_color) < 0.35 else BRAND["text_dark"]


def speaker_badge_html(speaker: str | None) -> str:
    """Return a safe HTML snippet for a small rounded speaker badge."""
    label = html.escape(str(speaker or "UNKNOWN"))
    background = SPEAKER_COLORS.get(str(speaker), SPEAKER_COLORS["UNKNOWN"])
    color = _text_on_background(background)
    return (
        f'<span style="display:inline-block;background-color:{background};'
        f"color:{color};border-radius:9999px;padding:0.15rem 0.6rem;"
        f'font-size:0.8rem;font-weight:600;">{label}</span>'
    )
