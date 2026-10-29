# Judge demo - 5-minute script

## Pre-demo checklist

- [ ] Fresh terminal: `python -m venv .venv`, activate, `pip install -r requirements.txt`.
- [ ] `copy .env.example .env` — add a real `META_API_KEY` for live calls, or leave blank for labelled mock mode.
- [ ] `python scripts/check_setup.py` exits 0 (mock mode passes with an empty key).
- [ ] Demo audio ready: `demo-data/synthetic/case-cr-123-2026.wav` (render with `scripts/make_demo_audio.ps1` if missing).
- [ ] Optional clean slate: delete `data/hakiscribe.db` and `storage/uploads/*` (keeps `.gitkeep`) for a fresh database.
- [ ] `streamlit run frontend/app.py` loads with no exception.
- [ ] Tab 2 ready (optional): `docs/API-EVIDENCE.md` regenerated via `python scripts/generate_api_evidence.py`.

## Timed script

### 0:00 - 0:30 — Setup and promise
Enter reviewer name. Read the banner aloud: synthetic demo only, AI
proposes, human reviews, not an official court record. Point at the
stepper: Upload → Transcribe → Review → Export.

### 0:30 - 1:30 — Upload and transcribe
Press **Load demo recording** (or upload a synthetic file + attestation).
Note the privacy notice: audio goes to the Meta Model API. Press
**Transcribe Recording**. Read one turn aloud: speaker label, time
range, verbatim mixed English/Kiswahili. Point at the REAL/MOCK badge.

### 1:30 - 2:30 — AI review
Open **Review Desk**. Press **Run AI review**. Read the counts (created,
dropped) and the line: flags are suggestions, not proof of error. Open
one flag: type, quoted evidence, message, suggestion.

### 2:30 - 3:45 — Human decides
Select the flagged segment. Play exactly that passage (jump-to-audio).
Show original (read-only) vs editable text and the diff. Edit one word,
give a reason, save. Assign a speaker role. Open the history timeline:
who, when, before → after, reason. Point at the unresolved-issues panel.

### 3:45 - 4:30 — Draft export and measurement
Open **Draft & Evaluation**. Press **Generate draft DOCX**, download it.
Show the DRAFT watermark, the correction log, and the unresolved list.
Read the metrics panel: AI-vs-reviewed WER/CER, traceability, review
time. State plainly: not a certified record.

### 4:30 - 5:00 — Honesty close
Open **About Us**: problem, approach, scope table (Live vs Not built).
If asked about accuracy: open `docs/EVALUATION.md` — only measured
numbers, everything else says "Not yet measured". If asked about real
calls: open `docs/API-EVIDENCE.md`. Close: AI proposes, human reviews.
