# V2 Backend — Workflow Rules, No UI

- `services/` contains the workflow rules for ingestion, transcription, review, corrections, export and evaluation.
- `repositories/` is the only backend code allowed to read/write the database.
- `integrations/meta/` is the only place for Meta Model API calls.
- Backend never renders Streamlit UI — it serves the frontend package.
