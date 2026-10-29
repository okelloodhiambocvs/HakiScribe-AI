# Kenyan-language ASR evaluation set

This folder holds a small, consented speech set for measuring HakiScribe's
batch transcription accuracy on Kenyan English, Kiswahili, and code-switched
speech. Every accuracy number in the app and docs must come from a run over
this set — nothing is estimated.

## Layout

- `manifest.json` — the clip list (`{"clips": [...]}`). Paths are relative
  to this folder.
- `audio/` — clip WAV files (committed only if synthetic or consented).
- `reference/` — one plain-text transcript per clip (see `TEMPLATE.txt`).
- `results/latest.json` — output of `scripts/evaluate_asr.py` (committed,
  so every claim stays backed by a results file).

## How to record a clip

1. Use consenting speakers only (colleagues role-playing, or synthesized
   voices). Never use real hearings, real litigants, or real case facts.
2. Record 16 kHz mono WAV, 20–60 seconds per clip, quiet room.
3. Speak naturally: full English sentences, full Kiswahili sentences, or
   natural code-switching — one category per clip.
4. Write the reference transcript: the exact words spoken, in order,
   including names, numbers, and language mixing. Do not translate,
   paraphrase, or tidy up disfluencies. Save as `reference/<id>.txt`.
5. Add a manifest entry:

```json
{
  "id": "sw-001",
  "category": "kiswahili",
  "audio": "audio/sw-001.wav",
  "reference": "reference/sw-001.txt",
  "speakers": ["SPEAKER_1"],
  "consent_note": "Synthetic voice; no real persons.",
  "duration_sec": 32.5
}
```

`category` is one of `english`, `kiswahili`, `code_switched`.
`consent_note` must state the clip is synthetic or name the consenting
arrangement. `duration_sec` is advisory; scoring uses the transcript.

## How to run

```bash
python scripts/evaluate_asr.py
python scripts/evaluate_asr.py --language-bias English,Kiswahili
python scripts/render_evaluation_doc.py
```

The evaluator needs `META_API_KEY` (real endpoint only — mock results
would be fake measurements), exits non-zero if any clip file is missing,
and writes `results/latest.json` only on a fully successful run. The
renderer turns that file into `docs/EVALUATION.md` and
`docs/LANGUAGE-LIMITATIONS.md`; categories with no runs say
"Not yet measured".
