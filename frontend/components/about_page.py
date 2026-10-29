"""About Us page: mission, problem, approach, solution, footer.

Content lives in module-level constants; render_about() only lays out.
No backend calls. Navigation writes show_about (and guarded current_step
for Quick Links) and nothing else.
"""

import streamlit as st

from frontend import state
from frontend.components.language_notes import render_language_notes
from frontend.components.stepper import can_access_snapshot

HERO_TITLE = "Karibu HakiScribe"
HAKI_NOTE = '"Haki" means justice in Kiswahili.'
HERO_INTRO = (
    "HakiScribe is a prototype review desk that turns a hearing recording "
    "into a draft transcript which a person reviews and corrects, with "
    "every change recorded. Its purpose is to reduce avoidable delay in "
    "preparing accurate court records."
)

PROBLEM_HEADING = "The Problem"
PROBLEM_PARAGRAPHS = (
    "When preparing, processing and sharing court proceedings depends on manual documentation and transcription, timely access to justice suffers. Judicial officers and court staff struggle to keep pace with recording hearings, preparing proceedings and judgments, and answering document requests.",
    "Delays hurt appellants and advocates who need records in time to move an appeal forward; for short custodial sentences, waiting can shrink what a successful appeal is worth. People of limited means face further barriers from repeated court visits and hard-to-find information. Technology cannot remove every cause of delay, but better digital tools can cut avoidable bottlenecks and keep records accurate, available and accountable — while protecting judicial independence, fairness, confidentiality and the integrity of official records.",
)
PROBLEM_CARDS = (
    (
        "DELAYS",
        "Manual documentation and transcription slow the preparation of proceedings and records.",
        "green",
    ),
    (
        "APPEALS",
        "Appellants and advocates need timely records; delay can mean time in custody while an appeal waits.",
        "gold",
    ),
    (
        "WORKLOAD",
        "Judicial officers and court staff balance recording hearings, preparing proceedings and answering document requests.",
        "amber",
    ),
    (
        "TRUST",
        "Records must stay accurate, confidential and traceable.",
        "dark",
    ),
)
AFFECTED_LABEL = "Who is affected"
AFFECTED_CHIPS = (
    "Judicial officers",
    "Court clerks and registry staff",
    "Advocates",
    "Litigants and appellants",
)

APPROACH_HEADING = "Our Approach"
APPROACH_TEXT = (
    "HakiScribe keeps a human reviewer in charge at every step.",
    "The AI drafts; the reviewer checks, corrects, and owns every decision.",
)
APPROACH_CHECKLIST = (
    "A person always decides, and the tool never makes legal decisions.",
    "The original machine transcript is never overwritten.",
    "Every correction records who, when and why.",
    "Unresolved issues stay visible.",
    "This prototype uses synthetic data only.",
    "Supports judicial independence and procedural fairness by assisting staff, not replacing judgment.",
)
APPROACH_SVG = (
    '<svg width="72" height="72" viewBox="0 0 72 72" role="img" '
    'aria-label="Human review check badge">'
    '<circle cx="36" cy="36" r="34" fill="#0B3D2C"/>'
    '<circle cx="36" cy="36" r="34" fill="none" stroke="#C9A86A" stroke-width="3"/>'
    '<path d="M22 37l10 10 18-20" fill="none" stroke="#FAF7F0" '
    'stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
    "</svg>"
)

SOLUTION_HEADING = "Our Solution"
MODEL_STATUS = {"voice": "Live", "spark": "Coming next", "export": "Coming next"}
SOLUTION_CARDS = (
    {
        "number": "1",
        "title": "Transcribe",
        "tint": "green",
        "status_key": "voice",
        "text": "Muse Voice Transcribe produces speaker labels and timestamps.",
    },
    {
        "number": "2",
        "title": "Review",
        "tint": "white",
        "status_key": "spark",
        "text": "Muse Spark flags possible errors; jump to the audio passage; edit and decide.",
    },
    {
        "number": "3",
        "title": "Export and Evaluate",
        "tint": "amber",
        "status_key": "export",
        "text": "A watermarked DOCX draft and a measured WER/CER comparison.",
    },
)

