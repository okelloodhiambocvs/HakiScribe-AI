"""Render measured evaluation results into docs (never invent numbers).

Reads evaluation/results/latest.json and rewrites docs/EVALUATION.md and
docs/LANGUAGE-LIMITATIONS.md from its values only. Every decimal in the
output is the repr of a value from the results file; categories without
results say "Not yet measured". Works when no run exists yet.
"""

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

CATEGORIES = (
    ("english", "English"),
    ("kiswahili", "Kiswahili"),
    ("code_switched", "Code-switched English-Kiswahili"),
)
NOT_MEASURED = "Not yet measured"


def load_results(path) -> dict | None:
    """Load latest.json; None when missing or invalid (never raises)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _settings_line(results: dict | None) -> str:
    """One-line run settings from the results file, or a no-run note."""
    if not results:
        return "No evaluation run yet."
    bias = results.get("language_bias") or []
    bias_text = ", ".join(bias) if bias else "none"
    return (
        f"Run {results.get('run_at')} · model {results.get('model')} · "
        f"mode {results.get('mode')} · language bias: {bias_text} · "
        f"keyword terms: {results.get('keyword_count')}"
    )


def _category_entry(results: dict | None, key: str) -> dict:
    """Category block from the results file (empty when not measured)."""
    if not results:
        return {}
    entry = (results.get("categories") or {}).get(key) or {}
    if not entry.get("clips") or entry.get("wer") is None:
        return {}
    return entry


def _number(value) -> str:
    """Format a measured value exactly as stored (repr, no arithmetic)."""
    return repr(value)


def render_evaluation_markdown(results: dict | None) -> str:
    """Build docs/EVALUATION.md from the results file only."""
    lines = [
        "# HakiScribe ASR evaluation (measured)",
        "",
        "> Every number below comes from `evaluation/results/latest.json`.",
        "> Nothing here is estimated.",
        "",
        _settings_line(results),
        "",
        "## Per-category results",
        "",
        "Mean of per-clip rates; lower is better, a perfect transcript "
        "scores zero.",
        "",
        "| Category | Clips | Mean WER | Mean CER | Reference words |",
        "| --- | --- | --- | --- | --- |",
    ]
    for key, label in CATEGORIES:
        entry = _category_entry(results, key)
        if entry:
            lines.append(
                f"| {label} | {entry['clips']} | {_number(entry['wer'])} "
                f"| {_number(entry['cer'])} | {entry['ref_words']} |"
            )
        else:
            lines.append(f"| {label} | 0 | {NOT_MEASURED} | {NOT_MEASURED} | 0 |")
    lines += [
        "",
        "## Per-clip results",
        "",
        "| Clip | Category | WER | CER | Reference words |",
        "| --- | --- | --- | --- | --- |",
    ]
    clips = (results or {}).get("clips") or []
    if clips:
        for clip in clips:
            lines.append(
                f"| {clip['id']} | {clip['category']} | {_number(clip['wer'])} "
                f"| {_number(clip['cer'])} | {clip['ref_words']} |"
            )
    else:
        lines.append(f"| _none_ | — | {NOT_MEASURED} | {NOT_MEASURED} | 0 |")
    lines += [
        "",
        "## Method",
        "",
        "- Each clip runs through the real batch endpoint: the same code "
        "path as the app, DIARIZATION mode with the configured keywords "
        "and language bias.",
        "- WER and CER use `evaluation_service` normalisation: Unicode "
        "NFC, lower-case, punctuation stripped, whitespace collapsed, "
        "diacritics preserved, no translation.",
        "- Category means are arithmetic means of the per-clip rates.",
        "- Regenerate with `python scripts/evaluate_asr.py` then "
        "`python scripts/render_evaluation_doc.py`.",
    ]
    return "\n".join(lines) + "\n"


def render_limitations_markdown(results: dict | None) -> str:
    """Build docs/LANGUAGE-LIMITATIONS.md from measured values only."""
    lines = [
        "# Language limitations (measured where stated)",
        "",
        "## Standing notices",
        "",
        "- HakiScribe shows the transcript as recognised. It does not "
        "translate, paraphrase or add words.",
        "- Accuracy can drop with accents, overlapping speech, background "
        "noise and mixed languages. Always verify against the audio.",
        "",
        "## Measured accuracy (batch ASR)",
        "",
        _settings_line(results),
        "",
    ]
    for key, label in CATEGORIES:
        entry = _category_entry(results, key)
        if entry:
            lines.append(
                f"- {label}: mean WER {_number(entry['wer'])} over "
                f"{entry['clips']} clips ({entry['ref_words']} reference "
                "words)."
            )
        else:
            lines.append(f"- {label}: {NOT_MEASURED} on Kenyan speech.")
    lines += [
        "",
        "## What this does not cover",
        "",
        "- Live microphone accuracy is not measured here.",
        "- Speaker attribution accuracy is reported per recording in the "
        "export view, not in this set.",
        "- Results change with the model, the language bias, and the "
        "recording conditions; re-run after any of those change.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """CLI entry: render both docs; int exit code (0, never invents)."""
    parser = argparse.ArgumentParser(
        description="Render measured evaluation results into docs."
    )
    parser.add_argument(
        "--results",
        default=str(_REPO_ROOT / "evaluation" / "results" / "latest.json"),
    )
    parser.add_argument(
        "--eval-doc", default=str(_REPO_ROOT / "docs" / "EVALUATION.md")
    )
    parser.add_argument(
        "--limits-doc",
        default=str(_REPO_ROOT / "docs" / "LANGUAGE-LIMITATIONS.md"),
    )
    args = parser.parse_args(argv[1:])
    results = load_results(args.results)
    eval_doc = Path(args.eval_doc)
    limits_doc = Path(args.limits_doc)
    eval_doc.parent.mkdir(parents=True, exist_ok=True)
    limits_doc.parent.mkdir(parents=True, exist_ok=True)
    eval_doc.write_text(
        render_evaluation_markdown(results), encoding="utf-8"
    )
    limits_doc.write_text(
        render_limitations_markdown(results), encoding="utf-8"
    )
    print(f"wrote {eval_doc} and {limits_doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
