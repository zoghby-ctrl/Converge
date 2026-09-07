# Phase 2B image validation lock

Locked before the first validation inference on 7 September 2026.

- Manifest: `fixtures/images/manifest.json`
- Manifest SHA-256 (UTF-8 content): `49e48d7e58d3c88c6b19891436f71edb71e687bd18bdcdaf7a7bb93ec78b647f`
- Task: `image-perception-1`
- Prompt: `image-1.2`
- Schema: `image-1.0`
- Normalization: `image-normalization-1`
- Requested model: `gpt-5.6-luna`; selective fallback: `gpt-5.6-terra`
- Reasoning effort: `none`

Locked validation IDs:

`water-04`, `water-05`, `water-06`, `damage-04`, `benign-06`,
`ambiguous-04`, `ambiguous-05`, `ambiguous-06`, `damage-05`, `damage-06`.

These ten records are distinct source photographs with no shared source group or
content hash across the development split. Reference labels were recorded before
runtime image-model output. They are agent visual labels, not independent human
ground truth. No prompt, reference label, split, or validation membership may be
changed after the first validation run and still be described as locked. A future
human review must be reported separately rather than retroactively replacing this
release measurement.
