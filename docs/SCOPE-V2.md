# HakiScribe-AI Scope V2 - Hackathon Submission

## Built - One Complete Workflow
Priority 1: Upload synthetic hearing, validate, call real Muse Voice Transcribe API, show transcript with speaker labels and timestamps. Mock fallback only if API unavailable, clearly labelled. (`tests/test_ingestion_v2.py`, `tests/test_transcription_v2.py`, `tests/test_voice_diarization.py`)
Priority 2: Intelligent Review Desk. Muse Spark flags possible errors; reviewer jumps to audio passage, edits draft, records decision. (`tests/test_spark_review.py`, `tests/test_human_review.py`)
Priority 3: Traceable Corrections. Original kept, each correction with who, when, before, after, reason, linked flag; unresolved issues stay visible. (`tests/test_human_review.py`)
Priority 4: Draft Export and Evaluation. Watermarked DOCX draft. Measured comparison original AI vs human-reviewed: WER, CER, % segments changed, flags resolved. (`tests/test_draft_export.py`)
Plus: live microphone capture (`tests/test_live_transcribe.py`), measured Kenyan-language evaluation (`tests/test_language_evaluation.py`), privacy deletion and API evidence (`tests/test_submission_readiness.py`).

Single role: Reviewer (name required). Responsive UI: stepper Upload -> Transcribe -> Review -> Export, segment cards, flag panel, jump-to-audio, diff view, About page, live tab.

## Deliberately Deferred - Do NOT Build For This Submission
- Public access to actual court records
- Real-case uploads and Judiciary system integrations
- Automated certification and digital court signatures
- Automated legal advice or appeal eligibility decisions
- Complex multi-role administrative portal (Clerk/Magistrate split is parked)
- Deadline prediction, sentencing analysis, judicial decision support
- Offline open-weight model (Muse Glimmer / Spark Open) unless core workflow is already reliable
- Muse Image timeline, SAM 3.1 charge-sheet redaction, Muse Wonder public explainer - parked to extras/

## Synthetic Data Only
Case CR 123/2026, R v SYNTHETIC John Doe. No real litigants, no real audio, no real ID numbers.

## Acceptance Criteria For Demo
A judge can, in 5 minutes (see `docs/JUDGE-DEMO.md`): load the demo recording, see the transcript, run AI review, click a flag and hear that passage, edit and save a decision, see correction history, export the watermarked DOCX, and see evaluation numbers.
