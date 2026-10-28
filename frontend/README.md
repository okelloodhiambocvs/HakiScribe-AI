# V2 Frontend — Streamlit UI Only

- Streamlit UI only. No business logic here.
- No direct Meta Model API calls — the frontend calls backend services, which own all Meta calls.
- No direct database access — all reads and writes go through the backend.
- Calls backend services for every action (upload and transcribe are live; flag, decide, export and evaluate connect in later steps).
- Responsible for the attractive, responsive reviewer workflow: Upload -> Transcribe -> Review -> Export
  (stepper, segment cards, flag preview; full flag panel, sticky audio and diff view are planned).
