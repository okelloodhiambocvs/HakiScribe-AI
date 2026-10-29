# V2 Meta Integrations — Only Place for Meta Model API Calls

All V2 Meta Model API calls live in this package and nowhere else.

LIVE (judge workflow):
- Muse Voice Transcribe (batch) — `voice_transcribe.py`: DIARIZATION turns with timestamps; the API returns no confidence scores (NULL). Responses are validated before an attempt is marked usable.
- Muse Voice Transcribe (realtime) — `realtime_transcribe.py`: WebSocket sessions; audio frames are sent followed by `{"type":"endStream"}`, then the client waits for the server's normal close (code 1000). Only a normally closed session counts as completed.
- Muse Spark review — `spark_client.py` plus `backend/services/review_prompt.py`: flags with quoted evidence; replies are validated as review JSON before use. The model never modifies the transcript.
- Audio helpers — `audio_prep.py` (16 kHz WAV prep) and `audio_capture.py` (microphone/file sources). No Meta calls here.

PARKED (do not build for submission; see extras/):
- Muse Wonder, Muse Image, SAM 3.1, Muse Glimmer and Muse Spark Open offline.

Attempt-outcome rules:
- Every HTTP attempt (success, retry, 4xx/5xx, timeout) is reported via on_attempt; services persist it to api_calls.
- ok=1 means a validated, usable result — never bare HTTP success. Unparseable or misshapen responses are recorded as PARSE_ERROR / INVALID_RESPONSE failures.
- Realtime rows record the handshake (HTTP 101) separately from completion: ok=1 only for normally completed sessions.
- Rows never store keys, audio, or response bodies. Evidence: `scripts/generate_api_evidence.py` → `docs/API-EVIDENCE.md`.

Rules for future code:
- Do NOT invent Meta endpoint URLs. Check the dev.meta.ai docs for exact paths and payloads.
- Reuse the parked `extras/` clients as reference (wonder, image, sam, glimmer clients).
