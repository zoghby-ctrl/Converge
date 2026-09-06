# Structured demo fixtures

All observations, image-family annotations, rain, placement, timing and road-context
classes in this phase are hand-authored synthetic examples. There are no real
municipal complaints, source photographs, or cached AI outputs. Reviewer labels
describe fixture review, not field verification.

The local map is a schematic within the proposed Nasr City extent; its lines are
simulated study segments, not downloaded or surveyed roads. It is deliberately
labeled as such. Real sourced road vectors and licensed photographs are next-phase
inputs. No external map, weather or extraction calls occur at runtime.

`python -m fixtures.generate` regenerates the versioned JSON fixtures. Hidden
expected outcomes live in tests, never in engine input. These are development
guard cases, not a held-out evaluation or accuracy benchmark.
# Phase 2A text corpus

`text_development.json` and `text_validation_locked.json` contain 18 reports each.
They are authored evaluation cases, not field reports or structured replay datasets.
The development prompt may be tuned on development; validation was locked before
its first model call. See `docs/TEXT_VALIDATION_LOCK.md`. Run evaluation via
`python -m backend.evaluate_text`; only `--live` permits API calls on cache misses.
Outputs and exact measured counts are in `docs/text-evaluation-*.json`.
