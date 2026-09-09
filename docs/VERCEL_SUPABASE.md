# Vercel + Supabase deployment

Status: **UNVERIFIED UNTIL LIVE DEPLOYMENT**. Local verification does not prove
Supabase connectivity, Vercel routing/runtime packaging, Storage permissions, or
live Gemini access. No commit, push, or cloud deployment is performed by this adaptation.

## Architecture and preserved state

One Vercel project serves Vite static assets and `/report`, `/operations`, plus
the existing FastAPI application through `api/index.py` at `/api/...`.
Frontend API requests remain same-origin. The entrypoint waits for existing
Starlette background jobs before releasing the HTTP response.

`DATABASE_URL` selects PostgreSQL. Without it, local development keeps SQLite;
on Vercel a missing URL fails closed rather than silently using ephemeral SQLite.
Explicit database paths still select SQLite for tests.

The existing two databases map to private `converge_replay` and `converge_live`
schemas. Both retain datasets, road contexts, signals, evidence, incidents,
incident revisions and capture memberships. Live also retains text/image jobs,
extraction revisions, extraction cache, cache events, API usage reservations,
and raw structured provider responses. JSON payloads, IDs and timestamp strings
are unchanged. PostgreSQL identity columns replace SQLite-generated integer IDs;
usage amounts use double precision, matching SQLite REAL.

Transaction-scoped advisory locks serialize shared state operations across
instances. Prepared statements are disabled for transaction-pooler compatibility.
Schema creation is explicit, not a cold-start side effect. New instances do not
mark other instances' running jobs interrupted. The existing engine and Gemini
transport/extraction semantics are unchanged.

Uploaded images must persist for viewing and reanalysis. Their normalized and
metadata-free full-resolution copies go to a private Supabase Storage bucket.
`/tmp` is only a rehydratable cache, never the authoritative copy. Bundled demo
images and context fixtures remain read-only deployment assets.

## Supabase dashboard

1. Create a dedicated Supabase project for this demo. Save the database password
   privately. Do not reuse another application's database/schema.
2. Open **SQL Editor**, paste and run `supabase/schema.sql`. It creates only the
   existing application tables, under two private schemas. Run it as the project
   database owner (`postgres`). Re-running creation is safe and does not reset data.
3. Keep `converge_replay` and `converge_live` out of the Data API's exposed schemas.
   No browser database access or public RLS policies are needed. Schema/table
   access is revoked from PUBLIC, anon and authenticated.
4. Open **Storage → New bucket**. Name it `converge-uploads`, keep it **private**,
   allow JPEG/PNG, and leave the bucket file-size restriction at the project
   default (the metadata-free full-resolution copy may exceed the upload size).
   Do not add public upload/read policies.
5. From **Connect → Transaction pooler**, copy the PostgreSQL URI (port 6543).
   Insert the password, URL-encoding password special characters. Use that URI
   as `DATABASE_URL`. The adapter requires TLS and disables prepared statements.
6. Copy the project URL and server-side legacy **service_role** key from project
   settings/API keys into Vercel's server environment. Never put these in `VITE_*`.

This bootstraps a fresh deployment; it does not copy existing local SQLite rows
or uploads. Local files remain untouched. Run the bundled replay on the new site.

## Vercel dashboard

### Immediate build failure diagnosis (2026-09-10)

Both local HEAD and GitHub `master` currently point to `ddf7735` (Railway
deployment). That commit has no root `package.json`, `vercel.json`,
`requirements.txt`, `.python-version`, or `api/index.py`. The Vercel/Supabase
adaptation is still in the working tree, including untracked deployment files.
Importing that commit with Vite at repository root does not deploy the local
adaptation. The abbreviated build log cannot establish the exact internal error.

The existing local `vercel.json` uses supported configuration: `framework: null`
selects Other and overrides the dashboard preset; explicit frontend commands
build `frontend/dist`; `api/index.py` exports ASGI `app`; root requirements include
backend requirements; `.python-version` pins 3.12. No legacy runtime declaration
or conflicting `builds` configuration needs replacing. Keep the repository root
so backend code and fixtures remain available. API rewrites target `/api`, and
only `/report` and `/operations` rewrite to the SPA; `/` serves its static index.

