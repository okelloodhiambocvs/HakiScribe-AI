# HakiScribe-AI 2.0 Architecture - Human-in-the-Loop

**Rule: AI proposes. HUMAN disposes.**

[Noisy Court Audio .mp3 - SYNTHETIC ONLY]
  |
  v
1. Muse Voice Transcribe (Meta Model API) -> raw text + timestamps + confidence
  |
  v
2. Muse Spark (Meta Model API) Agents:
   - Structurer: MAGISTRATE / PROSECUTION / WITNESS + Case No, Plea
   - Guardian: flags [VERIFY] if confidence < 0.75 or conflict
   - Deadline: calculates 14-day appeal window
  |
  v
3. HUMAN-IN-THE-LOOP UI:
   Clerk MUST replay + Edit/Accept each flag -> Magistrate MUST click CERTIFY
   No auto-certify. Audit log: AI v1 -> Clerk edits -> Magistrate certified + hash
  |
  +--> Muse Wonder -> Kiswahili Mwananchi explainer
  +--> SAM 3.1 -> segments charge sheet photo, masks signature
  +--> Muse Image -> visual case timeline
  +--> Muse Glimmer Open Weights (LOCAL OFFLINE) -> PII redaction, no internet