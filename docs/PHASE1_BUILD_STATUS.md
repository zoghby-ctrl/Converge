# Converge — Phase 1 build status

**Completed:** Implementation Phase 1 — foundation and first structured-input
vertical slice. **Date:** 6 September 2026. **Next phase:** not started.

The application runs locally and offline from reviewed synthetic observations
through SQLite, deterministic incident intelligence, and the municipal workbench.
No OpenAI API calls, extraction, image AI, deployment or custom training occurred.

## Working behavior

- Validated Signal, Evidence, CaptureGroup, RoadContext, Incident,
  IncidentRevision, HypothesisResult, RiskResult and ReviewState contracts.
- Provenance distinguishes synthetic content, simulated placement/time, manual
  annotation, reported/visually suggested/verified/derived evidence, and field review.
- Seven SQLite tables with foreign keys, dataset isolation, indexed observations,
  atomic replay commits, revision history, membership reasons and regrouping lineage.
- Deterministic idempotency/copy handling and normalized exact-text / image-hash
  support. Independent capture counts are separate from raw record counts.
- Inclusive 120 m all-member Haversine bounds, compatible reviewed road IDs,
  six-hour observation-time window, availability gating, metadata exclusion,
  future-clock tolerance and recency decay. No transitive bridge merging.
- Watch/candidate gates, signed feature fusion, explicit unknown/negative/conflict
  states, independent timed persistence, H1/H2/H3 support points, ties and abstention.
- Frozen four-component inspection-triage arithmetic with unrenormalized unknown
  ranges; evidence-strength gates remain independent from risk and hypotheses.
- Evidence/rule traces for membership, exclusion, risk, hypotheses, missing fields,
  conflicts and recommended municipal inspection checks.
- Six requested API routes only; structured datasets enter through demo reset.
- React workbench with separate queues, MapLibre local vectors, selected map labels,
  Cairo replay clock, observation-time timeline, original Arabic/provenance viewing,
  image-family ablation and ten-copy sandbox comparisons.
- Ten bundled development fixtures cover the signature story, missing image data,
  conflicting water, 119/121 m, 5h59/exact 6h/over 6h, chain guard and incompatible roads.

## Actual signature result

| Case | Result |
|---|---|
| Location A: eight identical reports | Eight records, one independent capture, watch item, Limited evidence; 25–75 provisional triage range. |
| Location B: water report + road annotation + later water observation | Three independent captures, candidate tagged water + road condition, Moderate evidence; exact risk 67.5, displayed 68/100. |
| Location C | Separate watch item; cannot bridge into B. |
| Remove B image family | Road condition unknown, two captures, Limited evidence, exact risk 52.5–82.5, displayed 52–83. |
| Add ten copies | No change to risk, hypothesis support or independent-capture counts. |

These are synthetic development results, not real-world predictive accuracy.

## Verification performed

| Check | Actual result |
|---|---|
| Python version | Project-local Python 3.11.16. |
| Backend regression command | `.\.venv\Scripts\python.exe -m pytest -q` — **38 passed in 3.84 s** on the final backend/fixture code. |
| Frontend typecheck | `npm run typecheck --prefix frontend` — **passed**, no TypeScript errors. |
| Production build | `npm run build --prefix frontend` — **passed**, Vite 8.2.2, 19 modules transformed; final build reported 778 ms. |
| Backend launch | Uvicorn started successfully on `127.0.0.1:8000`; health confirms foreign keys and `openai_enabled=false`. |
| Frontend launch | Vite started successfully on `127.0.0.1:5173`; production frontend also served by FastAPI on port 8000. |
| Browser workflow | **15 checks passed**, no failures: start, full replay, A copies, B candidate, C separation, map selection, 1280 layout, ablation, duplicate invariance, Arabic record, reset, repeat replay, reload, blocked external networking, local map. |
| Browser resources | **0 external requests, 0 failed resources, 0 console/page errors** in the final production QA run. |
| Offline backend | Replay and comparison pass while outbound socket connection functions are disabled. |
| Offline browser | Non-loopback requests blocked throughout production loading and replay; all assets and API calls served locally. Physical Wi-Fi was not disabled. |
| Persistence | Restart restores the final state; repeat/reset is deterministic; injected snapshot failure rolls back the entire step; foreign-key check is clean. |
| Visual QA | Inspected screenshots at 1440×900 and 1280×720, including ablation, labeled map locations and selected state. No horizontal page overflow at 1280. |
| Secret/artifact exclusions | `.env`, `.env.local`, virtual environment, local runtime/tools, node_modules and dist verified ignored. No secrets created. |

Browser procedure is `docs/browser-qa.js`. Local QA artifacts (ignored from git):

- `output/playwright/verification.txt`: final machine-readable 15-check result.
- `output/playwright/phase1-signature-1440.png`.
- `output/playwright/phase1-signature-1280.png`.
- `output/playwright/phase1-ablation-1280.png`.

Initial smoke testing found a Windows asyncio test-harness issue, a controlled
checkbox timing issue and missing MapLibre worker/shared-module assets. These
were fixed and the final verification above passed. The map worker now builds
locally with Vite's `?worker&url` handling.

## Exact Windows run commands

The current workspace is prepared. For the reliable single-process demo:

