"""Guardrails for measured evaluation and honest limitation reporting."""

import ast
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from backend.core import config
from backend.integrations.meta.voice_transcribe import TranscriptionError
from backend.repositories import api_calls_repo
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


_PROVENANCE_CLIPS = (
    (
        "sw1",
        "kiswahili",
        b"RIFFswahili-audio-bytes-001",
        "mahakama imeahirishwa hadi kesho",
    ),
    (
        "en1",
        "english",
        b"RIFFenglish-audio-bytes-001",
        "court is now in session",
    ),
)


def _write_provenance_fixture(base: Path, version=1):
    """Two-clip eval fixture with deterministic audio; manifest path."""
    (base / "audio").mkdir(parents=True)
    (base / "reference").mkdir()
    clips = []
    for clip_id, category, audio_bytes, ref_text in _PROVENANCE_CLIPS:
        (base / "audio" / f"{clip_id}.wav").write_bytes(audio_bytes)
        (base / "reference" / f"{clip_id}.txt").write_text(
            ref_text, encoding="utf-8"
        )
        clips.append(
            {
                "id": clip_id,
                "category": category,
                "audio": f"audio/{clip_id}.wav",
                "reference": f"reference/{clip_id}.txt",
            }
        )
    manifest = {"clips": clips}
    if version is not None:
        manifest["version"] = version
    path = base / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def _exact_transcribe(audio_path):
    """Injected transcription returning each clip's reference text."""
    refs = {clip_id: text for clip_id, _, _, text in _PROVENANCE_CLIPS}
    return {
        "segments": [{"idx": 0, "text_original": refs[Path(audio_path).stem]}]
    }


def test_run_evaluation_records_version_and_injected_source(tmp_path):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_provenance_fixture(tmp_path / "eval")
    results = evaluate.run_evaluation(
        manifest, transcribe_fn=_exact_transcribe
    )
    assert results["manifest_version"] == 1
    assert results["transcription_source"] == "injected"
    assert results["counts"] == {"clips": 2}
    for key in (
        "run_at",
        "model",
        "mode",
        "language_bias",
        "keyword_count",
        "clips",
        "categories",
    ):
        assert key in results
    assert results["categories"]["kiswahili"]["wer"] == 0.0
    assert results["categories"]["english"]["wer"] == 0.0
    assert results["categories"]["code_switched"]["wer"] is None


@pytest.mark.parametrize(
    "version", [None, "1", 1.5, True, 0, -1, 2]
)
def test_run_evaluation_rejects_bad_manifest_version(tmp_path, version):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_provenance_fixture(tmp_path / "eval", version=version)
    with pytest.raises(ValueError, match="[Vv]ersion"):
        evaluate.run_evaluation(manifest, transcribe_fn=_exact_transcribe)


def test_run_evaluation_records_audio_sha256(tmp_path):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_provenance_fixture(tmp_path / "eval")
    results = evaluate.run_evaluation(
        manifest, transcribe_fn=_exact_transcribe
    )
    by_id = {clip["id"]: clip for clip in results["clips"]}
    for clip_id, _, audio_bytes, _ in _PROVENANCE_CLIPS:
        expected = hashlib.sha256(audio_bytes).hexdigest()
        assert by_id[clip_id]["audio_sha256"] == expected
        assert len(expected) == 64
        assert expected == expected.lower()


def test_audio_sha256_changes_with_audio_bytes(tmp_path):
    evaluate = _load_script("evaluate_asr")
    base = tmp_path / "eval"
    manifest = _write_provenance_fixture(base)
    first = evaluate.run_evaluation(manifest, transcribe_fn=_exact_transcribe)
    changed_bytes = b"RIFFswahili-audio-bytes-002"
    (base / "audio" / "sw1.wav").write_bytes(changed_bytes)
    second = evaluate.run_evaluation(manifest, transcribe_fn=_exact_transcribe)
    first_by_id = {clip["id"]: clip for clip in first["clips"]}
    second_by_id = {clip["id"]: clip for clip in second["clips"]}
    assert second_by_id["sw1"]["audio_sha256"] == hashlib.sha256(
        changed_bytes
    ).hexdigest()
    assert (
        second_by_id["sw1"]["audio_sha256"]
        != first_by_id["sw1"]["audio_sha256"]
    )
    assert (
        second_by_id["en1"]["audio_sha256"]
        == first_by_id["en1"]["audio_sha256"]
    )


