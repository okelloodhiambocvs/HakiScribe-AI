"""Language and accuracy notes panel (measured values only).

Shows per-category WER from evaluation/results/latest.json when a run
exists, otherwise "Not yet measured". The standing notices always show.
Never raises: a missing or invalid results file means "not measured".
"""

import json
import os
from pathlib import Path

import streamlit as st

PANEL_TITLE = "Language and accuracy notes"
NOT_MEASURED = "Not yet measured on Kenyan speech"
NOTICES = (
    "HakiScribe shows the transcript as recognised. It does not translate, "
    "paraphrase or add words.",
    "Accuracy can drop with accents, overlapping speech, background noise "
    "and mixed languages. Always verify against the audio.",
)
CATEGORIES = (
    ("english", "English"),
    ("kiswahili", "Kiswahili"),
    ("code_switched", "Code-switched English-Kiswahili"),
)
RESULTS_ENV_VAR = "HAKISCRIBE_EVAL_RESULTS"


def results_path() -> Path:
    """Results file, overridable for tests via HAKISCRIBE_EVAL_RESULTS."""
    override = os.environ.get(RESULTS_ENV_VAR)
    if override:
        return Path(override)
    return (
        Path(__file__).resolve().parent.parent.parent
        / "evaluation"
        / "results"
        / "latest.json"
    )


def load_eval_results() -> dict | None:
    """Load latest.json; None when missing or invalid (never raises)."""
    try:
        data = json.loads(results_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def category_wer(results: dict | None, category: str) -> float | None:
    """Measured mean WER for a category; None when not measured."""
    if not results:
        return None
    entry = (results.get("categories") or {}).get(category) or {}
    if not entry.get("clips"):
        return None
    wer = entry.get("wer")
    return wer if isinstance(wer, (int, float)) else None


def render_language_notes() -> None:
    """Render the panel: measured WER per category + standing notices."""
    results = load_eval_results()
    with st.expander(PANEL_TITLE, expanded=False):
        for key, label in CATEGORIES:
            wer = category_wer(results, key)
            if wer is None:
                st.write(f"{label}: {NOT_MEASURED}")
            else:
                st.write(f"{label}: WER {wer:.4f}")
        run_at = (results or {}).get("run_at")
        if run_at:
            st.caption(f"Measured {run_at}; see docs/EVALUATION.md.")
        for notice in NOTICES:
            st.caption(notice)
