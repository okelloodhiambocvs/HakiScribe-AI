# HakiScribe ASR evaluation (measured)

> Every number below comes from `evaluation/results/latest.json`.
> Nothing here is estimated.

No evaluation run yet.

## Per-category results

Mean of per-clip rates, and pooled rates over all reference words or characters; lower is better, a perfect transcript scores zero.

| Category | Clips | Mean WER | Mean CER | Pooled WER | Pooled CER | Reference words |
| --- | --- | --- | --- | --- | --- | --- |
| English | 0 | Not yet measured | Not yet measured | Not yet measured | Not yet measured | 0 |
| Kiswahili | 0 | Not yet measured | Not yet measured | Not yet measured | Not yet measured | 0 |
| Code-switched English-Kiswahili | 0 | Not yet measured | Not yet measured | Not yet measured | Not yet measured | 0 |

## Per-clip results

| Clip | Category | WER | CER | Reference words | Word edits | Character edits | Reference characters |
| --- | --- | --- | --- | --- | --- | --- | --- |
| _none_ | — | Not yet measured | Not yet measured | 0 | Not yet measured | Not yet measured | Not yet measured |

## Method

- Each clip runs through the real batch endpoint: the same code path as the app, DIARIZATION mode with the configured keywords and language bias.
- WER and CER use `evaluation_service` normalisation: Unicode NFC, lower-case, punctuation stripped, whitespace collapsed, diacritics preserved, no translation.
- Category means are arithmetic means of the per-clip rates: every clip carries equal weight.
- Pooled WER is total word edits divided by total reference words; pooled CER is total character edits divided by total reference characters, including spaces. Mean metrics give every clip equal weight, while pooled metrics weight clips according to their reference length, so the two can differ when clip lengths vary. Neither method is universally better; they answer different evaluation questions.
- The transcription source names the selected code path (`provider_integration` or `injected`); it is not proof that an external provider request succeeded.
- Regenerate with `python scripts/evaluate_asr.py` then `python scripts/render_evaluation_doc.py`.
