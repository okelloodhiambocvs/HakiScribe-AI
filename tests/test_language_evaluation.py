"""Guardrails for measured evaluation and honest limitation reporting."""

import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from backend.core import config
from backend.services import evaluation_service, review_prompt
from frontend.components import language_notes

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "frontend" / "app.py"
_FIXTURE_RESULTS = {
    "run_at": "2026-10-29T12:00:00+00:00",
    "model": "muse-voice-transcribe-1.0",
    "mode": "DIARIZATION",
    "language_bias": ["English"],
    "keyword_count": 12,
    "counts": {"clips": 3},
    "clips": [
        {
            "id": "en-1",
            "category": "english",
            "wer": 0.1,
            "cer": 0.02,
            "ref_words": 40,
            "hyp_words": 40,
            "hypothesis": "court is now in session",
        },
        {
            "id": "en-2",
            "category": "english",
            "wer": 0.2,
            "cer": 0.05,
            "ref_words": 50,
            "hyp_words": 51,
            "hypothesis": "court is now in session",
        },
        {
            "id": "sw-1",
            "category": "kiswahili",
            "wer": 0.35,
            "cer": 0.12,
            "ref_words": 30,
            "hyp_words": 29,
            "hypothesis": "mahakama imeahirishwa",
        },
    ],
    "categories": {
        "english": {"clips": 2, "wer": 0.15, "cer": 0.035, "ref_words": 90},
        "kiswahili": {"clips": 1, "wer": 0.35, "cer": 0.12, "ref_words": 30},
        "code_switched": {"clips": 0, "wer": None, "cer": None, "ref_words": 0},
    },
}


def _load_script(name: str):
    """Load a scripts/<name>.py module without running its __main__."""
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _visible_text(app: AppTest) -> str:
    """All user-visible strings (walkers include expander children)."""
    chunks = []
    for group in (
        "header",
        "subheader",
        "markdown",
        "caption",
        "info",
        "success",
        "warning",
        "expander",
    ):
        widgets = getattr(app, group)
        for index in range(len(widgets)):
            widget = widgets[index]
            text = widget.label if group == "expander" else widget.value
            chunks.append(str(text))
    return "\n".join(chunks)


def test_review_prompt_forbids_translation_and_preserves_code_switching():
    text = review_prompt.SYSTEM_PROMPT.lower()
    assert "never translate" in text
    assert "paraphrase" in text
    assert "code-switching" in text
    assert "exactly as written" in text


_UPDATE_SET_ORIGINAL = re.compile(
    r"\bUPDATE\b.{0,300}\bSET\b.{0,300}text_original",
    re.IGNORECASE | re.DOTALL,
)


def _is_original_store(target) -> bool:
    """True for `x["text_original"] = ...` / `.text_original = ...`."""
    if isinstance(target, ast.Subscript):
        return (
            isinstance(target.slice, ast.Constant)
            and target.slice.value == "text_original"
        )
    if isinstance(target, ast.Attribute):
        return target.attr == "text_original"
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_is_original_store(elt) for elt in target.elts)
    if isinstance(target, ast.Starred):
        return _is_original_store(target.value)
    return False


def test_no_code_path_writes_text_original():
    offenders = []
    for part in ("backend", "database", "frontend", "scripts"):
        for path in sorted((ROOT / part).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = (
                        [node.target]
                        if isinstance(node, (ast.AnnAssign, ast.AugAssign))
                        else node.targets
                    )
                    for target in targets:
                        if _is_original_store(target):
                            offenders.append(f"{rel}: assigns text_original")
                elif isinstance(node, ast.NamedExpr):
                    if _is_original_store(node.target):
                        offenders.append(f"{rel}: assigns text_original")
                elif isinstance(node, ast.Constant) and isinstance(
                    node.value, str
                ):
                    if _UPDATE_SET_ORIGINAL.search(node.value):
                        offenders.append(f"{rel}: UPDATE..SET text_original")
                elif isinstance(node, ast.JoinedStr):
                    text = "".join(
                        value.value
                        for value in node.values
                        if isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    )
                    if _UPDATE_SET_ORIGINAL.search(text):
                        offenders.append(f"{rel}: UPDATE..SET text_original")
    assert offenders == []


def test_panel_shows_not_measured_when_results_absent(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "HAKISCRIBE_EVAL_RESULTS", str(tmp_path / "missing.json")
    )
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["current_step"] = "transcribe"
    app.run()
    assert not app.exception
    text = _visible_text(app)
    assert "Language and accuracy notes" in text
    assert "Not yet measured on Kenyan speech" in text
    assert "It does not translate, paraphrase or add words." in text
    assert "Always verify against the audio." in text


def test_panel_helpers_read_measured_wer(monkeypatch, tmp_path):
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(_FIXTURE_RESULTS))
    monkeypatch.setenv("HAKISCRIBE_EVAL_RESULTS", str(path))
    results = language_notes.load_eval_results()
    assert language_notes.category_wer(results, "english") == 0.15
    assert language_notes.category_wer(results, "kiswahili") == 0.35
    assert language_notes.category_wer(results, "code_switched") is None
    assert language_notes.category_wer(None, "english") is None


