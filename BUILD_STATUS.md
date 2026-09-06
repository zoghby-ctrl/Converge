# Converge — Phase 2A build status

**Completed: Implementation Phase 2A — OpenAI text perception, 6 September 2026.**
Phase 1 was approved and its engine is preserved. Phase 2B has not started.
No image inference, dashboard redesign, deployment, model training, chatbot or
geospatial expansion was implemented. The historical Phase 1 record is preserved
in [PHASE1_BUILD_STATUS.md](docs/PHASE1_BUILD_STATUS.md).

## Implemented integration

Official references consulted: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Luna model/configuration and text rates](https://developers.openai.com/api/docs/models/gpt-5.6-luna),
[Terra model/configuration and text rates](https://developers.openai.com/api/docs/models/gpt-5.6-terra).

- Official Python OpenAI SDK **3.8.0**, Responses API, strict JSON Schema generated
  from Pydantic, followed by server-side Pydantic and exact-source-span validation.
- Primary **gpt-5.6-luna**, fallback **gpt-5.6-terra**, `reasoning.effort=none`.
  Both requested model IDs worked in real API calls. Accepted responses returned
  those same identifiers; no more specific model snapshot was supplied.
- Prompt **text-1.1**, extraction schema **text-1.0**, task **text-perception-1**.
  Egyptian/standard Arabic, English and mixed reports; four-state conditions,
  duration, recurrence, reported explanation, per-span temporal qualification and
  machine-readable uncertainties. Missing fields never become negative evidence.
- Citizen text is untrusted user-message data. No model tools, decision fields,
  client-selected models or client-supplied credentials. Exact source quotes are
  checked before any evidence mapping. Reported pipe/cause claims never create
  verified discharge, pipe failure, persistence or root-cause facts.
- At most one Luna repair after invalid output. At most one Terra call after
  repair failure, material admission ambiguity, or explicit deeper review. No
  fallback on ordinary API/authentication/network errors; SDK auto-retries are off.
  Fallback is visibly labeled and retains the primary extraction/reference where
  one validated. Unresolved material ambiguity withholds the whole extraction
  from evidence admission and enters needs review.
- Explicit submission persists a Signal and pending job before an in-process
  background task. SQLite holds original inputs, extraction revisions, validated
  cache, raw structured response text and usage. Restarted pending/analyzing jobs
  become needs review; they never silently resume provider calls.
- Same existing Signal/Store/engine contracts; operational text has a separate
  `converge-text.sqlite3` beside the original replay database. This isolates
  synthetic reset from operator records. Revision plus incident recomputation is
  atomic. Manual corrections preserve original input and prior extraction history.
- Cache identity includes NFC/trim-normalized content hash, exact input hash
  (protecting source-substring validity), task/prompt/schema versions, prompt hash,
  requested model, fallback identifier/policy and reasoning setting. Successful
  cached extractions are revalidated locally. UI distinguishes live/cached/manual.
- New observation form, coordinates/time, reviewed road and capture metadata,
  explicit independence assertion, synthetic-test labeling, processing states,
  extracted claims, quotes, model/fallback detail, engine disposition and human
  correction. No extraction during typing, refresh or read-only polling.
- Default persistent development caps: **80 requests / US$1.00 locally estimated**.
  Reservations enforce the cap across retries/restarts; known text rates are used
  conservatively, including a 1.25 input multiplier. Failed/unknown-usage calls
  retain their reservation. Unknown model pricing fails closed. These are local
  development guards, not an account-wide billing guarantee.

## Actual tests and evaluation

**63 backend tests passed**, including all **38 unchanged Phase 1 tests** and
25 new perception tests (parameterization included). Frontend typecheck and
production build passed. The existing large-bundle advisory remains non-failing;
Starlette emits one dependency deprecation warning. Dependency check passed.

Guard coverage includes strict schema/extra-field rejection, Arabic negative and
resolved-water mapping, historical quarantine, hearsay, uncertainty, injection
exclusion, exact quote checks, one repair, fallback policies, API disconnect,
invalid-key safe errors and no infinite retry, persistent limits, cache while
unavailable, idempotency, duplicate non-inflation, review conflicts/history,
transaction rollback, interrupted-job recovery and operator-owned metadata.
Invalid credentials were verified through the **official SDK with a mocked HTTP
401 transport**, not by altering or exposing Ahmed's real credential. Malformed
responses and API disconnects were also fault-injected; no live provider failure
was needed to fabricate an error demonstration.

### Final authored corpus: 18 development + 18 locked validation reports

The prompt was refined on development only, then frozen before the first locked
validation call. The initial development baseline is retained separately. One
baseline report confused uncertainty about cause with uncertainty about observed
damage; Terra also supplied an unsupported pipe explanation. Prompt text-1.1
corrected this on development. No prompt or labels were tuned using validation.

Counts below measure **current extracted positive assertions before the review
admission gate**. Historical observations remain historical, not current positives.

| Split / field | TP | FP | FN | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| Development water | 7 | 0 | 0 | 100% | 100% |
| Development damage | 3 | 0 | 0 | 100% | 100% |
| Development obstruction | 2 | 0 | 0 | 100% | 100% |
| Locked validation water | 6 | 0 | 0 | 100% | 100% |
| Locked validation damage | 2 | 0 | 0 | 100% | 100% |
| Locked validation obstruction | 1 | 0 | 0 | 100% | 100% |

**Engine-admitted validation water:** 5 TP, 0 FP, 1 FN, precision 100%, recall
83.3%. The withheld report had clear water but uncertain damage; the whole-report
review gate conservatively withheld both. Other admission counts match the table.
Both splits had 2 unresolved-review reports, 2 fallback calls, 0 processing/schema
failures, 0 negation errors and 0 unsupported water/damage/obstruction positives.
There are 14 negation-tagged reports across the two splits. These tiny authored
counts are **not municipal field accuracy**, nor independent engineer annotation.
Explanation/duration/language quality was inspected, not assigned field-accuracy
percentages. Source-substring validation proves textual support exists, not that
all semantic interpretation is infallible.

Machine-readable evidence:

- [Development baseline](docs/text-evaluation-development-baseline.json)
- [Final development live run](docs/text-evaluation-development.json)
- [Final development cached metrics](docs/text-evaluation-development-cached.json)
- [Locked validation live run](docs/text-evaluation-validation.json)
- [Locked validation cached rerun](docs/text-evaluation-validation-cached.json)
- [Validation lock protocol](docs/TEXT_VALIDATION_LOCK.md)

Both full cached reruns covered all 36 reports with **0 OpenAI requests / 36 cache
hits**. These are replays of measured model outputs, not new independent samples.

### Real browser verification

Two new Arabic reports, labeled synthetic tests, were entered using the actual
form and real Luna calls. The first became a watch item; the second formed a
candidate with two captures in the existing engine. An explicit repeat used
cache with 0 provider requests. A road-damage correction created extraction
revision 3 after that cached revision, preserved the original report and showed
Human reviewed. Typing and page refresh made 0 provider calls. No browser errors.

The full Phase 1 production-browser replay passed with non-loopback network
requests blocked: A's eight copies stay one capture/watch, B reaches 68/100,
C stays separate, image ablation yields 52–83, ten duplicates do not inflate,
reset/reload work and local map assets load. Backend socket-blocked replay tests
also pass. This simulates internet loss while preserving the local HTTP server.

[Text browser result](docs/browser-text-result.json) ·
[Offline replay result](docs/browser-replay-result-phase2a.json).
Screenshots: `output/playwright/phase2a-live-candidate.png` and
`output/playwright/phase2a-human-review.png` (ignored local artifacts).

## Actual API usage / cost

As recorded after implementation/evaluation/UI verification:

| Measure | Observed |
|---|---:|
| Total API requests | 63 |
| Primary calls | 56 |
| Fallback calls | 7 |
| Input tokens | 73,546 |
| Output tokens | 7,164 |
| Cache hits | 38 |
| Live schema failures | 0 |
| Local conservative cost estimate | US$0.05516545 |
| Provider-reported billed cost | Not supplied |

Breakdown: original development including smoke 21 calls (18 primary + 3 Terra),
final development 20 (18 + 2), locked validation 20 (18 + 2), UI 2 Luna calls.
All seven fallback calls were triggered by admission ambiguity; schema-failure
and explicit-review fallback routing were separately tested with controlled
responses. No larger reasoning effort was needed for the measured release set.
Usage is cumulative per local text database; current UI values can increase after
this checkpoint. [Saved usage summary](docs/text-usage-observed.json).

## Security / unchanged scoring

- Existing gitignored `.env` reused; never created, rotated, printed or copied the
  credential. Backend reads it via python-dotenv; React receives no key.
- `.env.example` key empty. Scan of source, fixtures, tests, docs and production
  bundle found **0 matches for the actual credential**. `.env` is untracked/ignored.
- Provider exception bodies are not returned/logged; only stable safe error codes.
  SDK request debug logs are disabled. Raw structured response output is local
  SQLite data, with key-value redaction, and has no public raw-response endpoint.
- No model tool access; no arbitrary client model selection. 4,000-character input
  cap, fixed study bounds, operator-reviewed metadata and 500-record local cap.
- Engine SHA-256 unchanged:
  `5fe1a4471281bb0355fe45573610ab9679144401821b80c68c6e76394145b17b`.
- Rules SHA-256 unchanged:
  `7d07908512e641c760e5be40c6dfb4e57e9f30d5950206b9a26159b07f252667`.
  120 m, 6 hours, candidate/risk/hypothesis/evidence-strength formulas untouched.
  Store change adds an optional existing transaction for atomic text revisions;
  it does not change scoring. [Security scan](docs/security-verification.json).

## Known weaknesses / scope limits

1. Very small authored corpus, no field validation or independent label review.
   Negation, quoted speech, temporal mixtures and causality still require broader
   evaluation. Baseline cause hallucination demonstrates this limitation.
2. Whole-report review gating can suppress an otherwise valid positive claim.
   The locked validation water-admission recall of 5/6 records that tradeoff.
3. Presence has no measured severity. Positive evidence keeps its ordinal value
   unknown; reported duration/recurrence do not replace independent timed evidence.
   With unknown road class and rainfall, a text-only candidate can show 0–100
   risk and Limited evidence. This is intentional uncertainty, not a scoring bug.
4. Road assignment and capture independence are operator assertions, not automated
   geospatial matching or authenticated identity. Exact/normalized duplicates are
   handled; paraphrases require shared capture metadata and are not semantically
   deduplicated. No geospatial scope expansion was added.
5. Local single-worker prototype, no authentication or production access control.
   Incident snapshots are as of the last accepted/reviewed extraction. Failed
   reanalysis retains the prior accepted revision; interrupted work requires an
   explicit operator action. There is no automatic provider resumption.
6. Cache identity includes exact text to preserve spans; whitespace/case edits can
   miss cache. Primary model aliases are recorded exactly as returned, not pinned
   to a provider snapshot that was not supplied. Early baseline calls retain only
   provider response IDs; final development/validation also retain local raw text.
7. Final visual polish, image AI, source photographs, verified real roads, field
   outcomes and deployment remain outside Phase 2A.

## Exact Windows run commands

```powershell
Set-Location 'C:\Users\Zoghby\OneDrive - Egyptian Chinese University (ECU)\Documents\ChatGPT\Converge'
npm run build --prefix frontend
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Existing `.env` is loaded server-side. Fresh checkout
setup and exact safe key-entry steps are in [README.md](README.md); never overwrite
Ahmed's existing `.env`. Local QA ran on port 8002 to avoid another local server.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm run typecheck --prefix frontend
npm run build --prefix frontend
.\.venv\Scripts\python.exe -m backend.evaluate_text --split validation
```

The last command is cache-only; add `--live` only to explicitly permit API calls
for missing cache entries. No API request is needed for ordinary pytest/build.

## Recommendation for Phase 2B

After review/authorization, add separately evaluated image perception with sourced
photographs and the same strict provenance/cache/review boundary. First preserve
these text/negation tests and have an engineer review a larger new held-out text
set, particularly partial ambiguity and paraphrases. Keep the scoring rules and
offline replay as regression baselines. **Stopped after Phase 2A; no automatic
continuation to Phase 2B.**
