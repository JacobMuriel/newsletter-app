# Session 6 — NBA Social Buzz via Grok API

> First, paste the MASTER_CONTEXT.md document, then paste this.

---

## What we're doing this session

Adding a social buzz layer to the NBA section. When the pipeline runs each morning, it calls the Grok API (xAI) to synthesize what people on X/Twitter were saying about last night's NBA games — specifically the Rockets and Bulls, plus the 2–3 biggest league-wide storylines. The result is cached alongside the rest of `/sections` and surfaced as a new card in the NBA section of the iOS app.

Sessions 1 and 2 must be complete. `GET /sections` should already be working.

**Do NOT touch:** `newsletter.py`, `send_email.py`, `main.py` CLI flow

---

## Background: why Grok instead of the Twitter API

The Twitter/X API requires a paid plan (~$100/month minimum) for any meaningful search access. The Grok API (xAI) has a free tier and Grok has real-time X post access baked into its context — so we get synthesized social discourse without needing direct Twitter API access. The tradeoff is we get Grok's synthesis of X discourse, not raw tweets. That's fine for a morning briefing.

---

## Step 1 — Create `news_pipeline/nba_social.py`

Create this new file:

```python
# news_pipeline/nba_social.py

import json
import logging
import os
import re
from datetime import date, timedelta

from openai import OpenAI  # xAI uses the same SDK interface as OpenAI

logger = logging.getLogger(__name__)


def get_nba_social_buzz() -> dict | None:
    """
    Calls the Grok API to synthesize X/Twitter discourse about last night's NBA games.

    Checks specifically for Rockets and Bulls games, plus league-wide storylines.
    Returns structured JSON or None if the call fails.

    Requires env var: GROK_API_KEY
    """
    api_key = os.environ.get("GROK_API_KEY")
    if not api_key:
        logger.warning("[nba_social] GROK_API_KEY not set — skipping social buzz")
        return None

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
    )

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Explicit date strings — Grok needs these to anchor to the right day.
    # Do NOT use relative terms like "yesterday" alone; Grok can misinterpret
    # the reference frame and pull stale data or hallucinate game results
    # from training data instead of live X posts.
    today_str = today.strftime("%B %-d, %Y")
    yesterday_str = yesterday.strftime("%B %-d, %Y")

    prompt = f"""
Today's date is {today_str}. Search X (Twitter) specifically for posts made on {yesterday_str}.

Do the following:

1. Check if the Houston Rockets played an NBA game on {yesterday_str}.
   - If yes: summarize what fans and analysts on X are saying about the game.
     Include the final score, 2-3 reactions (paraphrased, not verbatim quotes),
     and the overall sentiment (positive / negative / mixed).
   - If no game was played: set rockets_buzz to null.

2. Check if the Chicago Bulls played an NBA game on {yesterday_str}.
   - Same format as above.
   - If no game was played: set bulls_buzz to null.

3. Summarize the 2-3 most-discussed NBA storylines on X from {yesterday_str}
   that are NOT about the Rockets or Bulls.
   These could be a big trade, standout performance, injury news, controversy,
   playoff standings movement, or anything else generating significant discussion.

Important: only report on games and events that actually occurred on {yesterday_str}.
Do not pull in results from other dates. If you are uncertain whether a game occurred,
set that team's field to null rather than guessing.

Return ONLY valid JSON. No markdown, no code fences, no explanation — raw JSON only.

{{
  "rockets_buzz": {{
    "played": true,
    "opponent": "Team Name",
    "score": "112-108",
    "result": "win",
    "sentiment": "positive",
    "reactions": [
      "Paraphrased fan or analyst reaction 1",
      "Paraphrased fan or analyst reaction 2",
      "Paraphrased hot take or notable comment"
    ]
  }},
  "bulls_buzz": {{
    "played": true,
    "opponent": "Team Name",
    "score": "98-104",
    "result": "loss",
    "sentiment": "negative",
    "reactions": [
      "Paraphrased reaction 1",
      "Paraphrased reaction 2",
      "Paraphrased reaction 3"
    ]
  }},
  "league_buzz": [
    {{
      "topic": "Short topic label",
      "summary": "2-3 sentence summary of what people are saying on X about this storyline"
    }},
    {{
      "topic": "Short topic label",
      "summary": "2-3 sentence summary"
    }}
  ],
  "data_date": "{yesterday_str}"
}}

If rockets_buzz or bulls_buzz is null because no game was played, use JSON null (not the string "null").
"""

    try:
        response = client.chat.completions.create(
            model="grok-3",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,  # low temp = more factual, less hallucination risk
        )

        raw = response.choices[0].message.content.strip()

        # Strip any accidental markdown fences Grok might add despite instructions
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        result = json.loads(raw)
        logger.info(f"[nba_social] Grok buzz fetched for {yesterday_str}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"[nba_social] Failed to parse Grok response as JSON: {e}")
        logger.error(f"[nba_social] Raw response was: {raw[:500]}")
        return None

    except Exception as e:
        logger.error(f"[nba_social] Grok API call failed: {e}")
        return None
```

