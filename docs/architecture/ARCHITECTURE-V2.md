# HakiScribe-AI Architecture V2 - One Judge-Usable Workflow

Rule: AI proposes. HUMAN REVIEWS. Nothing is official.
Export is a watermarked DOCX DRAFT - NOT an official court record.

## 1. Workflow (Priority 1 to 4)
1. Recording Ingestion: Upload synthetic .mp3/.wav -> validate type, size, hash, duration -> store file + DB row
2. Transcription: Muse Voice Transcribe via Meta Model API -> segments with start/end, speaker, confidence, original text preserved
3. Intelligent Review Desk: Muse Spark via Meta Model API flags errors/inconsistencies -> reviewer jumps to audio, edits, records ACCEPT / EDIT / DISMISS decision
4. Traceable Corrections: Original text never overwritten. Every correction stored with who, when, before, after, reason, linked flag. Unresolved flags are listed.
5. Draft Export + Evaluation: Watermarked DOCX draft + comparison original vs reviewed: segments changed %, words changed, WER, CER, flags resolved %

## 2. Layers - Frontend / Backend / Database
frontend/   Streamlit UI only. No Meta calls. No DB calls. Calls backend services.
backend/
  integrations/meta/   voice_transcribe.py, spark_review.py - ONLY place Meta Model API keys are used
  services/            ingestion, transcription, review, corrections, export_eval - business rules
  repositories/        ONLY code that reads/writes the database
database/   SQLite schema and connection. File: data/hakiscribe.db (gitignored)
storage/    uploads/ and exports/ for synthetic files only (gitignored)
tests/      Service tests + one end-to-end workflow test

Frontend never calls Meta directly. Backend never renders UI. Only repositories touch DB.

## 3. Database Tables
recordings: id, filename, sha256, size_bytes, duration_sec, uploaded_by, synthetic_attestation, created_at
segments: id, recording_id, idx, start_sec, end_sec, speaker, confidence, text_original (immutable), text_current
flags: id, segment_id, type, severity, message, evidence, status OPEN/RESOLVED/DISMISSED, created_by_model, created_at
corrections: id, segment_id, flag_id, before_text, after_text, reviewer_name, decision, reason, created_at
exports: id, recording_id, docx_filename, wer, cer, segments_changed_pct, flags_total, flags_resolved, generated_by, created_at

## 4. Kenyan Language Handling
Kenya uses English, Kiswahili, and normal code-switching in one conversation.
- Preserve original mix in text_original. Do NOT auto-translate.
- language_hints: en-KE, sw-KE
- Spark may flag [VERIFY - unclear code-switch] but human decides meaning.
- Evaluation compares original vs reviewed without punishing language mix.

Synthetic example:
MAGISTRATE: Case CR 123 of 2026, proceed.
PROSECUTOR: Mheshimiwa, mlalamikaji yupo kotini leo.
COMPLAINANT: Nilikuwa nyumbani saa mbili usiku.
ACCUSED: Si kweli, sikuwa hapo.

## 5. Kenyan Speaker Taxonomy
MAGISTRATE, PROSECUTOR, ADVOCATE, ACCUSED, COMPLAINANT, WITNESS_PW1, WITNESS_PW2, COURT_ASSISTANT, INVESTIGATING_OFFICER, INTERPRETER, UNKNOWN
UNKNOWN must be flagged for human, never guessed silently.

## 6. Meta Model Usage - Core Only For Submission
- Muse Voice Transcribe (Meta Model API): backend/integrations/meta/voice_transcribe.py - transcription with timestamps and confidence
- Muse Spark or Muse Wonder (Meta Model API): backend/integrations/meta/spark_review.py - flag errors/inconsistencies, explain why flagged, suggest correction. Suggest only.
- Muse Code in VS Code: coding agent, logged in MUSE-CODE-LOG.md
Parked to extras, NOT in core workflow: Muse Image, SAM 3.1, Muse Glimmer offline. Using 2 models deeply beats using 6 models shallowly.

## 7. Human-in-the-Loop Enforcement
- No segment is reviewed until a named Reviewer records a decision.
- Flags stay OPEN until human resolves or dismisses with a reason.
- DOCX export shows unresolved flags count and watermark on every page: DRAFT - NOT AN OFFICIAL COURT RECORD - HUMAN REVIEWED
- No automated certification, no digital signature, no legal advice, no deadline prediction.