Commit the complete existing adaptation with explicit file paths after review,
then push and deploy that new commit. Redeploying `ddf7735` cannot include these
local files. No application logic was changed for this diagnosis.

**UNVERIFIED UNTIL LIVE VERCEL REDEPLOYMENT**

After reviewing, committing and pushing the intended files yourself:

1. **Add New → Project → Import Git Repository**. Select the Converge repository.
2. Use repository root (`.`), **Framework Preset: Other**, and Node.js **24.x**.
   Do not set the project root to `frontend` or `backend`.
3. Let `vercel.json` provide these settings:
   - Install: `npm ci --prefix frontend`
   - Build: `VITE_UPLOAD_LIMIT_MB=4 npm run build --prefix frontend`
   - Output: `frontend/dist`
   - Python: `.python-version` selects **3.12**; Python 3.11 remains locally compatible.
   - Function: `api/index.py`, duration 300 seconds. Enable Fluid Compute.
   - API rewrite precedes the two SPA route rewrites; `/` and static assets are
     served directly. Backend code and fixtures are included in the function;
     frontend sources, local secrets and presentation artifacts are excluded.
4. Add these environment variables for **Production**:

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | Supabase transaction-pooler PostgreSQL URI |
   | `CONVERGE_PERCEPTION_PROVIDER` | `gemini` |
   | `GEMINI_API_KEY` | Existing Gemini API secret |
   | `SUPABASE_URL` | Your HTTPS Supabase project URL |
   | `SUPABASE_SERVICE_ROLE_KEY` | Server-only service_role key |
   | `SUPABASE_STORAGE_BUCKET` | `converge-uploads` |

   No `PORT` or `CONVERGE_RUNTIME_DIR` is needed. Existing `OPENAI_MAX_REQUESTS`
   (80), `OPENAI_MAX_SPEND_USD` (1.00), and `OPENAI_FALLBACK_ENABLED` (true)
   still apply to Gemini. Change these only if you intend to change the existing
   development spending limits. `OPENAI_API_KEY` is not required for Gemini.
   The public build variable `VITE_UPLOAD_LIMIT_MB=4` is supplied by the build
   command; it contains no credentials.
5. Use a separate Supabase project/bucket for Preview deployments if enabling
   previews. Pointing previews at Production shares all state, including replay resets.
6. Deploy. Check build/function logs, then use the single assigned
   `https://<project>.vercel.app` URL. Adjust deployment protection so judges can
   open the intended public deployment.

## Live acceptance checks

- Open `/`, `/report`, `/operations` directly and refresh each; inspect browser
  console/network errors. `/api/v1/health` must return JSON; unknown API routes
  must return 404 rather than HTML.
- Run the signature image replay: A has 8 records, 1 capture, Watch; B is 68,
  Moderate, 3 captures. Remove image: 52–83, Limited, 2. Restore: 68, Moderate,
  3. Add ten copies: 13 B records, still 68/Moderate/3.
- Submit one new text observation and a small JPEG/PNG using Gemini. Verify
  processing/revisions, provider provenance and usage accounting.
- View the uploaded image; reanalyze it; redeploy and confirm both the image and
  persisted observations remain. Exercise two concurrent submissions and confirm
  neither is lost. Confirm a cold start does not reset active jobs.

## Known deployment limits

- **UNVERIFIED UNTIL LIVE DEPLOYMENT:** actual PostgreSQL SQL execution/pooler
  behavior, Storage requests, Linux dependency installation, Vercel rewrites,
  function duration and real Gemini calls need the acceptance checks above.
- Vercel limits request bodies to 4.5 MB. The Vercel frontend accepts files up to
  4 MiB, leaving multipart headroom. Local development keeps the existing 5 MiB
  limit. Direct oversized API requests can be rejected by Vercel before FastAPI.
