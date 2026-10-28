# HakiScribe-AI — Clarity in Every Proceeding

Human-in-the-loop court transcription for Kenyan courts. Built for the **Meta Global Hackathon**.

> **RULE: AI proposes. HUMAN REVIEWS.** Nothing here is official. Every AI output is a draft.

> **SYNTHETIC DATA ONLY.** Every case, name, script, and document in this repo is fictional (`R v. SYNTHETIC John Doe`, CR 123/2026). No real litigants, no real court audio. See [demo-data/synthetic/README.md](demo-data/synthetic/README.md).

## The one workflow

Upload → Transcribe → Review → Export. Priority 1 (upload + transcribe) is live; the review desk and draft export are next. Design: [ARCHITECTURE-V2.md](docs/architecture/ARCHITECTURE-V2.md), [SCOPE-V2.md](docs/SCOPE-V2.md).

1. **Upload & validate** — synthetic audio (mp3, wav, m4a, aac, adts, ogg, opus, webm); type, size, and attestation checks; SHA-256 hashed and stored with a recording row.
2. **Transcribe** — Muse Voice Transcribe via Meta Model API (clearly-marked mock fallback offline); segments keep timestamps, speaker turns (Speaker A/B), and verbatim English/Kiswahili/code-switching. The API returns no confidence scores.
3. **Review desk (next)** — Spark flags, jump-to-audio, reviewer edits and per-segment decisions.
4. **Draft export + evaluation (next)** — watermarked DOCX draft with WER/CER against the reviewer's corrections.

## Component status

| Area | Status | Notes |
|---|---|---|
| Muse Voice Transcribe | Live | DIARIZATION turns + timestamps, no confidence from API (`backend/integrations/meta/voice_transcribe.py`) |
| Muse Spark review flags | Planned | Later step; the review desk shows an honest preview today |
| Corrections history | Planned | Repository ready; reviewer save flow is a later step |
| DOCX draft export | Planned | Later step; no generator yet |
| WER/CER evaluation | Planned | Later step; placeholders only |
| Muse Wonder explainer | Parked | `extras/`, not in the core workflow |
| Muse Image timeline | Parked | `extras/`, not in the core workflow |
| SAM 3.1 redaction | Parked | `extras/`, not in the core workflow |
| Muse Glimmer offline | Parked | `extras/`, not in the core workflow |

## Human-in-the-loop

- Single Reviewer role; a name is required on every decision.
- `text_original` is immutable — corrections are separate rows with reviewer, timestamp, before/after.
- The export is always a watermarked DRAFT, never a certified record.
- No certification, no deadlines, no legal advice anywhere in the system.

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # add your dev.meta.ai key, or leave blank for mock mode
streamlit run frontend/app.py
```

Demo flow (works fully offline in mock mode):

One-click demo: enter your reviewer name and press **Load demo recording**
(expects `demo-data/synthetic/case-cr-123-2026.wav`; generate it with
`scripts/make_demo_audio.ps1`).

1. Enter your reviewer name.
2. Upload a synthetic hearing file and tick the attestation box.
3. Transcribe (mock mode needs no key) and read the timestamped segments.

```bash
pytest   # 113 tests, all passing
```

## Project structure

```
frontend/app.py               # Streamlit Review Desk (Priority 1: upload + transcribe)
backend/core/config.py        # .env loading + Meta model names + key validation
backend/services/             # ingestion_service, transcription_service (review/export next)
backend/repositories/         # recordings, segments, flags, corrections, exports (only DB access)
backend/integrations/meta/    # voice_transcribe.py — the only Meta API call site
database/                     # SQLite schema + connection (data/hakiscribe.db, gitignored)
storage/uploads/  storage/exports/   # synthetic files only (gitignored)
data/                         # local SQLite file lives here (gitignored)
extras/                       # parked V1 client modules, reference only
docs/architecture/ARCHITECTURE-V2.md # layer design + schema
docs/SCOPE-V2.md              # submission scope + deferred list
demo-data/synthetic/          # fictional script + charge sheet + demo wav
scripts/make_demo_audio.ps1   # render the demo wav with Windows voices
tests/                        # test_database_v2, test_ingestion_v2, test_transcription_v2
```

## Configuration

| Variable | Purpose |
|---|---|
| `META_API_KEY` | dev.meta.ai key; blank/placeholder = mock mode |
| `META_API_BASE` | Model API base URL (default `https://api.meta.ai/v1`) |
| `META_VOICE_MODEL` | Voice Transcribe model name (live) |
| `META_VOICE_MODE` | `DIARIZATION` (default), `PUSH_TO_TALK`, or `ENDPOINTING` |
| `META_LANGUAGE_BIAS` | Comma list, e.g. `English,Kiswahili`; empty = not sent |
| `backend/core/keywords.txt` | One court term per line (max 50 x 40 chars); sent as `keywords` |
| `META_REASONING_MODEL` / `META_WONDER_MODEL` | Spark / Wonder model names (flagging next) |
| `META_SAM_MODEL` / `META_IMAGE_MODEL` / `META_OPEN_MODEL` / `GLIMMER_MODEL_PATH` | Parked-model settings (unused by V2 core) |
| `HAKISCRIBE_DB_PATH` | Override for the SQLite file (default `data/hakiscribe.db`) |

## Deferred scope

Deliberately not built for this submission ([SCOPE-V2.md](docs/SCOPE-V2.md)): certification and signatures, deadline prediction, legal advice, real-case data and Judiciary integrations, the Wonder public explainer, Image timelines, SAM redaction, and offline Glimmer.

## Build log

- [HACKATHON-LOG.md](HACKATHON-LOG.md) — proof of new work, steps 1–14.
- [MUSE-CODE-LOG.md](MUSE-CODE-LOG.md) — what was built with Muse Code.

## License

MIT — see [LICENSE](LICENSE).