SCOPE_HEADING = "Scope of this prototype"
SCOPE_BUILT_HEADING = "Built here"
SCOPE_BUILT_TEXT = (
    "Capture and verification of a hearing transcript: "
    "upload, transcribe, review, correct, draft export."
)
SCOPE_BEYOND_HEADING = "Beyond this prototype"
BEYOND_PROTOTYPE = (
    ("request tracking", "Not built"),
    ("deadline alerts", "Not built"),
    ("certification and digital signatures", "Not built"),
    ("authorised access to court documents", "Not built"),
    ("integration with judiciary systems", "Not built"),
)
SCOPE_VISION_NOTE = "Part of the wider vision — not features of this prototype."
SCOPE_NOTICE = (
    "Not legal advice. No appeal-eligibility or sentencing decisions. "
    "Draft transcripts are not certified records."
)

FOOTER_BRAND = "HakiScribe"
FOOTER_MISSION = "Reducing avoidable delay in preparing accurate court records."
FOOTER_QUICK_LINKS = (
    ("upload", "Upload"),
    ("transcribe", "Transcribe"),
    ("review", "Review Desk"),
    ("export", "Draft & Evaluation"),
)
FOOTER_CONTACT = "[Add team names and contact]"
FOOTER_LINKS_HEADING = "Quick Links"
FOOTER_MODELS_HEADING = "Models and Data"
FOOTER_CONTACT_HEADING = "Contact"
FOOTER_BOTTOM = (
    "© 2026 HakiScribe AI. Hackathon prototype. "
    "Draft transcripts only; not a certified record."
)


def _go_to_workflow(step_key: str) -> None:
    """Return to the workflow, applying the step only if guards allow."""
    snapshot = st.session_state.get(state.SNAPSHOT)
    st.session_state[state.SHOW_ABOUT] = False
    allowed, _reason = can_access_snapshot(step_key, snapshot)
    if allowed:
        st.session_state[state.CURRENT_STEP] = step_key
    st.rerun()


def _render_hero() -> None:
    st.markdown(
        f'<div class="about-hero"><h1>{HERO_TITLE}</h1>'
        f"<p><em>{HAKI_NOTE}</em></p>"
        f"<p>{HERO_INTRO}</p></div>",
        unsafe_allow_html=True,
    )
    if st.button("Start the review workflow", type="primary", key="start_workflow"):
        st.session_state[state.SHOW_ABOUT] = False
        st.rerun()