---

## Step 2 — Wire into `news_pipeline/pipeline_api.py`

In `get_ranked_stories()`, after the NBA section stories are assembled, add the Grok call. It should only run if `GROK_ENABLED=true` is set — this keeps dry runs fast and free.

Find the section where NBA stories are finalized and add:

```python
from news_pipeline.nba_social import get_nba_social_buzz

# Inside get_ranked_stories(), after sections dict is built:

if os.environ.get("GROK_ENABLED", "false").lower() == "true":
    logger.info("[pipeline] Fetching NBA social buzz from Grok...")
    buzz = get_nba_social_buzz()
    if buzz is not None:
        # Attach to the nba section as a sibling key alongside stories
        sections_output["nba_social_buzz"] = buzz
    else:
        logger.warning("[pipeline] NBA social buzz unavailable — Grok call returned None")
        sections_output["nba_social_buzz"] = None
else:
    sections_output["nba_social_buzz"] = None
```

Note: `nba_social_buzz` is a top-level key in the sections response, not nested inside the `nba` stories list. This keeps the story list structure clean.

---

## Step 3 — Update the `/sections` response shape in `server.py`

The response from `GET /sections` will now include `nba_social_buzz` at the top level alongside `sections`:

```json
{
  "generated_at": "2025-03-18T09:00:00Z",
  "sections": {
    "top": [...],
    "markets": [...],
    "ai": [...],
    "finance_market_structure": [...],
    "nba": [...]
  },
  "nba_social_buzz": {
    "rockets_buzz": {
      "played": true,
      "opponent": "Lakers",
      "score": "112-108",
      "result": "win",
      "sentiment": "positive",
      "reactions": [
        "Fans are calling it Sengun's best two-way game of the season",
        "Analysts note the Rockets held LA under 42% from the field",
        "Several accounts pointing to this win as a statement in the West race"
      ]
    },
    "bulls_buzz": null,
    "league_buzz": [
      {
        "topic": "Luka's triple-double streak",
        "summary": "Doncic recorded his 8th straight triple-double, with X users debating whether this run rivals historic streaks. Several analysts called it the quietest dominance in the league right now."
      },
      {
        "topic": "Warriors playoff bubble watch",
        "summary": "Golden State's loss to Memphis has X in full panic mode about the play-in. Fan accounts are calling for lineup changes; beat reporters are more measured."
      }
    ],
    "data_date": "March 17, 2025"
  }
}
```

No schema changes needed to the existing `sections` dict — this is purely additive.

---

## Step 4 — Add environment variables

Add to `render.yaml`:

```yaml
      - key: GROK_ENABLED
        value: "true"
      - key: GROK_API_KEY
        sync: false  # set manually in Render dashboard, never commit this
```

Add to `.env.example`:

```
GROK_ENABLED=false
GROK_API_KEY=
```

Note: default is `false` in `.env.example` so dry runs and local dev don't require a Grok key.

---

## Step 5 — Update the iOS app models

### Add to `SectionsResponse` (or wherever you decode `/sections`):

```swift
struct SectionsResponse: Codable {
    let generatedAt: String
    let sections: [String: [Story]]
    let nbaSocialBuzz: NBASocialBuzz?   // nullable — may be nil if Grok disabled

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case sections
        case nbaSocialBuzz = "nba_social_buzz"
    }
}
```

### New models in `Models/NBASocialBuzz.swift`:

```swift
struct NBASocialBuzz: Codable {
    let rocketsBuzz: TeamBuzz?
    let bullsBuzz: TeamBuzz?
    let leagueBuzz: [LeagueBuzzItem]
    let dataDate: String

    enum CodingKeys: String, CodingKey {
        case rocketsBuzz = "rockets_buzz"
        case bullsBuzz = "bulls_buzz"
        case leagueBuzz = "league_buzz"
        case dataDate = "data_date"
    }
}

struct TeamBuzz: Codable {
    let played: Bool
    let opponent: String?
    let score: String?
    let result: String?       // "win" or "loss"
    let sentiment: String?    // "positive", "negative", "mixed"
    let reactions: [String]
}

struct LeagueBuzzItem: Codable {
    let topic: String
    let summary: String
}
```

---

