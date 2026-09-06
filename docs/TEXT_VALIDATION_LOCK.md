# Phase 2A validation lock

The 18 reports in `fixtures/text_validation_locked.json` were authored separately
from the 18 development reports before any validation API call. Prompt text-1.1
was frozen after evaluating development, before opening validation results.
Validation labels, prompt and thresholds must not be tuned using this run. A
future iteration requires a new held-out set. The evaluation report records the
corpus SHA-256, prompt/schema versions, outputs, abstentions and actual usage.

Locked corpus SHA-256:
`c719a9b99f08bf9b7c252d0b61a4a721b3b0f4e4c256db371d3e3b2e34e4e448`.

Precision/recall use current positives. Explicit historical positives remain
historical claims and are negative examples for current evidence admission.
"Not seeing" damage is conservatively annotated uncertain, rather than proof of
absence. Speculation about cause is not a condition observation. The authored
labels have not been independently reviewed by municipal engineers.