def _render_problem() -> None:
    st.markdown(
        f'<div class="about-section"><h2 class="about-center">{PROBLEM_HEADING}</h2>'
        + "".join(f"<p>{paragraph}</p>" for paragraph in PROBLEM_PARAGRAPHS)
        + "</div>",
        unsafe_allow_html=True,
    )
    columns = st.columns(4)
    for column, (label, text, tint) in zip(columns, PROBLEM_CARDS):
        column.markdown(
            f'<div class="about-problem-card">'
            f'<span class="about-problem-label label-{tint}">{label}</span>'
            f"<p>{text}</p></div>",
            unsafe_allow_html=True,
        )
    st.markdown(
        f'<p class="about-affected-label">{AFFECTED_LABEL}</p>'
        '<div class="about-chips">'
        + "".join(
            f'<span class="about-chip">{chip}</span>' for chip in AFFECTED_CHIPS
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_approach() -> None:
    st.markdown(
        f'<div class="about-section"><h2 class="about-center">{APPROACH_HEADING}</h2></div>',
        unsafe_allow_html=True,
    )
    text_col, check_col = st.columns(2)
    with text_col:
        st.markdown(
            f'<div class="about-approach-lead">{APPROACH_SVG}<div>'
            + "".join(f"<p>{paragraph}</p>" for paragraph in APPROACH_TEXT)
            + "</div></div>",
            unsafe_allow_html=True,
        )
    with check_col:
        st.markdown(
            '<ul class="about-checklist">'
            + "".join(f"<li>{item}</li>" for item in APPROACH_CHECKLIST)
            + "</ul>",
            unsafe_allow_html=True,
        )


def _render_solution() -> None:
    st.markdown(
        f'<div class="about-section"><h2 class="about-center">{SOLUTION_HEADING}</h2></div>',
        unsafe_allow_html=True,
    )
    columns = st.columns(3)
    for column, card in zip(columns, SOLUTION_CARDS):
        status = MODEL_STATUS[card["status_key"]]
        badge_class = (
            "about-badge-live" if status == "Live" else "about-badge-next"
        )
        column.markdown(
            f'<div class="about-solution-card tint-{card["tint"]}">'
            f'<span class="about-step-number">{card["number"]}</span>'
            f"<h3>{card['title']}</h3>"
            f'<span class="{badge_class}">{status}</span>'
            f"<p>{card['text']}</p></div>",
            unsafe_allow_html=True,
        )


def _render_language_notes() -> None:
    """Measured accuracy notes (shared panel component)."""
    render_language_notes()


def _render_scope() -> None:
    st.markdown(
        f'<div class="about-section"><h2 class="about-center">{SCOPE_HEADING}</h2></div>',
        unsafe_allow_html=True,
    )
    built_col, beyond_col = st.columns(2)
    with built_col:
        st.markdown(
            f'<div class="about-scope-card"><h3>{SCOPE_BUILT_HEADING}</h3>'
            f"<p>{SCOPE_BUILT_TEXT}</p></div>",
            unsafe_allow_html=True,
        )
    with beyond_col:
        items = "".join(
            f'<p class="about-beyond-item">{text}'
            f'<span class="about-notbuilt">{label}</span></p>'
            for text, label in BEYOND_PROTOTYPE
        )
        st.markdown(
            f'<div class="about-scope-card"><h3>{SCOPE_BEYOND_HEADING}</h3>'
            f"{items}"
            f'<p class="about-vision-note">{SCOPE_VISION_NOTE}</p></div>',
            unsafe_allow_html=True,
        )
    st.info(SCOPE_NOTICE)


def _render_footer() -> None:
    st.markdown('<div class="about-footer">', unsafe_allow_html=True)
    brand_col, links_col, models_col, contact_col = st.columns(4)
    with brand_col:
        st.markdown(
            f"<h3>{FOOTER_BRAND}</h3><p>{FOOTER_MISSION}</p>",
            unsafe_allow_html=True,
        )
    with links_col:
        st.markdown(f"<h3>{FOOTER_LINKS_HEADING}</h3>", unsafe_allow_html=True)
        for step_key, label in FOOTER_QUICK_LINKS:
            if st.button(label, key=f"quick_link_{step_key}"):
                _go_to_workflow(step_key)
    with models_col:
        st.markdown(
            f"<h3>{FOOTER_MODELS_HEADING}</h3>"
            f"<p>Muse Voice Transcribe — {MODEL_STATUS['voice']}</p>"
            f"<p>Muse Spark review — {MODEL_STATUS['spark']}</p>"
            f"<p>Draft export and evaluation — {MODEL_STATUS['export']}</p>"
            "<p>Synthetic demo recordings only.</p>",
            unsafe_allow_html=True,
        )
    with contact_col:
        st.markdown(
            f"<h3>{FOOTER_CONTACT_HEADING}</h3><p>{FOOTER_CONTACT}</p>",
            unsafe_allow_html=True,
        )
    st.markdown(
        f'<p class="about-footer-bottom">{FOOTER_BOTTOM}</p></div>',
        unsafe_allow_html=True,
    )


def render_about() -> None:
    """Render the full About page (hero, problem, approach, solution, footer)."""
    if st.button("Back to workflow", type="secondary", key="back_to_workflow"):
        st.session_state[state.SHOW_ABOUT] = False
        st.rerun()
    st.markdown('<div class="about-page">', unsafe_allow_html=True)
    _render_hero()
    _render_problem()
    _render_approach()
    _render_solution()
    _render_language_notes()
    _render_scope()
    _render_footer()
    st.markdown("</div>", unsafe_allow_html=True)
