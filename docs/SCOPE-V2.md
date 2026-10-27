# HakiScribe-AI Scope V2 - Hackathon Submission

## Must Have - One Complete Workflow
Priority 1: Upload synthetic hearing, validate, call real Muse Voice Transcribe API, show transcript with speaker labels and timestamps. Mock fallback only if API unavailable, and mock must be clearly labelled.
Priority 2: Intelligent Review Desk. Muse Spark/Wonder flags possible errors and inconsistencies. Reviewer can jump to audio passage, edit draft, record decision.
Priority 3: Traceable Corrections. Keep original, each accepted correction, who, when, linked flag, unresolved issues remain visible.
Priority 4: Draft Export and Evaluation. Watermarked DOCX draft. Measured comparison original AI vs human-reviewed: WER, CER, % segments changed, flags resolved.

Single role: Reviewer (name required). Responsive attractive UI: stepper Upload -> Transcribe -> Review -> Export, segment cards, flag panel, sticky audio player, diff view.

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
A judge can, in under 3 minutes: upload synthetic audio, see transcript, click a flag and hear that passage, edit and save a decision, see correction history, export watermarked DOCX, and see evaluation numbers.