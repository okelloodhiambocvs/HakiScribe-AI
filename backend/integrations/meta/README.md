# V2 Meta Integrations — Only Place for Meta Model API Calls

All V2 Meta Model API calls live in this package and nowhere else.

CORE ACTIVE (judge workflow):
- Muse Voice Transcribe — transcription with timestamps and confidence.
- Muse Spark or Muse Wonder — intelligent flagging of errors and inconsistencies.

PARKED (do not build for submission; see extras/):
- Muse Image, SAM 3.1, Muse Glimmer and Muse Spark Open offline.

Rules for future code:
- Do NOT invent Meta endpoint URLs. Check the dev.meta.ai docs for exact paths and payloads.
- Reuse the existing `src/` clients as reference (transcription, spark, wonder clients).
