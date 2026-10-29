# HakiScribe-AI Architecture V2 - One Judge-Usable Workflow

Rule: AI proposes. HUMAN REVIEWS. Nothing is official.
Export is a watermarked DOCX DRAFT - NOT an official court record.

## 1. Workflow (six capabilities)
1. Recording Ingestion: Upload synthetic audio (.mp3/.wav/.m4a/.aac/.adts/.ogg/.opus/.webm) -> validate type, size, hash, attestation -> store file + DB row
2. Transcription: Muse Voice Transcribe via Meta Model API in DIARIZATION mode -> turns with start/end, Speaker A/B labels, verbatim text, confidence NULL (the API gives none)
3. Live microphone: realtime websocket capture with approximate timestamps -> optional batch finalise pass through the guarded replace path
4. Intelligent Review Desk: Muse Spark via Meta Model API flags suggestions -> reviewer jumps to audio, edits, records ACCEPT_SUGGESTION / EDIT_TEXT / DISMISS_FLAG / RETAIN_UNCERTAIN / ASSIGN_SPEAKER_ROLE
5. Traceable Corrections: Original text never overwritten. Every correction stored with who, when, before, after, reason, linked flag. Unresolved flags stay listed.
6. Draft Export + Evaluation: Watermarked DOCX draft + measured WER/CER (AI vs reviewed, AI vs reference), speaker attribution, traceability, review time
7. Privacy: typed-DELETE removal of rows, audio, and exports with a content-free deletion log; retention is local-only

## 2. Layers - Frontend / Backend / Database
frontend/   Streamlit UI only (app entry, views, components). No Meta calls. No DB calls. Calls backend.services only.
backend/
  integrations/      audio_capture.py (mic/file sources); meta/voice_transcribe.py, meta/realtime_transcribe.py, meta/spark_client.py, meta/audio_prep.py - ONLY place Meta is called
  services/          workflow_service (UI facade), ingestion_service, transcription_service, review_service (+review_prompt), evaluation_service, export_service, live_session_service, health_service - business rules
  repositories/      recordings, segments, flags, corrections, exports, api_calls, ai_runs, speaker_roles, review_events, deletion_log - ONLY code that reads/writes the database
database/   SQLite schema (user_version 8) and connection. File: data/hakiscribe.db (gitignored)
storage/    uploads/ and exports/ for synthetic files only (gitignored)
evaluation/ consented Kenyan-language set + results (see evaluation/README.md)
scripts/    probes, evaluate_asr, render_evaluation_doc, generate_api_evidence, check_setup, fresh_clone_check
tests/      offline suite incl. test_architecture_rules.py, which parses every file and enforces the layer rules

Frontend never calls Meta directly. Backend never renders UI. Only repositories touch DB.

## 3. Database Tables (schema user_version 8)
recordings: id, filename, stored_path, sha256, size_bytes, duration_sec, uploaded_by, synthetic_attestation, transcription_source real/mock (immutable once set), transcription_model, transcription_raw_json, transcribed_at, capture_source upload/live, created_at
segments: id, recording_id, idx, start_sec, end_sec, speaker, speaker_label, confidence (NULL for real calls), language, text_original (immutable trigger), text_current, is_approximate, created_at, updated_at
flags: id, segment_id, flag_type, severity, message, evidence, status OPEN/RESOLVED/DISMISSED/RETAINED, created_by_model, suggestion, related_segment_id, prompt_version, evidence_verified, created_at, resolved_at, resolved_by, resolution_note
corrections: id, segment_id, flag_id, field text/speaker_role, before_text, after_text, reviewer_name, decision, reason, created_at (append-only trigger)
exports: id, recording_id, docx_filename, wer, cer, segments_changed_pct, flags_total, flags_resolved, ref_wer, ref_cer, speaker_attribution_pct, boundary_error_ms, traceability_pct, review_seconds, generated_by, created_at
api_calls: id, provider, model, endpoint_path, mode, recording_id (SET NULL), http_status, ok, latency_ms, audio_bytes, audio_ms, request_id, error_code, created_at (outcomes only, never keys or bodies)
ai_runs: id, recording_id, model, prompt_version, mode real/mock, status, flags_created, flags_dropped, raw_json, created_at
speaker_roles: recording_id, speaker_label, role, assigned_by, assigned_at (UNIQUE recording_id + label)
review_events: id, recording_id, reviewer, event, at
deletion_log: id, recording_id (deleted id, no FK), reviewer, deleted_at (content-free)
Migrations are PRAGMA user_version-guarded ALTER TABLEs; fresh and old databases converge.

## 4. Error contract
backend/core/errors.py: HakiScribeError carries code + user_message (plain English, no traces, no secrets). Subclasses: UploadValidationError, TranscriptionError, AudioPrepError, AlreadyTranscribedError, TranscriptionLockedError, TranscriptionInProgressError, EditConflictError, AudioCaptureError, RealtimeError, SparkError. Frontend renders them via frontend/components/errors.py show_error().

## 5. Kenyan Language Handling
Kenya uses English, Kiswahili, and normal code-switching in one conversation.
- Preserve original mix in text_original. Do NOT auto-translate.
- languageBias and court keywords are configurable; review prompt forbids translation and protects code-switching.
- Measured accuracy lives in evaluation/results/latest.json; unmeasured categories say so (docs/EVALUATION.md, docs/LANGUAGE-LIMITATIONS.md).
- WER/CER normalisation (backend/services/evaluation_service.py): Unicode NFC, lower-case, strip punctuation/symbols, collapse whitespace, keep diacritics, never translate or spell-correct.

Synthetic example:
MAGISTRATE: Case CR 123 of 2026, proceed.
PROSECUTOR: Mheshimiwa, mlalamikaji yupo kotini leo.
COMPLAINANT: Nilikuwa nyumbani saa mbili usiku.
ACCUSED: Si kweli, sikuwa hapo.

## 6. Kenyan Speaker Taxonomy
MAGISTRATE, PROSECUTOR, ADVOCATE, ACCUSED, COMPLAINANT, WITNESS_PW1, WITNESS_PW2, COURT_ASSISTANT, INVESTIGATING_OFFICER, INTERPRETER, UNKNOWN
UNKNOWN must be flagged for human, never guessed silently.

## 7. Meta Model Usage - Core Only For Submission
- Muse Voice Transcribe (Meta Model API): backend/integrations/meta/voice_transcribe.py (batch) + realtime_transcribe.py (live) - turns with timestamps, no confidence from API
- Muse Spark (Meta Model API): backend/integrations/meta/spark_client.py + review_prompt.py - flag suggestions with quoted evidence. Suggest only, never modifies.
- Muse Code in VS Code: coding agent, logged in MUSE-CODE-LOG.md
Parked to extras, NOT in core workflow: Muse Image, SAM 3.1, Muse Glimmer offline, Muse Wonder explainer. Using 2 models deeply beats using 6 models shallowly.

## 8. Human-in-the-Loop Enforcement
- No segment is reviewed until a named Reviewer records a decision.
- Flags stay OPEN until human resolves, dismisses, or retains with a reason.
- DOCX export shows unresolved flags count and watermark on every page: DRAFT - NOT CERTIFIED.
- No certification, no digital signature, no legal advice, no deadline prediction, no appeal decisions.