```powershell
Set-Location 'C:\Users\Zoghby\OneDrive - Egyptian Chinese University (ECU)\Documents\ChatGPT\Converge'
npm run build --prefix frontend
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. After building once, only the Uvicorn command is
needed. It serves the frontend and local map assets. Servers are currently running
on 8000 and 5173 from verification; do not start a second server on an occupied port.

For development, use a second PowerShell terminal:

```powershell
Set-Location 'C:\Users\Zoghby\OneDrive - Egyptian Chinese University (ECU)\Documents\ChatGPT\Converge'
npm run dev --prefix frontend -- --port 5173 --strictPort
```

Open **http://127.0.0.1:5173**. Stop the corresponding foreground server with Ctrl+C.
See `README.md` for fresh-checkout dependency installation and browser QA commands.
The local database is `%LOCALAPPDATA%\Converge\runtime\converge.sqlite3`.

## Versions and decisions

- Python 3.11.16; FastAPI 0.115.12; Pydantic 2.13.5; SQLite from the Python runtime.
  Exact tested backend dependencies are in `backend/requirements.txt`.
- Node 24.18.0; React 19.2.8; TypeScript 7.0.2; Vite 8.2.2; MapLibre 6.7.0.
  Direct versions are pinned in `frontend/package.json`, with a committed-ready
  `package-lock.json` for transitive resolution.
- Architecture approval and organizer pre-build permission updated in the freeze;
  obsolete default model removed. Future primary is `gpt-5.6-luna`, fallback is
  `gpt-5.6-terra`, with the requested extraction-only boundary and cache contract.
- The explicit environment examples in section C take precedence over the earlier
  generic "empty values only" statement: API key empty, model names supplied.
- Three schematic synthetic segments replace real road sourcing **for this phase**;
  reviewed road IDs are supplied directly. No nearest-road assignment is claimed.
- Exact generic text is conservatively dependent across the demo dataset. Independent
  author overrides and near-duplicate review are deferred.
- Thirty minutes is the explicit same-time conflict/supersession tolerance. Other
  frozen spatial, temporal, risk and hypothesis weights are preserved.
- Rain context, capture groups and scoring traces use small validated JSON objects
  inside the seven required tables. No speculative future tables were added.
- Python was obtained as a project-local managed runtime after automatic approval
  review rejected a system-installer command. No system Python or PATH changes
  were made. This does not affect running the prepared virtual environment.

Full rationale and limits are in `docs/PHASE1_DECISIONS.md`.

## Known limitations and unimplemented screens/features

There are **no known failing Phase 1 checks**. The remaining limitations are:

1. All demo content and map segments are synthetic. Image-family records are
   structured annotations without photographs. No extraction or AI accuracy has
   been measured; no genuine model-output cache exists yet.
2. One local demo dataset, one serialized backend writer. No arbitrary production
   ingestion, authentication, concurrent editing, correction form, field-outcome
   form, review-state controls or external municipal action. Review states are
   contracted/stored, but the Phase 1 UI does not edit them.
3. Road matching, image preprocessing, near-duplicate adjudication, source
   authentication, source-author independence overrides and long-episode linkage
   remain future work. Greedy bounded grouping may split a real incident.
4. The engine enforces a six-hour active window and a 500-available-record replay
   limit; the structured dataset contract caps stored fixture records at 1,000.
   This is a small demo, not a city-scale performance claim.
5. Same-feature contradiction handling is incident-local and uses a documented
   30-minute heuristic. It cannot resolve differing viewpoints or engineering cause.
6. The frontend build reports a non-failing >500 kB chunk warning. The main bundle
   is approximately 1.19 MB (323 kB gzip), the worker 486 kB, and CSS 90 kB. All
   are local; bundle splitting and final visual design are deferred.
7. Full Arabic interface, source-image UI, extraction jobs/cache/fallback, generic
   manual-entry panel, inspection workflow editing, polished final design and
   deployment are not implemented. The original Arabic report is viewable.
8. No held-out municipality/extraction study, 20-run latency benchmark, three timed
   cold starts, teammate user study or end-to-end raw-input evaluation is claimed.
   The broader freeze's later P0 acceptance gates remain future validation work.

## Files/directories created or changed

- Updated `PRODUCT_ARCHITECTURE_FREEZE.md` and `.gitignore`.
- Created `.env.example`, `README.md`, `BUILD_STATUS.md`, `pytest.ini`.
- Created `backend/app/{models,config,engine,store,main}.py`, package initializers,
  and `backend/requirements.txt`.
- Created frontend package/lock/config files, `src/{main.tsx,types.ts,style.css,vite-env.d.ts}`,
  `index.html`, and local `public/favicon.svg`.
- Created `fixtures/generate.py`, `fixtures/README.md`, package initializer and ten
  JSON development scenarios.
- Created `tests/test_engine.py`, `tests/test_api.py`,
  `docs/PHASE1_DECISIONS.md`, and `docs/browser-qa.js`.
- Prepared ignored `.venv`, `.runtime`, `.tools`, dependency/build directories and
  `output/playwright` QA artifacts. Mutable SQLite is outside the workspace.
- No commit, deployment, external message, paid API call or Phase 2 work performed.

## Phase 2 recommendation

After reviewing this slice, implement one server-side OpenAI provider adapter for
bounded text extraction first. Verify access to the requested model IDs, validate
strict output contracts, and cache successes by content/task/prompt/schema/model
configuration. Add the fallback only for the three allowed triggers. Evaluate
Arabic/English negation, uncertainty and unsupported inference before feeding
outputs into the unchanged local engine. Then add separately evaluated image
perception, sourced photographs and reviewed real local road vectors. Keep the
current fully offline structured replay as the regression baseline.

**Stopped after Phase 1. Phase 2 has not begun.**
