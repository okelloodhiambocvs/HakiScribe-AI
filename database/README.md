# V2 Database — SQLite Layer

- SQLite database file (future): `data/hakiscribe.db` (gitignored).
- Tables: recordings, segments, flags, corrections, exports
  (see docs/architecture/ARCHITECTURE-V2.md for the full schema).
- `segments.text_original` is IMMUTABLE — the AI draft is never overwritten.
- Corrections are separate rows carrying reviewer, timestamp, before and after.
- Only `backend/repositories/` may read/write this database.
