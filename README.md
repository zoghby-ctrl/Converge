# Converge

Phase 2A: a local municipal inspection workbench with OpenAI text perception and
an offline structured replay. Team: **Control Alt Delete**, IMPACTX 2026 Smart Cities.
AI extracts report claims; the existing deterministic engine controls membership,
risk, hypotheses and evidence strength. Image inference and deployment are deferred.

## Run on this Windows machine

Open PowerShell in the repository. Dependencies and a Python 3.11 virtual
environment have already been prepared here.

```powershell
Set-Location 'C:\Users\Zoghby\OneDrive - Egyptian Chinese University (ECU)\Documents\ChatGPT\Converge'
npm run build --prefix frontend
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. The backend serves the production frontend and all
map assets. After the first build, only the last command is needed. The prepared
structured replay requires no internet. New uncached text analysis uses OpenAI;
cached analysis and human correction work locally.

For frontend development, leave the backend running and open a second terminal:

```powershell
Set-Location 'C:\Users\Zoghby\OneDrive - Egyptian Chinese University (ECU)\Documents\ChatGPT\Converge'
npm run dev --prefix frontend -- --port 5173 --strictPort
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to the local backend. Use one
backend process. Stop servers with Ctrl+C. No activation, Docker or GPU setup is
required. The backend's SQLite file is outside OneDrive at
`%LOCALAPPDATA%\Converge\runtime\converge.sqlite3`.

## Fresh checkout setup

Install Python 3.11 and Node.js 22.12+ (tested here with 24.18.0), then:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
```

On this prepared machine the local runtime lives under `.runtime`, so the
existing `.venv` works even though `py -3.11` does not resolve a system install.
`.venv`, `.runtime`, and `.tools` are ignored and are not portable checkout files.

The backend reads the repository `.env`; process environment values take precedence.
Ahmed's Converge API key is already there and must be reused. Never copy the example
over that file. On a **fresh checkout only**, prepare the file if it is missing:

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
notepad .env
```

Enter your API key locally in `OPENAI_API_KEY`, save, close the editor and restart
the backend. Do not paste it into chat, React, a fixture or a command line.
`.env` is gitignored and `.env.example` contains no credentials.

```dotenv
OPENAI_PRIMARY_MODEL=gpt-5.6-luna
OPENAI_FALLBACK_MODEL=gpt-5.6-terra
OPENAI_FALLBACK_ENABLED=true
OPENAI_REASONING_EFFORT=none
OPENAI_MAX_REQUESTS=80
OPENAI_MAX_SPEND_USD=1.00
```

Defaults apply when optional entries are missing. Usage limits persist in the
local text database; restarting does not reset them. The spend limit uses a
conservative local token-price estimate and reservations, **not provider-reported
billing**. Unknown/unpriced model IDs fail closed. SDK retries are disabled. Luna
gets at most one schema repair; Terra is called only after that fails, for material
admission ambiguity, or through **Deeper review with Terra**. Remaining ambiguity
requires human review. Use one local backend worker; no background API polling.

## Enter and review a report

1. Click **New observation**. Enter text, coordinates within the existing study
   extent, observation time, location accuracy, operator and reviewed road segment.
2. Confirm capture independence only when the source supports it. Copies share
   a capture group. Uncertain independence prevents engine admission. Mark authored
   demo reports as **synthetic** so provenance does not imply field collection.
3. Click **Submit for text analysis**. Pending/analyzing jobs become processed,
   needs review or failed. The saved report, exact source quotes, temporal claims,
   model, fallback reason and live/cached/manual origin remain visible.
4. The operator queue shows the engine's watch/candidate result or admission
   exclusions. **Correct extraction** appends a human-reviewed revision and
   recomputes locally. The original report and prior revisions remain unchanged.
5. **Show offline replay** returns to Phase 1. Reset affects only that synthetic
   dataset, not operator records, extraction revisions, cache or usage.

Text presence alone does not measure severity. Positive evidence therefore has
unknown ordinal severity; reported duration does not establish independently
corroborated persistence. Text-only risk can remain **0–100** with Limited evidence.
Road class/rainfall stay unknown; the LLM never fills those gaps. The incident
clock is the last local computation, not a continuously refreshed forecast.

Operator data is stored at `%LOCALAPPDATA%\Converge\runtime\converge-text.sqlite3`.
Raw structured response text is local-only; OpenAI requests use `store=false`.
No automatic job resumption occurs after restart: interrupted jobs require an
explicit retry or manual review. A failed reanalysis retains the last accepted
revision as the active evidence until a replacement is accepted.

## Replay the signature story

1. Select `signature`, click **Reset**, then **Start replay**.
2. **Advance**: A now contains eight copies, one capture, and remains a watch item.
3. **Advance** twice: B receives an Arabic water report and an independent
   image-family road annotation. A candidate forms.
4. **Advance**: later independent water evidence establishes temporal persistence.
5. **Advance**: C stays separate. B has three captures, Moderate evidence, and a
   **68/100** inspection-triage index.
6. Select B and enable **Hide image evidence**. Road condition becomes unknown,
   evidence drops to Limited, and the risk range becomes **52–83**.
7. Restore images and enable **Add 10 duplicates**. No risk, support-point or
   independent-capture inflation occurs. Comparisons never alter the saved replay.

