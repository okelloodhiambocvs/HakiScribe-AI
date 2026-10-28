# V2 Extras — Parked, Not In Core Judge Workflow

Deliberately deferred; do not build for this submission:
- Certification (multi-role approval, signatures)
- Deadline prediction
- Public explainer
- Muse Image timeline
- SAM 3.1 redaction
- Offline Glimmer

See docs/SCOPE-V2.md for the deferred list.

## Parked V1 client modules (reference only, never imported)

Moved here untouched from `src/` during the V2 layering. They still reference
the deleted `src.*` package paths and are kept for reference only:
- `explainer/` — Muse Wonder client + service (V1 citizen explainer)
- `timeline/` — Muse Image client + service (V1 visual timeline)
- `vision/` — SAM 3.1 client + service (V1 charge-sheet redaction)
- `offline/` — Muse Glimmer client + service (V1 offline redaction)
