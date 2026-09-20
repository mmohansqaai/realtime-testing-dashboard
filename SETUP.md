# Setup — latest GitHub repos and deployed URLs

Canonical GitHub org: **[mmohansqaai](https://github.com/mmohansqaai)**.  
Use these remotes (not stale `mmohan-bayone` clones).

| System | GitHub (latest) | Latest branch | Deployed |
|---|---|---|---|
| **Retail website** | https://github.com/mmohansqaai/RetailWebsite | `main` | https://retail-website-fawn.vercel.app (BayOne Retail demo) |
| **Self-healing Playwright** | https://github.com/mmohansqaai/SelfHealingPlaywrightFramework | `main` | GitHub Actions: [Playwright Tests](https://github.com/mmohansqaai/SelfHealingPlaywrightFramework/actions/workflows/playwright.yml) |
| **Testing + Triage dashboard** | https://github.com/mmohansqaai/realtime-testing-dashboard | `unified-testing-triage-dashboard` | UI: https://realtime-unified-dashboard.vercel.app · API: https://realtime-unified-dashboard-api.onrender.com |
| **CI Failure Triage engine** | https://github.com/mmohansqaai/ci-failure-triage | `phase-1-github-connector` | No public web deploy (CLI / GitHub repo only). Default branch on GitHub is still `main`. |

## How they connect

```text
RetailWebsite (Vercel)
        ▲
        │ BASE_URL
SelfHealingPlaywrightFramework (GitHub Actions)
        │ ingest + HTML report
        ▼
realtime-testing-dashboard
  Testing tab  → KPIs, Run pipeline, HTML report
  Triage tab   → classification for a GitHub run ID
        │
        └── optional later: ci-failure-triage POST /api/triage/results
```

Playwright CI currently uses:

- `BASE_URL=https://retail-website-fawn.vercel.app`
- `DASHBOARD_URL=https://realtime-testing-dashboard-api.onrender.com` (legacy ingest host in `playwright.yml`)

Unified dashboard (shared with management):

- Testing: https://realtime-unified-dashboard.vercel.app
- Triage: https://realtime-unified-dashboard.vercel.app/triage
- API health: https://realtime-unified-dashboard-api.onrender.com/api/health
- API summary: https://realtime-unified-dashboard-api.onrender.com/api/summary

## Clone

```bash
git clone https://github.com/mmohansqaai/RetailWebsite.git
git clone https://github.com/mmohansqaai/SelfHealingPlaywrightFramework.git
git clone https://github.com/mmohansqaai/realtime-testing-dashboard.git
git clone https://github.com/mmohansqaai/ci-failure-triage.git

cd realtime-testing-dashboard && git checkout unified-testing-triage-dashboard
cd ../ci-failure-triage && git checkout phase-1-github-connector
```

## Dashboard env (Render API)

Set on **realtime-unified-dashboard-api**:

- `DATABASE_URL` — Neon Postgres (project must be within quota)
- `CORS_ORIGINS` — `https://realtime-unified-dashboard.vercel.app`
- `DATA_SOURCE=github`
- `GITHUB_ACTIONS_INGEST_TOKEN`
- `GITHUB_CI_TOKEN` — classic PAT, scopes `repo` + `workflow` (dedicated token; do not share with the old API if you hit GitHub rate limits)
- `GITHUB_CI_REPO=mmohansqaai/SelfHealingPlaywrightFramework`

Vercel project **realtime-unified-dashboard**:

- Production branch: `unified-testing-triage-dashboard`
- `VITE_API_BASE_URL=https://realtime-unified-dashboard-api.onrender.com`

## Legacy dashboard (still exists)

Do not use these for the unified BayOne demo:

- API: https://realtime-testing-dashboard.onrender.com
- Ingest host still referenced by Playwright: https://realtime-testing-dashboard-api.onrender.com
- GitHub default branch of the dashboard repo: `main` (older than `unified-testing-triage-dashboard`)
