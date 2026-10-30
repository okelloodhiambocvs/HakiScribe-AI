"""Measure batch ASR accuracy on the Kenyan-language evaluation set.

Runs every clip in evaluation/manifest.json through the REAL batch
endpoint (the same transcribe_audio_file code path the app uses, with
DIARIZATION and the configured keywords/language bias), scores WER/CER
with evaluation_service normalisation (diacritics preserved, no
translation), and writes evaluation/results/latest.json. Nothing is
ever invented: a missing clip, a missing API key, or an API failure
exits non-zero without writing.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.core import config  # noqa: E402
from backend.core.config import is_configured  # noqa: E402
from backend.integrations.meta import voice_transcribe  # noqa: E402
from backend.repositories import api_calls_repo  # noqa: E402
from backend.services import evaluation_service  # noqa: E402

CATEGORIES = ("english", "kiswahili", "code_switched")
SUPPORTED_MANIFEST_VERSION = 1
_HASH_CHUNK_BYTES = 65536


def _load_manifest(path: Path) -> dict:
    """Load and shape-check the manifest; raise on any problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FileNotFoundError(f"manifest not found: {path}") from exc
    try:
        manifest = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"manifest is not valid JSON: {path}") from exc
    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("clips"), list
    ):
        raise ValueError(f'manifest must be {{"clips": [...]}}: {path}')
    return manifest


def _manifest_version(manifest: dict, path: Path) -> int:
    """Return the manifest version; reject missing/invalid/unsupported."""
    version = manifest.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError(f"manifest version must be an integer: {path}")
    if version <= 0:
        raise ValueError(f"manifest version must be positive: {path}")
    if version != SUPPORTED_MANIFEST_VERSION:
        raise ValueError(
            f"unsupported manifest version {version}: {path} "
            f"(supported: {SUPPORTED_MANIFEST_VERSION})"
        )
    return version


