# Session 1 — Restructure Pipeline + Build FastAPI Server

> First, paste the MASTER_CONTEXT.md document, then paste this.

---

## What we're doing this session

Wrapping the existing Python pipeline in a FastAPI server. By the end of this session we should be able to run the server locally and hit both endpoints from a browser or curl.

**Do NOT touch:** `newsletter.py`, `send_email.py`, the existing CLI flow via `main.py`

---

## Step 1 — Audit the pipeline for callability

Look at `main.py` and the `news_pipeline/` modules. The pipeline currently runs as a script (top to bottom). We need to extract the core logic into callable functions without breaking `python main.py`.

Specifically:
- Identify where stories are fetched, clustered, categorized, and ranked
- Identify where summaries are generated (the OpenAI call in `summarize.py`)
- Note what state/config is loaded at startup vs per-story

---

## Step 2 — Create `news_pipeline/pipeline_api.py`

Create a new file `news_pipeline/pipeline_api.py` with two clean functions:

```python
def get_ranked_stories() -> dict:
    """
    Runs the full pipeline (fetch → cluster → categorize → rank).
    Returns stories grouped by section, with metadata per story.
    Does NOT generate summaries.
    Each story dict must include: id, headline, source, url, 
    published_at, section, bias_flags, has_left_right
    Story ID should be a stable hash of the URL.
    """

def get_story_summary(story_id: str, story_data: dict) -> dict:
    """
    Generates a summary for a single story using the existing
    summarize.py logic. Returns summary text, and left_take/right_take
    if the story is in the 'top' section.
    """
```

These functions should reuse the existing pipeline modules — don't rewrite the logic, just wrap it.

---

## Step 3 — Create `server.py`

Create `server.py` at the repo root:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# ... imports

app = FastAPI()

# Allow requests from the iOS app (any origin is fine for personal use)
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)

# In-memory cache
_sections_cache = None
_sections_cache_date = None
_summary_cache = {}  # story_id -> summary dict

@app.get("/sections")
async def sections():
    # Return cached result if same calendar day
    # Otherwise re-run pipeline and cache
    ...

@app.post("/summary")
async def summary(body: SummaryRequest):
    # Check cache first
    # If not cached, call get_story_summary() and cache result
    ...
```

Add a `SummaryRequest` Pydantic model:
```python
class SummaryRequest(BaseModel):
    story_id: str
```

---

## Step 4 — Add dependencies

Add to `requirements.txt`:
```
fastapi
uvicorn[standard]
pydantic
```

---

## Step 5 — Test locally

Run:
```bash
OPENAI_ENABLED=false uvicorn server:app --reload
```

Then verify:
```bash
curl http://localhost:8000/sections
```

Should return JSON with sections and story lists (no summaries). Fix any errors until this works cleanly.

Also test with `OPENAI_ENABLED=true` and a real `OPENAI_API_KEY` to confirm summary generation works:
```bash
curl -X POST http://localhost:8000/summary \
  -H "Content-Type: application/json" \
  -d '{"story_id": "<id from sections response>"}'
```

---

## Done when:
- [ ] `python main.py` still works exactly as before
- [ ] `uvicorn server:app` starts without errors
- [ ] `GET /sections` returns valid JSON grouped by section
- [ ] `POST /summary` returns a summary for a valid story_id
- [ ] Both endpoints log clearly to the console (no silent failures)
