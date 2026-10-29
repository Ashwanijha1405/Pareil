# Pareil

Same taste, smaller bill. Pareil reads where you spend on food, then uses Qloo's taste graph to find
places that people with your taste love, one price tier cheaper and rated as well or better.
Built for the Qloo Agentic Hackathon 2026.

## Deployment

```
 browser ──► Vercel (static/)                         free, always on
               ├─ index.html, app.js, styles.css
               └─ demo/nyc.json, demo/blr.json        recorded demo runs, played in the browser
   │
   │  Run live / CSV upload only
   ▼
 Render (FastAPI, app/web.py)                         free, sleeps after 15 min idle
   ├─ GET  /healthz                 {"ok": true}, no Qloo or LLM calls
   ├─ POST /api/runs                start a live run (per-IP limit + max 3 at once)
   ├─ GET  /api/runs/{id}/events    live agent trace (SSE)
   └─ GET  /api/runs/{id}/report
        └──► Qloo API, Gemini (OpenAI-compatible endpoint)
```

**Why it's split.** Render's free tier sleeps when idle and takes about a minute to wake. If the
demos needed the backend, a judge's first click would hit that minute. Instead the demos are static
files on Vercel, so they open instantly whether or not the backend is up. Only "Run live" and CSV
uploads call Render. The page pings `/healthz` on load to start the wake-up early, and a live run
waits behind a "Waking the server" screen for up to 90 seconds.

`static/demo/` holds trimmed output of one recorded run per city (only the fields the page shows:
names, tiers, ratings, shared tags, explainability %, savings and trace step summaries). It exists
so the demo works while the free backend sleeps. Qloo photos in it are URLs, hot-linked from
`images.qloo.com`; no image files are stored. If the engine changes, record fresh demos before
deploying:

```
python scripts/export_demos.py   # runs both demos live (Qloo + LLM calls), writes static/demo/*.json
```

### Backend on Render

`render.yaml` is a Render Blueprint for one free web service:
`pip install -r requirements.txt`, then `uvicorn app.web:app --host 0.0.0.0 --port $PORT`,
health check `/healthz`. Set these in the Render dashboard (never commit values):

| Variable | Value |
|---|---|
| `QLOO_API_KEY` | your Qloo hackathon key |
| `QLOO_BASE_URL` | `https://hackathon.api.qloo.com` |
| `LLM_API_KEY` | your Gemini key |
| `LLM_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `LLM_MODEL` | `gemini-3.5-flash-lite` |
| `ALLOWED_ORIGINS` | your Vercel production URL, e.g. `https://pareil.vercel.app` (comma-separated, no trailing slash) |

CORS allows only `ALLOWED_ORIGINS` plus `http://localhost` / `http://127.0.0.1` on any port.

### Frontend on Vercel

Import the repo with no build step; `vercel.json` serves `static/` and sets the CSP and cache
headers (`.vercelignore` keeps the Python code out of the upload). The API URL
(`https://pareil-api.onrender.com`) lives in `static/config.js` and in `connect-src` in
`vercel.json`; change both if the Render service moves.

### Run locally

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      # macOS/Linux: .venv/bin/pip
copy .env.example .env                              # then fill in the keys

# terminal 1: API on :8000
.venv\Scripts\python -m uvicorn app.web:app --port 8000

# terminal 2: frontend on :5500 (a different origin, like production)
.venv\Scripts\python -m http.server 5500 -d static
```

Open http://localhost:5500. `static/config.js` points localhost at the API on port 8000. The API
also serves the frontend itself at http://localhost:8000 for a one-terminal setup.

Tests: `.venv\Scripts\python -m pytest`.
