# Meta API evidence (from the local database)

Generated 2026-10-29T21:30:13+00:00 from this machine's local `api_calls`, `ai_runs`, and `recordings` tables. Rows record attempts made by this app — they are not independent verification of the Meta service. Metadata only: no transcript text, response bodies, API keys, or session identifiers.

## Voice batch (`/asr/transcribe`)

No calls recorded yet — no provider evidence.

## Voice realtime (`/asr/realtime`)

No calls recorded yet — no provider evidence.

## Spark (chat / messages / responses style endpoint)

No calls recorded yet — no provider evidence.

## Mock executions (not provider evidence)

- Mock-mode transcripts persisted: 1
- Mock review runs ledgered: 0 (real runs: 0)
- Mock mode makes no provider calls and proves nothing about the Meta service.

## What this report does not prove

- A configured API key alone proves nothing; only recorded attempts with usable results count.
- A handshake (HTTP 101), an empty ledger, or a stopped session is not a successful integration.
- Response content is deliberately omitted: transcript text, response bodies, API keys, and session identifiers never appear in this report.
- The repository's tests use isolated databases and fake servers; their rows never appear in this ledger.