def test_default_path_reports_provider_integration(tmp_path, monkeypatch):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_provenance_fixture(tmp_path / "eval")
    calls = []

    def fake_integration(audio_path, on_attempt=None):
        calls.append(audio_path)
        assert callable(on_attempt)
        return {
            "segments": [{"idx": 0, "text_original": "court is now in session"}]
        }

    monkeypatch.setattr(
        evaluate.voice_transcribe, "transcribe_audio_file", fake_integration
    )
    results = evaluate.run_evaluation(manifest)
    assert results["transcription_source"] == "provider_integration"
    assert results["manifest_version"] == 1
    assert len(calls) == 2
    assert all(str(call).endswith(".wav") for call in calls)
    assert results["categories"]["english"]["wer"] == 0.0


class _FakeEvalResponse:
    """Minimal requests.post stand-in (no network)."""

    def __init__(self, status_code, payload=None, headers=None, body=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = body

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON here")
        return self._payload


_VALID_DIARIZATION = {
    "sessionId": "eval-session",
    "transcript": "court is now in session",
    "audioDurationMs": 4000,
    "turns": [
        {
            "turnId": 0,
            "startMs": 0,
            "endMs": 4000,
            "transcript": "court is now in session",
            "speaker": "A",
        }
    ],
}


def _write_single_clip_fixture(
    base: Path,
    audio_bytes=b"RIFFsingle-clip-audio",
    ref_text="court is now in session",
):
    """One-clip eval fixture; manifest path."""
    (base / "audio").mkdir(parents=True)
    (base / "reference").mkdir()
    (base / "audio" / "s1.wav").write_bytes(audio_bytes)
    (base / "reference" / "s1.txt").write_text(ref_text, encoding="utf-8")
    manifest = {
        "version": 1,
        "clips": [
            {
                "id": "s1",
                "category": "english",
                "audio": "audio/s1.wav",
                "reference": "reference/s1.txt",
            }
        ],
    }
    path = base / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def _passthrough_wav(src, dst):
    """prepare_wav stand-in: copy bytes without audio tooling."""
    data = Path(src).read_bytes()
    Path(dst).write_bytes(data)
    return Path(dst)


def _patch_provider_path(monkeypatch, evaluate, post):
    """Fake HTTP + configured key + no-op WAV prep (no network)."""
    monkeypatch.setattr(
        "backend.integrations.meta.voice_transcribe.requests.post", post
    )
    monkeypatch.setattr(
        evaluate.voice_transcribe.config, "is_configured", lambda: True
    )
    monkeypatch.setattr(
        evaluate.voice_transcribe, "prepare_wav", _passthrough_wav
    )


def _ledger_rows(db_path):
    """All api_calls rows, oldest first."""
    rows = api_calls_repo.list_recent_api_calls(limit=500, db_path=db_path)
    return sorted(rows, key=lambda row: row["id"])


def test_injected_transcription_creates_no_ledger_rows(tmp_path):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_provenance_fixture(tmp_path / "eval")
    db_path = tmp_path / "ledger.db"
    results = evaluate.run_evaluation(
        manifest, transcribe_fn=_exact_transcribe, db_path=db_path
    )
    assert results["transcription_source"] == "injected"
    assert results["manifest_version"] == 1
    assert results["counts"] == {"clips": 2}
    assert results["categories"]["english"]["wer"] == 0.0
    for clip in results["clips"]:
        assert len(clip["audio_sha256"]) == 64
    assert _ledger_rows(db_path) == []


def test_default_path_records_successful_attempt(tmp_path, monkeypatch):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_single_clip_fixture(tmp_path / "eval")
    db_path = tmp_path / "ledger.db"

    def post(url, headers=None, files=None, timeout=None):
        return _FakeEvalResponse(200, dict(_VALID_DIARIZATION))

    _patch_provider_path(monkeypatch, evaluate, post)
    results = evaluate.run_evaluation(manifest, db_path=db_path)
    assert results["transcription_source"] == "provider_integration"
    assert results["categories"]["english"]["wer"] == 0.0
    rows = _ledger_rows(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "meta"
    assert row["model"] == config.META_VOICE_MODEL
    assert row["endpoint_path"] == "/asr/transcribe"
    assert row["mode"] == config.get_voice_mode()
    assert row["http_status"] == 200
    assert row["ok"] == 1
    assert row["recording_id"] is None
    assert row["error_code"] is None
    assert row["audio_bytes"] == len(b"RIFFsingle-clip-audio")


def test_retry_then_success_records_two_rows(tmp_path, monkeypatch):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_single_clip_fixture(tmp_path / "eval")
    db_path = tmp_path / "ledger.db"
    planned = [
        _FakeEvalResponse(429, headers={"Retry-After": "0"}),
        _FakeEvalResponse(200, dict(_VALID_DIARIZATION)),
    ]

    def post(url, headers=None, files=None, timeout=None):
        return planned.pop(0)

    _patch_provider_path(monkeypatch, evaluate, post)
    evaluate.run_evaluation(manifest, db_path=db_path)
    rows = _ledger_rows(db_path)
    assert len(rows) == 2
    assert rows[0]["http_status"] == 429
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "HTTP_429"
    assert rows[1]["http_status"] == 200
    assert rows[1]["ok"] == 1
    assert rows[1]["error_code"] is None


def test_http_400_records_failure_and_raises(tmp_path, monkeypatch):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_single_clip_fixture(tmp_path / "eval")
    db_path = tmp_path / "ledger.db"

    def post(url, headers=None, files=None, timeout=None):
        return _FakeEvalResponse(400, body='{"error": "bad request"}')

    _patch_provider_path(monkeypatch, evaluate, post)
    with pytest.raises(TranscriptionError):
        evaluate.run_evaluation(manifest, db_path=db_path)
    rows = _ledger_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["http_status"] == 400
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "HTTP_400"


def test_mock_mode_records_nothing(tmp_path, monkeypatch):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_single_clip_fixture(tmp_path / "eval")
    db_path = tmp_path / "ledger.db"
    monkeypatch.setattr(
        evaluate.voice_transcribe.config, "is_configured", lambda: False
    )
    results = evaluate.run_evaluation(manifest, db_path=db_path)
    assert results["transcription_source"] == "provider_integration"
    assert results["counts"] == {"clips": 1}
    assert _ledger_rows(db_path) == []


def test_malformed_json_records_parse_error(tmp_path, monkeypatch):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_single_clip_fixture(tmp_path / "eval")
    db_path = tmp_path / "ledger.db"

    def post(url, headers=None, files=None, timeout=None):
        return _FakeEvalResponse(200, body="not json{{{ skewed")

    _patch_provider_path(monkeypatch, evaluate, post)
    with pytest.raises(TranscriptionError, match="not valid JSON"):
        evaluate.run_evaluation(manifest, db_path=db_path)
    rows = _ledger_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "PARSE_ERROR"


def test_invalid_response_records_invalid_response(tmp_path, monkeypatch):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_single_clip_fixture(tmp_path / "eval")
    db_path = tmp_path / "ledger.db"

    def post(url, headers=None, files=None, timeout=None):
        return _FakeEvalResponse(200, {"transcript": "", "turns": []})

    _patch_provider_path(monkeypatch, evaluate, post)
    with pytest.raises(TranscriptionError, match="no turns or transcript"):
        evaluate.run_evaluation(manifest, db_path=db_path)
    rows = _ledger_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["ok"] == 0
    assert rows[0]["error_code"] == "INVALID_RESPONSE"


def test_explicit_db_path_is_honored(tmp_path, monkeypatch):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_single_clip_fixture(tmp_path / "eval")
    used = tmp_path / "used.db"
    untouched = tmp_path / "untouched.db"

    def post(url, headers=None, files=None, timeout=None):
        return _FakeEvalResponse(200, dict(_VALID_DIARIZATION))

    _patch_provider_path(monkeypatch, evaluate, post)
    evaluate.run_evaluation(manifest, db_path=used)
    assert len(_ledger_rows(used)) == 1
    assert not untouched.exists()


def test_fake_key_absent_from_ledger(tmp_path, monkeypatch):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_single_clip_fixture(tmp_path / "eval")
    db_path = tmp_path / "ledger.db"
    fake_key = "EVAL-FAKE-KEY-999"
    monkeypatch.setattr(config, "META_API_KEY", fake_key)

    def post(url, headers=None, files=None, timeout=None):
        assert fake_key in headers.get("Authorization", "")
        return _FakeEvalResponse(400, body=f"bad key {fake_key} rejected")

    _patch_provider_path(monkeypatch, evaluate, post)
    with pytest.raises(TranscriptionError):
        evaluate.run_evaluation(manifest, db_path=db_path)
    rows = _ledger_rows(db_path)
    assert len(rows) == 1
    assert fake_key not in json.dumps(rows)


def test_main_db_path_wires_ledger(tmp_path, monkeypatch):
    evaluate = _load_script("evaluate_asr")
    manifest = _write_provenance_fixture(tmp_path / "eval")
    db_path = tmp_path / "ledger.db"
    out_dir = tmp_path / "results"

    def post(url, headers=None, files=None, timeout=None):
        return _FakeEvalResponse(200, dict(_VALID_DIARIZATION))

    _patch_provider_path(monkeypatch, evaluate, post)
    monkeypatch.setattr(evaluate, "is_configured", lambda: True)
    code = evaluate.main(
        [
            "evaluate_asr.py",
            "--manifest",
            str(manifest),
            "--results-dir",
            str(out_dir),
            "--db-path",
            str(db_path),
        ]
    )
    assert code == 0
    assert (out_dir / "latest.json").is_file()
    assert len(_ledger_rows(db_path)) == 2
