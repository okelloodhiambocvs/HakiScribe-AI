# HakiScribe-AI — Clarity in Every Proceeding

Human-in-the-loop court transcription for Kenyan courts. Built for the **Meta Global Hackathon**.

> **RULE: AI proposes. HUMAN disposes.** No transcript is final until a Clerk verifies it and a Magistrate certifies it. No auto-certify, ever.

> **SYNTHETIC DATA ONLY.** Every case, name, script, and document in this repo is fictional (`R v. SYNTHETIC John Doe`, CR 123/2026). No real litigants, no real court audio. See [demo-data/synthetic/README.md](demo-data/synthetic/README.md).

## What it does

Noisy courtroom audio goes in; a certified, hash-sealed court record comes out — with a plain-language explainer for the citizen, a visual case timeline, and redacted public copies. Every AI output is a **draft** that a named human must review, edit, or approve before it counts.

Pipeline ([ARCHITECTURE.md](ARCHITECTURE.md)):

1. **Transcribe** — court audio → speaker segments with timestamps + confidence.
2. **Structure & flag** — speakers normalized, low-confidence segments flagged, appeal deadlines suggested.
3. **Human loop** — Clerk reviews every flagged segment → Magistrate certifies (must be a different person) → SHA-256 sealed record + audit log.
4. **Serve the citizen** — Kiswahili/English explainer, visual timeline, certified PDF, redacted public copies. All blocked until certification.

## Meta models used

| Model | Role | Module |
|---|---|---|
| Muse Voice Transcribe | en-KE/sw-KE transcription with diarization + word confidence | `src/transcription/client.py` |
| Muse Spark | Structurer (speakers/case no.), Guardian (`[VERIFY]` flags < 0.75), Deadline (14/60-day appeal windows) | `src/agents/` |
| Muse Wonder | Mwananchi explainer — certified outcomes in plain English + Kiswahili | `src/explainer/` |
| SAM 3.1 | Charge-sheet segmentation; masks signature + ID number for public copies | `src/vision/` |
| Muse Image | Visual case timeline infographic (hearing → review → certify → deadlines) | `src/timeline/` |
| Muse Glimmer (open weights) | **Local, offline** PII redaction on the court laptop — no internet | `src/offline/` |

Every client follows the same pattern: real Meta Model API call when `META_API_KEY` is configured, clearly-marked synthetic mock fallback when offline — and `needs_human_review=True` on all AI output either way.

## Human-in-the-loop locks

- Clerk reviews **per segment** (no bulk approve), name required for accountability.
- Magistrate can certify only after Clerk completes, and must be a **different person**.
- Explainer, timeline, and PDF export are **blocked until certified**; every approval is named and audit-logged.
- Final record is SHA-256 hashed over `final_text + clerk + magistrate`.

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # add your dev.meta.ai key, or leave blank for mock mode
streamlit run app.py
```

Demo flow (works fully offline in mock mode):

1. Enter a Clerk name and a *different* Magistrate name.
2. **Load Synthetic Demo CR 123/2026** → AI draft v1 (NOT certified).
3. Clerk confirms/edits each flagged segment → **Clerk Complete Review**.
4. **Magistrate CERTIFY** → sealed record + hash.
5. Generate the Mwananchi explainer, visual timeline, certified PDF, and redactions — each needs human approval.

Optional: record teammates reading [the 2-minute script](demo-data/synthetic/case-cr-123-2026-script.md) as `demo-data/synthetic/cr-123-mock.mp3`.

```bash
pytest   # 32 tests, all passing
```

## Project structure

```
app.py                    # Streamlit human-in-the-loop UI
src/transcription/        # Muse Voice Transcribe client
src/agents/               # Muse Spark: structurer, guardian, deadline
src/verification/         # Clerk/Magistrate review service + audit log + hash
src/explainer/            # Muse Wonder EN/SW explainer (post-certification)
src/timeline/             # Muse Image visual timeline (post-certification)
src/export/               # Certified PDF export (human only)
src/vision/               # SAM 3.1 charge-sheet redaction drafts
src/offline/              # Glimmer local offline PII redaction
src/utils/config.py       # .env plumbing + key validation
demo-data/synthetic/      # Fictional case script + charge sheet
tests/                    # pytest suite incl. end-to-end certification flow
```

## Configuration

| Variable | Purpose |
|---|---|
| `META_API_KEY` | dev.meta.ai key; blank/placeholder = mock mode |
| `META_API_BASE` | Model API base URL (default `https://dev.meta.ai/model-api/v1`) |
| `META_VOICE_MODEL` / `META_REASONING_MODEL` | Voice Transcribe / Spark model names |
| `META_WONDER_MODEL` / `META_SAM_MODEL` / `META_IMAGE_MODEL` / `META_OPEN_MODEL` | Wonder / SAM 3.1 / Image / Glimmer model names |
| `GLIMMER_MODEL_PATH` | Local open-weights path; if set, Glimmer runs on-device |

## Build log

- [HACKATHON-LOG.md](HACKATHON-LOG.md) — proof of new work, steps 1–8.
- [MUSE-CODE-LOG.md](MUSE-CODE-LOG.md) — what was built with Muse Code.

## License

MIT — see [LICENSE](LICENSE).
