# Real-Time Testing Dashboard

A real-time QA observability dashboard with a FastAPI backend and a React frontend.

## Features

- Live updates over WebSocket (`/ws`)
- Run and case tracking (`/api/runs`, `/api/cases/{id}/status`)
- Dashboard summary aggregation (`/api/summary`)
- Module quality trends, environment spread, and KPI cards
- Demo simulator that auto-progresses running test cases
- Demo control to create synthetic runs instantly

## Tech stack

- Backend: FastAPI, SQLAlchemy, Alembic, Uvicorn
- Frontend: React + TypeScript + Vite
- Realtime transport: WebSocket

## Project structure

- `app/` - FastAPI app, models, repository, realtime manager, static/template fallback
- `migrations/` - Alembic migration scripts
- `scripts/seed_demo.py` - inserts sample data
- `frontend/` - React dashboard client
- `qa_dashboard.db` - SQLite database file
- `render.yaml` - Render Blueprint for backend (DB: Neon or any Postgres URL in `DATABASE_URL`)
- `.python-version` - Python **3.11.9** for [Render](https://render.com/docs/python-version) (avoids 3.14 default → `pydantic-core` Rust build failures)
- `runtime.txt` - same version (kept for other hosts that still read it)

## Local development

### 1) Backend setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python -m scripts.seed_demo
```

### 2) Frontend setup

```bash
cd frontend
npm install
cd ..
```

### 3) Run in development mode (two terminals)

Terminal A (backend):

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal B (frontend):

```bash
cd frontend
npm run dev
```

Open `http://127.0.0.1:5173`.

Vite is configured to proxy:

- `/api` -> `http://127.0.0.1:8000`
- `/ws` -> `ws://127.0.0.1:8000`

Backend env vars:

- `DATABASE_URL` (default: `sqlite:///./qa_dashboard.db`)
- `CORS_ORIGINS` (comma-separated, example: `http://127.0.0.1:5173`)
- `AUTO_CREATE_SCHEMA` (`true` for local quick-start; set `false` in production with Alembic)
- `DATA_SOURCE` (`demo` or `github`)
- `GITHUB_ACTIONS_INGEST_TOKEN` (required when `DATA_SOURCE=github`)

## Production-style run (FastAPI serves React build)

Build frontend:

```bash
cd frontend
npm run build
cd ..
```

Start backend:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

When `frontend/dist` exists, FastAPI serves the React app and asset bundle.

## Deploy as SaaS (Free tier): Vercel + Render (+ Neon Postgres)

### A) Postgres on Neon (recommended)

1. In [Neon Console](https://console.neon.tech), create a project (pick a region near your Render service).
2. Open **Dashboard** → **Connection details**, copy the **connection string** (use the **pooled** URI if Neon offers it).
3. Leave the string as `postgresql://` or `postgres://` — the app normalizes it for SQLAlchemy (see [`app/database.py`](app/database.py)).

### B) Backend web service on Render

1. Push this repo to GitHub/GitLab/Bitbucket.
2. Render → **New** → **Blueprint** → select the repo branch.
3. Render reads [`render.yaml`](render.yaml) and creates **`realtime-testing-dashboard-api`** (no Render Postgres).
4. When prompted (or under **Environment**), set:
   - **`PYTHON_VERSION`** — `3.11.9` (required if you use **New Web Service** instead of Blueprint — Render’s default for new services is **3.14.x**, which breaks this stack; see [Render: Python version](https://render.com/docs/python-version)).
   - **`DATABASE_URL`** — paste the Neon connection string (must include TLS, e.g. `?sslmode=require` if Neon provides it).
   - **`CORS_ORIGINS`** — comma-separated frontend origins; for Vercel use `https://<your-project>.vercel.app` (add preview URLs if you use them — browsers send the exact `Origin`).
5. Deploy and wait for **Live**. Check: `https://<your-render-service>.onrender.com/api/health`

The repo root includes [`.python-version`](.python-version) so Render installs **3.11.9** automatically on the **next** clone after you merge/push — but an already-created service won’t pick that up until you clear build cache or rely on **`PYTHON_VERSION`** above.

Each deploy runs `alembic upgrade head` before Uvicorn starts, so the Neon schema stays in sync with [`migrations/`](migrations/).

#### Optional Render-only Postgres (legacy)

Older revisions of this repo shipped a **`databases:`** block in `render.yaml`. If you prefer managed Postgres **on Render** instead of Neon, remove `DATABASE_URL` from the Blueprint env, add a **`databases:`** entry named `realtime-testing-dashboard-db`, and set `DATABASE_URL` with `fromDatabase` as in Render’s Postgres docs — or create a Postgres instance in the dashboard and paste its **Internal** or **External** URL into `DATABASE_URL`.

If Render shows **Deploy failed** during **Build** with **`pydantic-core`** / **`maturin`** / **read-only file system** errors, the service is using **Python 3.14+** without a prebuilt wheel. Fix: set **`PYTHON_VERSION`** to **`3.11.9`** (Render dashboard → **Environment**), or merge [`.python-version`](.python-version) and redeploy. Avoid relying on `runtime.txt` alone — [Render’s documented](https://render.com/docs/python-version) signals are **`PYTHON_VERSION`** and **`.python-version`**.

Backend startup command runs migrations before boot:

```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### C) Deploy frontend on Vercel

1. Import the `frontend/` directory as a Vercel project.
2. Set environment variable in Vercel (optional if you use the committed default):

```bash
VITE_API_BASE_URL=https://<your-render-service>.onrender.com
```

The frontend includes [`frontend/.env.production`](frontend/.env.production) so production builds default to the Render API URL above—**redeploy Vercel after changing API or data**, or the browser can keep showing an old bundle / cached responses.

3. Build settings:
   - Build command: `npm run build`
   - Output directory: `dist`

### D) Verify production deployment

Run these checks after deploy:

- Open `https://<your-project>.vercel.app` and confirm dashboard loads.
- Confirm backend health: `https://<your-render-service>.onrender.com/api/health`.
- Click `Create Demo Test Run`; verify new run appears in the table.
- Keep the page open and confirm live updates continue via WebSocket.
- Restart backend in Render and verify data persists (Postgres-backed).

## Real data from GitHub Actions (optional)

Set `DATA_SOURCE=github` on the backend and set a strong `GITHUB_ACTIONS_INGEST_TOKEN`.

In GitHub repo settings, add a secret:

- `DASHBOARD_INGEST_TOKEN`: same value as `GITHUB_ACTIONS_INGEST_TOKEN`

Then add a workflow step to POST results to the dashboard:

```yaml
name: Tests
on:
  push:
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: |
          # run your tests here and produce results you can map into JSON
          echo "ok"

      - name: Publish results to dashboard
        env:
          DASHBOARD_URL: https://realtime-testing-dashboard-api.onrender.com
          DASHBOARD_INGEST_TOKEN: ${{ secrets.DASHBOARD_INGEST_TOKEN }}
        run: |
          cat > payload.json <<'EOF'
          {
            "suite_name": "GitHub Actions CI",
            "environment": "CI",
            "build_version": "${{ github.sha }}",
            "test_cases": [
              {"name":"Example test 1","module":"CI","status":"PASSED","duration_ms":10},
              {"name":"Example test 2","module":"CI","status":"FAILED","duration_ms":12,"defect_id":"GH-ISSUE-123"}
            ]
          }
          EOF

          curl -sS -X POST "$DASHBOARD_URL/api/ingest/github-actions/run" \
            -H "Content-Type: application/json" \
            -H "X-Ingest-Token: $DASHBOARD_INGEST_TOKEN" \
            --data-binary @payload.json
```

Example: zip the Playwright HTML output and send it with the same JSON payload (so the dashboard can render the full report):

```bash
# From the repo root after tests, with playwright-report/ on disk:
( cd playwright-report && zip -qr ../report.zip . )
curl -sS -X POST "$DASHBOARD_URL/api/ingest/github-actions/run-with-report" \
  -H "X-Ingest-Token: $DASHBOARD_INGEST_TOKEN" \
  -F "payload=@payload.json;type=application/json" \
  -F "report_zip=@report.zip;type=application/zip"
```

Notes:
- In `DATA_SOURCE=github` mode, the UI demo button is hidden and `POST /api/runs` is disabled; ingestion must go through `/api/ingest/github-actions/run`.
- You can map your real test framework output into the `test_cases` array (name/module/status/duration/optional defect_id).
- **HTML test reports (Playwright / multi-file):** GitHub Actions **artifacts are zips, not a public URL**, so the dashboard cannot load them unless you **upload the report** to the API. Use `POST /api/ingest/github-actions/run-with-report` with `multipart/form-data`: form field `payload` = same JSON as today (`TestRunCreate`), and optional file part `report_zip` = a zip of the HTML report folder (e.g. zip the contents of `playwright-report/`). The API stores the zip and serves `GET /api/runs/{id}/report/...` for the embedded viewer. Requires `python-multipart` on the server (listed in [`requirements.txt`](requirements.txt)).
- **HTML without a zip:** you can still send `html_report_url` (public HTTPS) and/or `html_report_html` (single file) on the original JSON endpoint `POST /api/ingest/github-actions/run`.
- **Playwright helper:** [`examples/playwright-report-to-dashboard.mjs`](examples/playwright-report-to-dashboard.mjs) reads the JSON report for metrics and, if `playwright-report/` exists, runs `zip` and posts to `run-with-report` automatically. Set `PLAYWRIGHT_HTML_REPORT_DIR` if the folder is not `./playwright-report`, or `DASHBOARD_SKIP_HTML_ZIP=1` to send JSON only. Optional: `HTML_REPORT_URL`, `HTML_REPORT_FILE`.
- **Playwright JSON reports** nest tests under `suite.specs[].tests[]` (not only `suite.tests[]`). That script parses both shapes. If CI logs show `0 test case(s)` but tests ran, ensure `outputFile` for the JSON reporter points at the file you pass to the script.
- With `DATA_SOURCE=github`, the API **lists CI runs first** in the live feed (so old seeded rows do not stay at the top). To remove seeded/demo rows entirely, truncate tables in Postgres (see Render Postgres shell / SQL): `TRUNCATE test_case_results, test_runs RESTART IDENTITY CASCADE;`
- **HTML column still “—” after deploy?** Check `GET https://<your-api>/api/summary` → `latest_runs`: if `has_html_report_zip` is never `true`, your **test repository** workflow is still calling only `POST .../run` (JSON) without `report_zip`. Updating and pushing **this** dashboard repo does not change workflows in **SelfHealingPlaywrightFramework** (or any other repo). Add a step there that zips `playwright-report/` and POSTs to `.../run-with-report`.
- **CI step is green but still no HTML?** GitHub only checks the script’s exit code. If multipart uses the wrong field name (must be exactly `report_zip`, not `file` / `artifact` / `zip`), the API accepts the JSON metrics and returns **200** with **`has_html_report_zip": false`** and header **`X-Ingest-Report-Zip-Bytes: 0`**. Log the HTTP response body (`jq .has_html_report_zip`) or use `curl -v` and confirm `X-Ingest-Report-Zip-Bytes` is greater than zero. An empty `report_zip` file now returns **400** so the step fails visibly.
- **Log says “JSON-only run - no multipart”** (from your own publish script): the request never used `multipart/form-data` with a `report_zip` file part—only `POST .../run` with JSON, or a bug/branch in Node that skips `FormData`. Fix: use **`curl -F payload=@payload.json -F report_zip=@report.zip`** to `.../run-with-report`, or copy [`examples/github-actions-publish-step.yml`](examples/github-actions-publish-step.yml) into **SelfHealingPlaywrightFramework** and wire `payload.json` the same way you do today.
- **HTTP 422 on `run-with-report` with `curl -F payload=@payload.json`:** `curl` sends `payload` as a **file part** (with a filename). The API reads multipart manually (see `X-Ingest-Api-Revision: 3` on success). If you still get **422**, the JSON failed **schema** validation—save the body: `curl ... -o err.json -w '%{http_code}'` and open `err.json` (lists missing/wrong fields). Do **not** rely on `curl: (22)` alone; it hides the response body.
- **WebSocket “Reconnecting”** on Vercel: set `CORS_ORIGINS` to your exact Vercel URL (including `https://`). Redeploy the API after changing it.

### E) Rollback and recovery

- Frontend rollback: redeploy a previous successful Vercel deployment.
- Backend rollback: redeploy previous Render service revision.
- DB protection: never drop production DB; use Alembic migrations for schema changes.

## API examples

### Create a run

```bash
curl -X POST http://127.0.0.1:8000/api/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "suite_name": "Nightly Regression",
    "environment": "QA",
    "build_version": "v2.1.0",
    "test_cases": [
      {"name": "Login", "module": "Auth", "status": "RUNNING", "duration_ms": 0},
      {"name": "Checkout", "module": "Checkout", "status": "RUNNING", "duration_ms": 0}
    ]
  }'
```

### Update a test case

```bash
curl -X POST http://127.0.0.1:8000/api/cases/1/status \
  -H 'Content-Type: application/json' \
  -d '{"status":"FAILED","duration_ms":2400,"defect_id":"DEF-201"}'
```
