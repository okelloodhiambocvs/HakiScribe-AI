# HakiScribe-AI Architecture - Human-in-the-Loop

Rule: AI proposes. HUMAN disposes.

[Synthetic Noisy Court Audio]
  |
  v
1. Muse Voice Transcribe (Meta Model API) `src/transcription/client.py`
   -> segments + timestamps + confidence + EN-KE/SW-KE
  |
  v
2. Muse Spark Agents (Meta Model API) `src/agents/`
   Structurer: speakers + Case No
   Guardian: flags confidence < 0.75 for HUMAN replay
   Deadline: suggests 14-day / 60-day appeal dates, human must confirm law
  |
  v
3. HUMAN VERIFICATION `src/verification/service.py` + `app.py`
   Clerk (Human 1) MUST review each flagged segment individually
   Magistrate (Human 2, different person) MUST click CERTIFY
   -> SHA256 hash + audit log: AI_DRAFT -> CLERK_REVIEWED -> CERTIFIED
  |
  +--> Certified PDF `src/export/pdf_service.py` (human export only)
  +--> Muse Wonder Explainer EN/SW `src/explainer/` (human approve)
  +--> Muse Image Timeline `src/timeline/` (human approve)
  +--> SAM 3.1 Redaction `src/vision/` (human approve masks)
  +--> Muse Glimmer Offline Redaction `src/offline/` (local, human approve)

No certified record = no public output. No named human = no export/share.