# Session 2 — Deploy to Render

> First, paste the MASTER_CONTEXT.md document, then paste this.

---

## What we're doing this session

Deploying the FastAPI server (built in Session 1) to Render.com free tier so it's accessible from the internet — and eventually from the iOS app.

Session 1 must be complete before this session. `GET /sections` and `POST /summary` should be working locally.

---

## Step 1 — Create `render.yaml`

Create a `render.yaml` at the repo root. This tells Render how to build and run the server:

```yaml
services:
  - type: web
    name: briefing-api
    env: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn server:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: OPENAI_ENABLED
        value: "true"
      - key: OPENAI_MODEL
        value: "gpt-4o-mini"
      - key: OPENAI_API_KEY
        sync: false  # set manually in Render dashboard, never commit this
```

---

## Step 2 — Create a `Procfile` (backup start method)

```
web: uvicorn server:app --host 0.0.0.0 --port $PORT
```

---

## Step 3 — Verify the app handles the PORT environment variable

Render sets a `$PORT` env var. Make sure `server.py` doesn't hardcode port 8000 anywhere. The `startCommand` in render.yaml handles this via uvicorn flags — confirm nothing in the code overrides it.

---

## Step 4 — Add a health check endpoint

Add to `server.py`:

```python
@app.get("/health")
async def health():
    return {"status": "ok", "cached_sections": _sections_cache_date}
```

Render uses this to confirm the service is running.

---

## Step 5 — Confirm requirements.txt is complete

Run a clean install in a fresh virtualenv to make sure all dependencies are captured:

```bash
python -m venv .venv_test
source .venv_test/bin/activate
pip install -r requirements.txt
uvicorn server:app &
curl http://localhost:8000/health
```

Fix any missing packages.

---

## Step 6 — Push to GitHub

Make sure all new files are committed:
- `server.py`
- `news_pipeline/pipeline_api.py`
- `render.yaml`
- `Procfile`
- updated `requirements.txt`

```bash
git add .
git commit -m "Add FastAPI server and Render deployment config"
git push
```

---

## Step 7 — Manual Render setup instructions (do this yourself)

Claude Code can't log into Render for you. Here's exactly what to do:

1. Go to render.com, sign up with GitHub
2. Click "New +" → "Web Service"
3. Connect your GitHub repo
4. Render will detect `render.yaml` automatically
5. In the dashboard, go to Environment → add `OPENAI_API_KEY` with your actual key
6. Click "Deploy"
7. Wait ~3 minutes for first deploy
8. Hit `https://your-app-name.onrender.com/health` to confirm it's live
9. Hit `https://your-app-name.onrender.com/sections` — this will take 30–60 seconds on first run as the pipeline executes

---

## Step 8 — Note your Render URL

Once deployed, save your Render URL. It will look like:
```
https://briefing-api-xxxx.onrender.com
```

You'll hardcode this into the iOS app in Session 3.

---

## Done when:
- [ ] `render.yaml` and `Procfile` exist in the repo
- [ ] `/health` endpoint exists and returns JSON
- [ ] All files committed and pushed to GitHub
- [ ] (Manual) Render service is live and `/sections` returns valid JSON from the public URL