## Step 6 — Add NBA Social Buzz card to the iOS NBA section

In the NBA section view, render a `SocialBuzzCard` above the story list if `nbaSocialBuzz` is non-nil.

### `SocialBuzzCard.swift`

```swift
struct SocialBuzzCard: View {
    let buzz: NBASocialBuzz

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {

            // Header
            Text("X / SOCIAL · \(buzz.dataDate.uppercased())")
                .font(Theme.sans(9, weight: .medium))
                .foregroundColor(Theme.muted)
                .tracking(1.2)

            Divider().background(Theme.rule)

            // Team buzz rows
            if let rockets = buzz.rocketsBuzz, rockets.played {
                TeamBuzzRow(teamName: "ROCKETS", buzz: rockets)
                Divider().background(Theme.rule)
            }

            if let bulls = buzz.bullsBuzz, bulls.played {
                TeamBuzzRow(teamName: "BULLS", buzz: bulls)
                Divider().background(Theme.rule)
            }

            // League buzz items
            if !buzz.leagueBuzz.isEmpty {
                Text("AROUND THE LEAGUE")
                    .font(Theme.sans(9, weight: .medium))
                    .foregroundColor(Theme.muted)
                    .tracking(1.2)

                ForEach(buzz.leagueBuzz, id: \.topic) { item in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(item.topic)
                            .font(Theme.sans(12, weight: .medium))
                            .foregroundColor(Theme.ink)
                        Text(item.summary)
                            .font(Theme.sans(11, weight: .light))
                            .foregroundColor(Color(hex: "#3a3530"))
                            .lineSpacing(3)
                    }
                }
            }
        }
        .padding(16)
        .background(Color(hex: "#ede9e0"))
        .cornerRadius(4)
        .padding(.horizontal, 20)
        .padding(.top, 12)
    }
}

struct TeamBuzzRow: View {
    let teamName: String
    let buzz: TeamBuzz

    var sentimentColor: Color {
        switch buzz.sentiment {
        case "positive": return Color(hex: "#2a7a2a")
        case "negative": return Theme.accentRed
        default: return Theme.muted
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(teamName)
                    .font(Theme.sans(10, weight: .medium))
                    .foregroundColor(Theme.ink)
                    .tracking(1.0)
                Spacer()
                if let score = buzz.score, let opponent = buzz.opponent {
                    Text("vs \(opponent) · \(score)")
                        .font(Theme.sans(10, weight: .light))
                        .foregroundColor(Theme.muted)
                }
                if let result = buzz.result {
                    Text(result.uppercased())
                        .font(Theme.sans(9, weight: .medium))
                        .foregroundColor(sentimentColor)
                        .tracking(0.8)
                        .padding(.leading, 6)
                }
            }
            ForEach(buzz.reactions, id: \.self) { reaction in
                HStack(alignment: .top, spacing: 6) {
                    Text("–")
                        .font(Theme.sans(11, weight: .light))
                        .foregroundColor(Theme.muted)
                    Text(reaction)
                        .font(Theme.sans(11, weight: .light))
                        .foregroundColor(Color(hex: "#3a3530"))
                        .lineSpacing(3)
                }
            }
        }
    }
}
```

---

## Step 7 — Test locally

```bash
# Without Grok (confirm nothing breaks)
GROK_ENABLED=false OPENAI_ENABLED=false uvicorn server:app --reload
curl http://localhost:8000/sections | python -m json.tool | grep nba_social_buzz
# Should return: "nba_social_buzz": null

# With Grok
GROK_ENABLED=true GROK_API_KEY=xai-... OPENAI_ENABLED=false uvicorn server:app --reload
curl http://localhost:8000/sections | python -m json.tool
# nba_social_buzz should be populated with real data
```

Check the server logs for `[nba_social]` prefixed lines — these confirm whether the Grok call succeeded or failed and why.

---

## Done when:
- [ ] `news_pipeline/nba_social.py` exists and calls Grok with explicit date anchoring
- [ ] `GROK_ENABLED=false` runs the full pipeline with no errors and `nba_social_buzz: null`
- [ ] `GROK_ENABLED=true` with a real key returns populated buzz for yesterday's games
- [ ] Rockets and Bulls correctly return `null` on days they didn't play (not hallucinated data)
- [ ] Server logs show `[nba_social]` status on every pipeline run — no silent failures
- [ ] `render.yaml` and `.env.example` updated with new env vars
- [ ] iOS models decode `nba_social_buzz` without crashing when it's null
- [ ] `SocialBuzzCard` renders correctly in the NBA section when data is present
- [ ] App handles `nba_social_buzz: null` gracefully (card simply doesn't appear)