def test_render_round_trip_only_measured_numbers(tmp_path):
    render = _load_script("render_evaluation_doc")
    results_path = tmp_path / "latest.json"
    fixture_text = json.dumps(_FIXTURE_RESULTS, indent=2)
    results_path.write_text(fixture_text)
    eval_doc = tmp_path / "EVALUATION.md"
    limits_doc = tmp_path / "LANGUAGE-LIMITATIONS.md"
    assert (
        render.main(
            [
                "render_evaluation_doc.py",
                "--results",
                str(results_path),
                "--eval-doc",
                str(eval_doc),
                "--limits-doc",
                str(limits_doc),
            ]
        )
        == 0
    )
    eval_text = eval_doc.read_text(encoding="utf-8")
    limits_text = limits_doc.read_text(encoding="utf-8")
    for value in (0.1, 0.2, 0.35, 0.15, 0.02, 0.05, 0.12, 0.035):
        assert repr(value) in eval_text
    assert "Not yet measured" in eval_text
    assert "Not yet measured" in limits_text
    assert "0.15" in limits_text
    for token in set(re.findall(r"\d+\.\d+", eval_text + limits_text)):
        assert token in fixture_text, f"unmeasured number {token}"


def test_render_without_results_says_not_measured(tmp_path):
    render = _load_script("render_evaluation_doc")
    eval_doc = tmp_path / "EVALUATION.md"
    limits_doc = tmp_path / "LANGUAGE-LIMITATIONS.md"
    assert (
        render.main(
            [
                "render_evaluation_doc.py",
                "--results",
                str(tmp_path / "nope.json"),
                "--eval-doc",
                str(eval_doc),
                "--limits-doc",
                str(limits_doc),
            ]
        )
        == 0
    )
    assert "Not yet measured" in eval_doc.read_text(encoding="utf-8")
    assert "No evaluation run yet" in limits_doc.read_text(encoding="utf-8")


def test_evaluate_fake_backend_category_averages(tmp_path):
    evaluate = _load_script("evaluate_asr")
    base = tmp_path / "eval"
    (base / "audio").mkdir(parents=True)
    (base / "reference").mkdir()
    refs = {
        "en1": "court is now in session",
        "en2": "the complainant is present today",
        "sw1": "mahakama imeahirishwa hadi kesho",
    }
    hyps = {
        "en1": "court is now in session",
        "en2": "court is now in session",
        "sw1": "mahakama imeahirishwa hadi kesho",
    }
    clips = []
    for clip_id, category in (
        ("en1", "english"),
        ("en2", "english"),
        ("sw1", "kiswahili"),
    ):
        (base / "audio" / f"{clip_id}.wav").write_bytes(b"RIFFfake")
        (base / "reference" / f"{clip_id}.txt").write_text(
            refs[clip_id], encoding="utf-8"
        )
        clips.append(
            {
                "id": clip_id,
                "category": category,
                "audio": f"audio/{clip_id}.wav",
                "reference": f"reference/{clip_id}.txt",
            }
        )
    (base / "manifest.json").write_text(json.dumps({"version": 1, "clips": clips}))

    def fake_transcribe(audio_path):
        stem = Path(audio_path).stem
        return {"segments": [{"idx": 0, "text_original": hyps[stem]}]}

    results = evaluate.run_evaluation(
        base / "manifest.json", transcribe_fn=fake_transcribe
    )
    expected_en2 = evaluation_service.wer(refs["en2"], hyps["en2"])
    assert results["counts"] == {"clips": 3}
    assert results["model"] == config.META_VOICE_MODEL
    assert results["mode"] == config.get_voice_mode()
    assert results["language_bias"] == config.get_language_bias()
    assert results["categories"]["english"]["clips"] == 2
    assert results["categories"]["english"]["wer"] == round(
        round(expected_en2, 4) / 2, 4
    )
    assert results["categories"]["kiswahili"]["wer"] == 0.0
    assert results["categories"]["code_switched"]["clips"] == 0
    assert results["categories"]["code_switched"]["wer"] is None


def test_evaluate_main_refuses_without_key(monkeypatch, tmp_path):
    evaluate = _load_script("evaluate_asr")
    monkeypatch.setattr(evaluate, "is_configured", lambda: False)
    out = tmp_path / "results"
    assert (
        evaluate.main(
            [
                "evaluate_asr.py",
                "--manifest",
                str(tmp_path / "manifest.json"),
                "--results-dir",
                str(out),
            ]
        )
        == 1
    )
    assert not (out / "latest.json").exists()


def test_evaluate_main_exits_nonzero_when_clip_missing(monkeypatch, tmp_path):
    evaluate = _load_script("evaluate_asr")
    monkeypatch.setattr(evaluate, "is_configured", lambda: True)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "clips": [
                    {
                        "id": "x",
                        "category": "english",
                        "audio": "audio/x.wav",
                        "reference": "reference/x.txt",
                    }
                ],
            }
        )
    )
    out = tmp_path / "results"
    assert (
        evaluate.main(
            [
                "evaluate_asr.py",
                "--manifest",
                str(manifest),
                "--results-dir",
                str(out),
            ]
        )
        == 1
    )
    assert not (out / "latest.json").exists()


def test_shipped_manifest_is_valid():
    manifest = json.loads(
        (ROOT / "evaluation" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == 1
    assert isinstance(manifest["clips"], list)
    for clip in manifest["clips"]:
        assert clip["category"] in ("english", "kiswahili", "code_switched")
        assert (ROOT / "evaluation" / clip["audio"]).is_file()
        assert (ROOT / "evaluation" / clip["reference"]).is_file()
