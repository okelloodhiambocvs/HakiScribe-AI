# HakiScribe ASR evaluation (measured)

> Every number below comes from `evaluation/results/latest.json`.
> Nothing here is estimated.

No evaluation run yet.

## Per-category results

Mean of per-clip rates; lower is better, a perfect transcript scores zero.

| Category | Clips | Mean WER | Mean CER | Reference words |
| --- | --- | --- | --- | --- |
| English | 0 | Not yet measured | Not yet measured | 0 |
| Kiswahili | 0 | Not yet measured | Not yet measured | 0 |
| Code-switched English-Kiswahili | 0 | Not yet measured | Not yet measured | 0 |

## Per-clip results

| Clip | Category | WER | CER | Reference words |
| --- | --- | --- | --- | --- |
| _none_ | — | Not yet measured | Not yet measured | 0 |

## Method

- Each clip runs through the real batch endpoint: the same code path as the app, DIARIZATION mode with the configured keywords and language bias.
- WER and CER use `evaluation_service` normalisation: Unicode NFC, lower-case, punctuation stripped, whitespace collapsed, diacritics preserved, no translation.
- Category means are arithmetic means of the per-clip rates.
- Regenerate with `python scripts/evaluate_asr.py` then `python scripts/render_evaluation_doc.py`.