def _sha256_of_file(path: Path) -> str:
    """Lowercase hex SHA-256 of a file, read in fixed-size chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _attempt_recorder(db_path):
    """Build the integration's per-attempt callback (persists via repo).

    Mirrors the transcription service recorder; evaluation clips are
    not recordings, so recording_id stays NULL.
    """

    def record(info: dict) -> None:
        api_calls_repo.create_api_call(
            provider="meta",
            model=config.META_VOICE_MODEL,
            endpoint_path=voice_transcribe.ENDPOINT_PATH,
            mode=config.get_voice_mode(),
            recording_id=None,
            http_status=info.get("http_status"),
            ok=bool(info.get("ok")),
            latency_ms=info.get("latency_ms"),
            audio_bytes=info.get("audio_bytes"),
            audio_ms=info.get("audio_ms"),
            request_id=info.get("request_id"),
            error_code=info.get("error_code"),
            db_path=db_path,
        )

    return record


def _validate_clip(entry: object) -> dict:
    """Check one manifest entry has id, category, audio, reference."""
    if not isinstance(entry, dict):
        raise ValueError(f"clip entry must be an object: {entry!r}")
    for key in ("id", "category", "audio", "reference"):
        if not entry.get(key):
            raise ValueError(f"clip entry missing {key!r}: {entry!r}")
    if entry["category"] not in CATEGORIES:
        raise ValueError(
            f"clip {entry['id']!r} has unknown category "
            f"{entry['category']!r}"
        )
    return entry


def run_evaluation(
    manifest_path, *, transcribe_fn=None, db_path=None
) -> dict:
    """Transcribe and score every clip; return the results document.

    transcribe_fn(audio_path) defaults to the real batch code path and
    must return {"segments": [{"idx", "text_original", ...}]}. Raises
    FileNotFoundError for missing clip files (never partial results)
    and ValueError for a missing, invalid, or unsupported manifest
    version. transcription_source names the selected code path only;
    it is not proof of an external provider request. On the default
    path, provider attempts are recorded in the api_calls ledger via
    the integration callback (recording_id NULL); injected functions
    and mock mode record nothing.
    """
    manifest_path = Path(manifest_path)
    base = manifest_path.parent
    manifest = _load_manifest(manifest_path)
    version = _manifest_version(manifest, manifest_path)
    clips = [_validate_clip(entry) for entry in manifest["clips"]]
    if transcribe_fn is None:
        transcribe = voice_transcribe.transcribe_audio_file
        transcription_source = "provider_integration"
        on_attempt = _attempt_recorder(db_path)
    else:
        transcribe = transcribe_fn
        transcription_source = "injected"
        on_attempt = None
    scored = []
    for clip in clips:
        audio_path = base / clip["audio"]
        ref_path = base / clip["reference"]
        if not audio_path.is_file():
            raise FileNotFoundError(
                f"clip {clip['id']!r}: audio file missing: {audio_path}"
            )
        if not ref_path.is_file():
            raise FileNotFoundError(
                f"clip {clip['id']!r}: reference file missing: {ref_path}"
            )
        reference = ref_path.read_text(encoding="utf-8").strip()
        audio_sha256 = _sha256_of_file(audio_path)
        if on_attempt is None:
            result = transcribe(str(audio_path))
        else:
            result = transcribe(str(audio_path), on_attempt=on_attempt)
        segments = sorted(
            result.get("segments", []), key=lambda item: item.get("idx", 0)
        )
        hypothesis = " ".join(
            item.get("text_original", "") for item in segments
        ).strip()
        scored.append(
            {
                "id": clip["id"],
                "category": clip["category"],
                "wer": round(
                    evaluation_service.wer(reference, hypothesis), 4
                ),
                "cer": round(
                    evaluation_service.cer(reference, hypothesis), 4
                ),
                "ref_words": len(
                    evaluation_service.normalize_text(reference).split()
                ),
                "hyp_words": len(
                    evaluation_service.normalize_text(hypothesis).split()
                ),
                "audio_sha256": audio_sha256,
                "hypothesis": hypothesis,
            }
        )
        print(
            f"scored {clip['id']} ({clip['category']}): "
            f"WER {scored[-1]['wer']:.4f} CER {scored[-1]['cer']:.4f}",
            flush=True,
        )
    categories = {}
    for category in CATEGORIES:
        group = [item for item in scored if item["category"] == category]
        if group:
            categories[category] = {
                "clips": len(group),
                "wer": round(
                    sum(item["wer"] for item in group) / len(group), 4
                ),
                "cer": round(
                    sum(item["cer"] for item in group) / len(group), 4
                ),
                "ref_words": sum(item["ref_words"] for item in group),
            }
        else:
            categories[category] = {
                "clips": 0,
                "wer": None,
                "cer": None,
                "ref_words": 0,
            }
    return {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": config.META_VOICE_MODEL,
        "mode": config.get_voice_mode(),
        "language_bias": config.get_language_bias(),
        "keyword_count": len(config.get_keywords()),
        "manifest_version": version,
        "transcription_source": transcription_source,
        "counts": {"clips": len(scored)},
        "clips": scored,
        "categories": categories,
    }


def main(argv: list[str]) -> int:
    """CLI entry: parse args, run, write latest.json; int exit code."""
    parser = argparse.ArgumentParser(
        description="Measure batch ASR WER/CER on the evaluation set."
    )
    parser.add_argument(
        "--manifest",
        default=str(_REPO_ROOT / "evaluation" / "manifest.json"),
    )
    parser.add_argument(
        "--results-dir",
        default=str(_REPO_ROOT / "evaluation" / "results"),
    )
    parser.add_argument(
        "--language-bias",
        default=None,
        help="Comma-separated languageBias override for this run "
        "(default: the configured value).",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="API-call ledger database (default: the application's "
        "normal database resolution).",
    )
    args = parser.parse_args(argv[1:])
    if args.language_bias is not None:
        config.META_LANGUAGE_BIAS = args.language_bias
    if not is_configured():
        print("error: META_API_KEY is not set; refusing to invent results")
        return 1
    try:
        results = run_evaluation(args.manifest, db_path=args.db_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        return 1
    except Exception as exc:
        print(f"error: transcription failed: {exc}")
        return 1
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / "latest.json"
    out_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_path} ({results['counts']['clips']} clips)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