Expand calculation, membership and hypothesis sections to inspect evidence/rule
IDs. Open an evidence record for original Arabic and provenance. The timeline
uses observation time; availability controls what each replay step can know.

All Phase 1 reports, image-family annotations, rainfall, road segments, locations
and event times are synthetic. No photographs or cached model outputs are included.
The map is an explicitly labeled schematic in the Nasr City study extent. Nothing
in the demo claims a real incident, a physical diagnosis, or a failure probability.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm run typecheck --prefix frontend
npm run build --prefix frontend
```

Browser QA uses the Playwright CLI (not required to run the demo). With the
production backend running:

```powershell
New-Item -ItemType Directory -Force output\playwright | Out-Null
npx --yes --package @playwright/cli playwright-cli -s=converge open http://127.0.0.1:8000 --headed
npx --yes --package @playwright/cli playwright-cli -s=converge run-code --filename docs/browser-qa.js
```

The browser check blocks every non-loopback request, drives the complete replay,
checks reset, comparisons, Arabic record viewing, local resource failures and
1280×720 layout, and saves screenshots under `output/playwright`. Initial CLI
installation may need the internet. This is a simulated loss of external network
access while retaining the local server, not a physical Wi-Fi disconnection.

## Project layout

- `backend/app/models.py`: validated domain contracts and provenance.
- `backend/app/config.py`, `engine.py`: versioned, network-free correlation/scoring.
- `backend/app/store.py`, `main.py`: SQLite and API wiring.
- `backend/app/text_contract.py`, `perception.py`, `observations.py`: strict text
  contract, server-only Responses adapter, cache/usage and durable review workflow.
- `backend/evaluate_text.py`: explicitly invoked development/validation evaluation.
- `frontend/`: React, TypeScript, Vite and MapLibre municipal workbench.
- `fixtures/`: ten reproducible structured development scenarios and their authoring script.
- `tests/`: engine guards, persistence, API, isolation and offline regression checks.
- `docs/`: implementation decisions and browser QA procedure.
- `PRODUCT_ARCHITECTURE_FREEZE.md`: approved product/architecture source of truth.
- `BUILD_STATUS.md`: actual verification results, limitations, and Phase 2 recommendation.

## API

`GET /api/v1/health`, `GET /api/v1/incidents`,
`GET /api/v1/incidents/{id}`, `GET /api/v1/signals/{id}`,
`POST /api/v1/demo/replay`, and `POST /api/v1/demo/compare`.

The replay endpoint accepts `{ "action": "reset|start|advance", "scenario": "signature" }`.
Only reset accepts a full reviewed synthetic `dataset` following the JSON fixture
contract. Reset replaces the dedicated demo dataset. Start is idempotent once
started; advance at the end is a no-op. Invalid data returns 422; unavailable IDs
return 404; comparison before starting returns 409. There are no authentication,
deployment, chatbot or external dispatch endpoints.

The compare body is `{ "disable_families": ["image"], "add_duplicates": 0 }`.
Duplicates can range from 0 to 10. The returned sandbox is recomputed from the
current analysis clock with the same engine and never committed.

Implementation interpretations and deferred pieces are in
[`docs/PHASE1_DECISIONS.md`](docs/PHASE1_DECISIONS.md). Phase 2A implementation and
measured results are in [`BUILD_STATUS.md`](BUILD_STATUS.md). Stop after text
perception; Phase 2B needs a separate instruction.

Additional APIs:

- `POST /api/v1/signals`: durable text submission (202); client idempotency key.
- `GET /api/v1/signals/{id}/processing`: job state, original, revisions and engine disposition.
- `GET /api/v1/observations`: saved text jobs; never initiates extraction.
- `POST /api/v1/signals/{id}/review`: `{extraction, reviewer, reason, expected_revision}`.
- `POST /api/v1/signals/{id}/reanalyze`: `{action: "retry_primary"|"deeper_review", expected_revision}`.
- `GET /api/v1/live/incidents`: operator dataset using the unchanged engine contracts.
- `GET /api/v1/perception/usage`: persistent requests, primary/fallback calls, tokens and cache hits.

`GET /api/v1/health` retains Phase 1's offline mode fields; `text_perception` separately
reports server configuration without returning credentials. Inputs are capped at
4,000 characters and 500 stored operator observations. No client model/key fields
are accepted. Schema failures and provider errors return safe job error codes.

## Text evaluation and browser checks

These commands reuse cached validated outputs without making OpenAI calls:

```powershell
.\.venv\Scripts\python.exe -m backend.evaluate_text --split development
.\.venv\Scripts\python.exe -m backend.evaluate_text --split validation
```

On a machine without this cache, missing cases are reported as `not_cached`.
For an explicitly billed run on cache misses, append `--live`. Development has 18
reports; the locked validation set has 18. Reports go to `docs/text-evaluation-*.json`.
Do not tune using validation and then describe a rerun as held-out accuracy.

The text browser check submits two clearly labeled synthetic reports to the real
OpenAI adapter, checks watch-to-candidate formation, cache reuse, human revision
history, original preservation and no refresh-triggered inference:

```powershell
npx --yes --package @playwright/cli playwright-cli -s=converge open http://127.0.0.1:8000 --headed
npx --yes --package @playwright/cli playwright-cli -s=converge run-code --filename docs/browser-text-qa.js
```

Run this on a fresh operator dataset/segment for its initial-watch assertion.
The UI test can make two provider calls; it is not run automatically by pytest.