- Processing completes within the request lifetime. A platform hard timeout or
  crash can leave a pending/analyzing job; there is no durable worker queue.
  After confirming no requests are running, recover affected jobs in SQL Editor:

  ```sql
  UPDATE converge_live.text_jobs
  SET status='needs_review', error_code='interrupted_restart'
  WHERE status IN ('pending','analyzing');
  UPDATE converge_live.image_jobs
  SET status='needs_review', error_code='interrupted_restart'
  WHERE status IN ('pending','analyzing');
  ```

  Then retry explicitly through the existing UI. Do not run this while jobs are active.
- This remains the existing shared prototype: public submissions/replay controls
  and the 500-observation cap are unchanged. Locks favor correctness over throughput.
  Existing development usage limits remain the bound on paid provider calls.
- Warm instances retain temporary image copies; a large upload session can reach
  the platform's temporary-disk limit. Storage remains the durable source.

## Local verification performed

- Full backend suite: **167 passed**, Python **3.11.16**; one existing Starlette
  deprecation warning. After removing an unsafe temporary-file deletion for
  concurrent uploads, its focused Storage test also passed.
- Vercel-mode frontend production build (4 MiB upload limit): TypeScript check
  and Vite build passed. Existing large-chunk warning remains.
- Browser smoke: home rendered; `/report` and `/operations` loaded directly and
  refreshed; zero console errors on both routes. These used the built frontend
  and ASGI entrypoint locally, not Vercel's cloud rewrites.
- Signature image replay/ablation/restoration/ten-copy invariants passed through
  the ASGI entrypoint. PostgreSQL connection/locking and Storage transports were
  tested with mocks; no live PostgreSQL or Supabase service was exercised.
- Credential-pattern scan found only synthetic test URLs. Actual local secret
  values were absent from tracked files, added deployment files and built assets.
  `.env` is untracked/ignored. `git diff --check` passed.

References: [Vercel Python runtime](https://vercel.com/docs/functions/runtimes/python),
[Python API directory](https://vercel.com/docs/functions/runtimes/python/api-directory),
[Vercel payload limit](https://vercel.com/docs/errors/function_payload_too_large),
[Supabase pooler](https://supabase.com/docs/guides/database/connecting-to-postgres),
[Supabase Storage uploads](https://supabase.com/docs/guides/storage/uploads/standard-uploads).

## Working tree at handoff

Pre-existing presentation/deck artifacts below are untouched. Nothing was staged, committed or pushed.

```text
 M .env.example
 M backend/app/image_observations.py
 M backend/app/main.py
 M backend/app/observations.py
 M backend/app/perception.py
 M backend/app/store.py
 M backend/requirements.txt
 M frontend/src/ObservationPanel.tsx
 M frontend/src/ReportSurface.tsx
?? .codex-finalizer/
?? .deck-build/
?? .deck-final-inspect-v2/
?? .deck-final-inspect-v3/
?? .deck-final-inspect-v4/
?? .deck-final-inspect/
?? .deck-inspect/
?? .deck_dump.mjs
?? .deck_edit.mjs
?? .deck_edit2.mjs
?? .deck_final_inspect.mjs
?? .deck_finalize.mjs
?? .deck_inspect.mjs
?? .deck_runs.mjs
?? .deck_test_set.mjs
?? .python-version
?? .vercelignore
?? Converge_IMPACTX_2026.pdf
?? Converge_IMPACTX_2026.pptx
?? api/
?? backend/app/postgres_store.py
?? backend/app/upload_storage.py
?? docs/FINAL_PRESENTATION_SPEC.md
?? docs/TEAM_CODE_DEFENSE_GUIDE.md
?? docs/TEAM_ORAL_EXAM.md
?? docs/VERCEL_SUPABASE.md
?? docs/presentation/
?? frontend/src/uploadLimit.ts
?? generate_deck.py
?? requirements.txt
?? supabase/
?? tests/test_vercel_deployment.py
?? vercel.json
```

Suggested commit message: `Adapt Converge deployment for Vercel and Supabase`
