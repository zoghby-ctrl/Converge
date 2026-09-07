# Converge — Phase 5 Release QA Report

**Date:** 8 September 2026  
**Auditor / Engineering Team:** Control Alt Delete (IMPACTX 2026 Smart Cities)  
**Status:** Verified — All Blockers Surgically Resolved  
**Git Commit Status:** Uncommitted (per instruction)

---

## 1. Audit Finding Verdicts & Resolutions

| Finding ID | Severity | Description | Verdict | Resolution / Evidence |
|---|---|---|---|---|
| **SYS-HIGH-01** | High | Phase 4 orphaned `ObservationPanel` review/correction workflow | **CONFIRMED & FIXED** | Re-integrated human review and correction directly into `/operations` Review tab (Tab 4 of `TabbedInspector`). Directly reuses backend `POST /api/v1/signals/{sid}/review` contracts and exported `ReviewForm` / `ImageReviewForm` components. Retains immutable source, appends revision lineage, and recomputes incident triage. |
| **SYS-HIGH-02** | High | OpenAI quota exhausted (80/80 requests) blocking live submissions | **REFUTED / REJECTED** | Auditor read static offline evaluation report (`docs/image-usage-observed.json`). The actual live runtime database (`%LOCALAPPDATA%\Converge\runtime\converge-text.sqlite3`) has **2 total requests**, **$0.00087225 spent**, and **78 requests remaining**. Live submissions are completely functional and unblocked. Zero database records were tampered with or reset. |
| **SYS-MED-01** | Medium | HTML5 geolocation silently substitutes Street 14 coordinates for out-of-area GPS | **CONFIRMED & FIXED** | Real detected GPS coordinates are preserved without alteration. If coordinates fall outside the Nasr City boundary (30.045°–30.063° N, 31.325°–31.346° E), an amber warning banner is displayed with honest explanations and one-click study presets (Street 14, Al-Tayaran, Youssef Abbas). Submissions outside the boundary are cleanly blocked with an explanatory error. |
| **SYS-MED-02** | Medium | Failed offline submission loses entered text and photo silently | **CONFIRMED & FIXED** | On network failure or offline state, form state (`text`, `file`, `lat`, `lon`) is strictly preserved in memory. Displays explicit notice: *"Offline: Report was NOT sent. Your entered text and photo are preserved. You can retry sending once your connection is restored."* The submit button transitions to a retry state. |
| **SYS-LOW-01** | Low | Service worker navigation handler used un-awaited Promise OR fallback | **CONFIRMED & FIXED** | Updated `frontend/public/sw.js` navigation handler from `caches.match('/index.html') \|\| caches.match('/')` to `caches.match('/index.html').then((cached) => cached \|\| caches.match('/'))`. |
| **DOCS-01** | Low | README stated Phase 4 was deferred and claimed database was at 80/80 cap | **CONFIRMED & FIXED** | Updated `README.md` and `BUILD_STATUS.md` to reflect Phase 4 and Phase 5B delivery. Removed all exaggerated claims; honestly stated boundaries (prototype risk weights, historical ERA5 demo context, no municipal partnerships or maintenance suite). |

---

## 2. Runtime AI Ledger State

The live SQLite database was directly inspected via SQL queries:
- **Database Path:** `%LOCALAPPDATA%\Converge\runtime\converge-text.sqlite3`
- **Total Recorded Requests:** `2`
- **Configured Cap (`OPENAI_MAX_REQUESTS`):** `80`
- **Available Requests Remaining:** `78`
- **Total Spend Recorded:** `$0.00087225`
- **Configured Spend Cap (`OPENAI_MAX_SPEND_USD`):** `$1.00`
- **Live Submission Blocker:** **FALSE** (Live submissions are active and accepted)

---

## 3. Automated Test Suite Verification

- **Full Suite Run:** `pytest`
- **Total Tests:** **126 passed** (0 failed, 1 warning for deprecated starlette portal alias)
- **Duration:** 23.80 seconds
- **New Regression Tests Added (`tests/test_phase5_blocker_fixes.py`):**
  1. `test_app_version_metadata`: Verifies FastAPI title and v4.0 version.
  2. `test_out_of_area_geolocation_rejected_by_backend`: Verifies backend rejects out-of-study coordinates with HTTP 422 and accepts study area coordinates.
  3. `test_human_review_and_correction_lineage`: Verifies submission, processing state, review correction incrementing revision to 2, provenance annotation updating to `human_reviewed`, reviewer recording, raw source preservation, and incident triage recomputation.
  4. `test_service_worker_promise_fallback_fix`: Verifies `.then((cached) => cached || caches.match('/'))` pattern in `/sw.js`.
  5. `test_runtime_ai_ledger_sanity`: Verifies ledger tracking under quota.
- **Frontend Verification:**
  - `npm run typecheck`: **0 errors**
  - `npm run build`: **Built successfully** in 852 ms

---

## 4. End-to-End Demonstration Script

To present the system to judges:

### Step 1: Launch Backend
```powershell
Set-Location 'C:\Users\Zoghby\OneDrive - Egyptian Chinese University (ECU)\Documents\ChatGPT\Converge'
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```
Open `http://127.0.0.1:8000`.

### Step 2: Gateway & Mobile Citizen Signal Capture (`/report`)
1. Click **Report Observation** or navigate to `/report`.
2. Enter observation text (e.g. `مياه متراكمة في الحارة اليمين وكسر في الأسفلت`).
3. Note the location pill:
   - Shows detected or preset location in Nasr City study area.
   - If an out-of-area coordinate is entered, the warning banner immediately appears with study presets.
4. Click **Send observation**. Observe instant receipt screen with signal ID and timestamp.

### Step 3: Municipal Operations Workbench (`/operations`)
1. Click **Open operations workbench** or navigate to `/operations`.
2. Inspect the Incident Queue and MapLibre canvas:
   - Road network is highlighted.
   - Spatial threshold guide shows `≤120 m all-member correlation threshold`.
3. In the Inspector pane, click **Review** (Tab 4):
   - View the submitted signal, its extraction status, model/provider, and exact quote spans.
   - Click **Correct this observation**.
   - Modify the extracted condition or severity, enter Reviewer Name (`Eng. Municipal Team`) and Reason (`Field inspection confirmation`).
   - Click **Save corrected revision**.
   - Observe: Revision increments from 1 to 2; provenance reflects `human_reviewed`; incidents and risk scores immediately recompute on the map and queue.

### Step 4: Replay & Audit Sandbox
1. Click **Replay & Audit** in the top navigation.
2. Step through `signature_image` or `context_signature` replay.
3. Test **Hide image evidence** or **Add 10 duplicates** to demonstrate duplicate invariance.

---

## 5. Explicit Prototype Boundaries & Limitations

1. **Study Area:** Restricted to Nasr City sector (30.045°–30.063° N, 31.325°–31.346° E). Coordinates outside this bounding box are not accepted.
2. **Weather Context:** Uses authentic Open-Meteo ERA5 historical reanalysis data for January 2025. It is not real-time radar or live precipitation forecasts.
3. **Risk Formulas:** Prototype heuristic formulas based on civil engineering principles, not officially calibrated municipal department weights.
4. **Offline Capability:** Application shell is cached offline via PWA service worker. Submissions require network connectivity; failed offline submissions preserve entered form state for immediate retry.
5. **Human Authority:** AI perception is strictly bounded to extracting asserted claims and visible features; deterministic correlation and human operators hold sole authority over incident triage and confirmation.
