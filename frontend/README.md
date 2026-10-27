# V2 Frontend — Streamlit UI Only

- Streamlit UI only. No business logic here.
- No direct Meta Model API calls — the frontend calls backend services, which own all Meta calls.
- No direct database access — all reads and writes go through the backend.
- Calls backend services for every action (upload, transcribe, flag, decide, export, evaluate).
- Responsible for the attractive, responsive reviewer workflow: Upload -> Transcribe -> Review -> Export
  (stepper, segment cards, flag panel, sticky audio player, diff view).
