# Optional Gemini perception

## Files changed

| File | Change |
| --- | --- |
| `.env.example` | Optional provider selector and blank Gemini credential placeholder |
| `backend/app/gemini_provider.py` | New bounded Gemini HTTP transport and wire-schema projection |
| `backend/app/perception.py` | Provider selection, dispatch, accounting, metadata and cache namespace |
| `backend/app/image_perception.py` | Provider-aware metadata and cache namespace |
| `tests/test_gemini_provider.py` | 24 focused offline checks |
| `tests/test_phase5_blocker_fixes.py` | Inject fake provider into two existing tests |
| `docs/GEMINI_PERCEPTION.md` | Configuration, verification and limitations report |
| `docs/gemini-live-validation.json` | Successful live outputs and request accounting |

Ignored `.runtime` smoke scripts/results and `.firecrawl` documentation downloads
were also created locally. Existing unrelated untracked files were left untouched.

## Configuration

Set these in the server environment or ignored root `.env`, then restart the backend:

```dotenv
CONVERGE_PERCEPTION_PROVIDER=gemini
GEMINI_API_KEY=your-local-key
```

Omit the selector, or set it to `openai`, to use the existing provider. No credentials
belong in frontend configuration or source control. `.env.example` contains blank
credential placeholders only. This integration does not change the local `.env`.

## Scope

Google Gemini extracts bounded report claims and visible image observations into
Converge's existing `TextExtraction` and `ImageExtraction` contracts. Existing
source-span validation, uncertainty accounting, evidence mapping and deterministic
engine logic run afterward. Gemini never calculates Risk Index, Evidence Strength,
incident membership, duplicate independence, hypotheses or final inspection action.
Neither tools nor grounding are enabled. Images use the existing normalized bytes;
capture identity, operator location/time and provenance remain outside the model.

The only production integration points are `perception.py`, `image_perception.py`
and the small HTTP transport in `gemini_provider.py`. No engine, scoring, weight,
incident, hypothesis, fixture, database schema or history logic changed.

## Model and verified API

Verified September 9, 2026:

- Stable `gemini-3.8-flash`, supporting text/image input and structured text output:
  [official model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash).
- REST `POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent`:
  [structured output guide](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).
- The live model metadata endpoint confirmed `generateContent` support.
- REST `responseFormat.text.mimeType` is `APPLICATION_JSON`, and thinking level is
  `LOW`, per the [official discovery schema](https://generativelanguage.googleapis.com/$discovery/rest?version=v1beta).
  The guide's `application/json` value for the new enum field was rejected live.

Gemini rejected the complete text schema with HTTP 400. The transport therefore
omits numeric, string-length and array-length bounds and schema titles from its
wire projection. Field names, types, enums, required fields, nullability and
`additionalProperties: false` remain. **Every original bound and semantic validator
still runs locally before acceptance.** No output repair supplies missing values.
Google documents schema complexity limits and recommends reducing constraints.

## Failure, metadata and budgets

The existing retry boundary remains: one primary call, at most one schema repair,
then at most one fallback. For Gemini, fallback/deeper review rechecks the same
pinned model; it is not a stronger model or a switch to OpenAI. The existing
`OPENAI_FALLBACK_ENABLED` flag controls this policy for either provider. Material
text uncertainty retains the primary extraction and follows the existing review
policy. Image uncertainty follows the existing image review policy.

HTTP errors, blocked output, malformed envelopes, missing credentials and unknown
providers fail with fixed error codes. Network errors are not automatically retried.
Incomplete outputs cannot be accepted. No HTTP error body is returned to callers.
The key is sent only in the authentication header. Both provider keys are excluded
from settings representations and redacted from stored raw output; credential-bearing
output is rejected before caching or acceptance.

Results retain provider, requested model, actual model version, actual response ID,
prompt/schema/task versions, timestamps, source hashes and usage. Thought tokens
are accounted as output usage but thought content is not extracted. Provider cache
namespaces are separate, while existing OpenAI cache keys remain unchanged. There
are no SQLite migrations or changes to observation history semantics.

Existing `OPENAI_MAX_REQUESTS` and `OPENAI_MAX_SPEND_USD` caps apply across both
providers in the same usage ledger. Gemini uses a conservative rate ceiling of
$1.50/M input and $7.50/M output tokens, above the current promotional rates, plus
the existing input margin. See [official pricing](https://ai.google.dev/gemini-api/docs/pricing).
Image reservations conservatively use encoded byte size, so large images may hit
the development budget early. Missing usage leaves the reservation accounted.
Costs remain estimates, not Google billing. Gemini retention follows Google's API
terms; the metadata does not claim OpenAI's `store=false` behavior for Google.

## Validation results

`python -m pytest -q`: **153 passed**, one existing Starlette/AnyIO deprecation warning.
This includes 24 focused Gemini/configuration/contract/pipeline/replay test cases.
The initial existing-suite run had 128 passes and one failure in a revision-history
test that depended on a live provider. The two phase-5 tests that submitted live
reports now inject the existing fake provider; their business assertions remain.

Exactly one successful live text extraction and one successful live image extraction
were obtained using isolated temporary databases. There were **nine generation HTTP
attempts total: two successes and seven failures** while resolving API/schema
compatibility (six configuration rejections and one provider API error). No automatic
retry loop or extra successful image run was used. Metadata/count-token diagnostics
did not generate observations.

- Text: “There is standing water on the road. The road surface is damaged.” Both
  conditions were `present` with exact source spans; obstruction and recurrence
  stayed `not_mentioned`; duration and explanation stayed null. Accepted by the
  original text contract and mapped to two existing evidence objects.
- Image: existing `fixtures/images/water-01.jpg`, normalized through the unchanged
  ingestion path. Gemini returned water `present`, visible surface damage `absent`,
  obstruction `absent`, usable quality and three support descriptions. Accepted by
  the original image contract and mapped to three evidence objects. These remain
  model observations, not field verification.

Full successful outputs, hashes, response references and usage are in
[`gemini-live-validation.json`](gemini-live-validation.json). The image success used
the complete wire schema before the later generic projection was introduced; the
final projection is covered offline for both modalities. The successful image was
not sent again. Temporary smoke databases were discarded, leaving application
history untouched.

Both `signature` and `signature_image` replay fixtures pass under both provider
settings, with **zero provider calls** and persistent replay state unchanged:

| State | Risk Index | Evidence Strength | Independent captures |
| --- | --- | --- | --- |
| Baseline | 68 | Moderate | 3 |
| Image removed | 52–83 | Limited | 2 |
| Restored | 68 | Moderate | 3 |
| Ten duplicate copies | 68 | Moderate | 3 |

## Remaining limitations

Two successful examples establish connectivity and contract acceptance, not model
accuracy across Arabic, ambiguous scenes or adversarial inputs. Those need a later
evaluation. Gemini can produce schema-valid but incorrect observations; existing
review/admission gates remain necessary. Same-model rechecking does not establish
independent evidence. Google availability, pricing and data terms can change. The
documented generateContent API is labeled legacy; a future migration should remain
inside the transport. No commit, staging operation or git-history change was made.
