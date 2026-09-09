# Railway deployment

Deploy from the repository root as one Docker service. No separate frontend service,
build command override, or start command override is needed. `railway.json` selects
the Dockerfile, one replica, and `/api/v1/health` as the deployment health check.

The Node 24.18.0 build stage runs `npm ci` then `npm run build` in `frontend`
(TypeScript checking followed by Vite). The Python 3.11.16 runtime installs the
existing pinned `backend/requirements.txt`, copies backend and bundled fixtures,
and serves the compiled frontend through the existing FastAPI static routes.
Base image version tags are fixed; they are not immutable digest pins.

The Docker CMD uses a shell to expand Railway's port, then replaces the shell:

```sh
exec python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
```

`/`, `/report`, `/operations`, static assets, and `/api/...` share that port.
The Vite development proxy is not used in production. Keep one worker and one
replica to preserve existing process-local coordination and SQLite behavior.

## Railway setup

1. Ensure the deployment source includes all application files. In the inspected
   workspace, `frontend/src/display.ts` already existed but was untracked and is
   imported by tracked components. Include it when preparing your eventual commit;
   a Git-only deployment without it will fail. This deployment task does not commit.
2. Create a service from this repository with the repository root as its root directory.
3. Attach a persistent Railway volume to this service at `/data` before first use.
4. Set these service variables in Railway:

   | Variable | Value |
   | --- | --- |
   | `CONVERGE_RUNTIME_DIR` | `/data` |
   | `CONVERGE_PERCEPTION_PROVIDER` | `gemini` |
   | `GEMINI_API_KEY` | Supply the real key only through Railway secrets/service variables |
   | `PORT` | Supplied by Railway; do not hardcode |

5. Deploy and generate a public domain. Check `/api/v1/health` and the three page
   routes. Health and replay checks do not call perception providers.

No OpenAI key is required for Gemini. Existing perception configuration reads the
root `.env` and then overlays process environment variables. The Docker build
excludes `.env` files entirely; do not supply keys as build arguments or Vite variables.
The health endpoint's existing `configured` fields reflect the OpenAI key and are
not a Gemini readiness test; their semantics are unchanged.

## Persistence and local fallback

With `CONVERGE_RUNTIME_DIR=/data`, replay data is `/data/converge.sqlite3`, live
observations/cache/usage are `/data/converge-text.sqlite3`, and uploaded normalized
images are under `/data/images`. SQLite files and images survive restarts and
redeployments **only when the same persistent volume remains attached**. Merely
setting the variable does not provision a volume. Existing local data is not
automatically copied to Railway. Volume deletion loses that data; configure backups
in Railway as appropriate. Volume-backed redeployments can have brief downtime.

Without the override, Windows retains `%LOCALAPPDATA%/Converge/runtime`; when
`LOCALAPPDATA` is absent, the existing fallback is `~/.local/Converge/runtime`.
Export `CONVERGE_RUNTIME_DIR` in the process environment (it is not read from `.env`).
The default local port remains 8000. Container storage without a volume is ephemeral.

## Optional local Docker smoke

```sh
docker build -t converge .
docker volume create converge-data
docker run --rm --name converge -p 8000:8000 -e PORT=8000 -e CONVERGE_RUNTIME_DIR=/data -e CONVERGE_PERCEPTION_PROVIDER=gemini -v converge-data:/data converge
```

This smoke needs no API key. Exercise health, pages, and bundled replay; stop and
rerun with the same volume to verify replay state survives. Do not submit uncached
text or image extraction during deployment preparation.

## Preparation verification

- 155 tests passed (153 existing plus two deployment storage tests), with external
  socket connections blocked and provider keys blanked; one dependency deprecation warning.
- Frontend typecheck and production build passed; Vite reported a large-chunk warning.
- Real local Uvicorn startup on `0.0.0.0` with port 18763 passed health and page checks.
- Signature: `68 / Moderate / 3`; image removal: `52–83 / Limited / 2`;
  restore: `68 / Moderate / 3`; ten duplicates: `68 / Moderate / 3`.
- Replay state survived a real process restart with the same configured directory.
- `git diff --check` passed. Secret-pattern scan of 154 tracked, deployment, and
  frontend build files found no matches (not a guarantee against every secret format).
- Docker was unavailable: Linux image build and container/volume execution remain
  unverified. The runtime Python version matches the local test environment.
- No live provider calls, Railway deployment, staging, or commit was performed.

References: [Dockerfiles](https://docs.railway.com/builds/dockerfiles),
[start commands](https://docs.railway.com/deployments/start-command),
[health checks](https://docs.railway.com/deployments/healthchecks),
[service persistence](https://docs.railway.com/services).
