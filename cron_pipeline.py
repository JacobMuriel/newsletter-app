# cron_pipeline.py

import argparse
import logging
import os
import sys
import time
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _run_primary():
    """
    Full daily pipeline: NBA stats → NBA social buzz → all sections + AI/finance/markets buzz.
    Writes all Redis keys including briefing:cache_date.
    """
    from news_pipeline.pipeline_api import get_ranked_stories, get_story_summary
    from news_pipeline.redis_cache import save_sections_cache, save_summaries_cache

    # ── Step 1: NBA Stats (runs first so game data can anchor the Grok search) ──
    nba_stats = None
    nba_stats_enabled = os.environ.get("NBA_STATS_ENABLED", "true").lower() == "true"
    if nba_stats_enabled:
        logger.info("[cron] Fetching NBA game stats from ESPN (step 1 — needed for social buzz)...")
        from news_pipeline.nba_stats import get_nba_game_stats
        from news_pipeline.redis_cache import save_nba_stats_cache
        nba_stats = get_nba_game_stats()
        if nba_stats is not None:
            save_nba_stats_cache(nba_stats)
            logger.info(
                f"[cron] NBA stats written to Redis "
                f"({len(nba_stats.get('all_games', []))} games, "
                f"Rockets played: {nba_stats.get('rockets_game', {}).get('played')}, "
                f"Bulls played: {nba_stats.get('bulls_game', {}).get('played')})"
            )
        else:
            logger.warning("[cron] NBA stats unavailable — social buzz will have no game context")
    else:
        logger.info("[cron] NBA_STATS_ENABLED is false — skipping NBA stats")

    # ── Step 2: NBA Social Buzz (uses confirmed game data from step 1) ──
    grok_enabled = os.environ.get("GROK_ENABLED", "false").lower() == "true"
    nba_buzz = None
    if grok_enabled:
        logger.info("[cron] Fetching NBA social buzz from Grok (with ESPN game context)...")
        from news_pipeline.nba_social import get_nba_social_buzz
        rockets_game = nba_stats.get("rockets_game") if nba_stats else None
        bulls_game   = nba_stats.get("bulls_game")   if nba_stats else None
        nba_buzz = get_nba_social_buzz(rockets_game=rockets_game, bulls_game=bulls_game)
        if nba_buzz is None:
            logger.warning("[cron] NBA social buzz unavailable — Grok returned None")
        else:
            logger.info("[cron] NBA social buzz fetched successfully")
    else:
        logger.info("[cron] GROK_ENABLED is false — skipping NBA social buzz")

    # ── Step 3: Main pipeline (stories + AI/finance/markets social buzz) ──
    logger.info("[cron] Running main pipeline...")
    result = get_ranked_stories()

    story_count = sum(len(v) for v in result.get("sections", {}).values())
    logger.info(f"[cron] Pipeline complete — {story_count} stories across {len(result.get('sections', {}))} sections")

    # Inject nba_social_buzz (pipeline_api returns None for it; we fill it here)
    result["nba_social_buzz"] = nba_buzz

    logger.info("[cron] Writing sections to Redis...")
    save_sections_cache(result)

    logger.info("[cron] Pre-generating summaries...")
    summaries: dict = {}
    for section_stories in result.get("sections", {}).values():
        for story_data in section_stories:
            story_id = story_data["id"]
            try:
                summaries[story_id] = get_story_summary(story_id, story_data)
            except Exception as e:
                logger.warning(f"[cron] Could not summarize {story_id}: {e}")
    save_summaries_cache(summaries)
    logger.info(f"[cron] Saved {len(summaries)} summaries to Redis")


def _run_top_only():
    """
    Secondary run: refresh Top Stories only (2pm / 6pm CT).
    - Skips NBA stats, NBA social buzz, and all Grok calls.
    - Caps top section at 10 stories (vs. 5 in the primary run).
    - Partial Redis write: patches briefing:sections.top and merges summaries.
    - Does NOT update briefing:cache_date (preserves morning timestamp).
    """
    # Disable all Grok/social calls — those are morning-only.
    # These override whatever the workflow env block sets.
    os.environ["GROK_ENABLED"] = "false"
    os.environ["AI_SOCIAL_ENABLED"] = "false"
    os.environ["FINANCE_SOCIAL_ENABLED"] = "false"
    os.environ["NBA_STATS_ENABLED"] = "false"
    # Expand top section limit so we get more fresh stories in the afternoon.
    os.environ["TOP_SECTION_LIMIT"] = "10"

    from news_pipeline.pipeline_api import get_ranked_stories, get_story_summary
    from news_pipeline.redis_cache import write_top_section_only

    logger.info("[cron:top-only] Running top-section pipeline (no Grok, no NBA)...")
    result = get_ranked_stories()

    top_stories = result.get("sections", {}).get("top", [])
    logger.info(f"[cron:top-only] Top section has {len(top_stories)} stories")

    logger.info("[cron:top-only] Pre-generating summaries for top stories...")
    summaries: dict = {}
    for story_data in top_stories:
        story_id = story_data["id"]
        try:
            summaries[story_id] = get_story_summary(story_id, story_data)
        except Exception as e:
            logger.warning(f"[cron:top-only] Could not summarize {story_id}: {e}")

    write_top_section_only(top_stories, summaries)
    logger.info(f"[cron:top-only] Partial Redis write complete ({len(summaries)} summaries merged)")


def main():
    parser = argparse.ArgumentParser(description="Briefing daily pipeline")
    parser.add_argument(
        "--top-only",
        action="store_true",
        help="Refresh top stories only; skip Grok, NBA, and full Redis write",
    )
    # --dry-run: recognized flag for CI/test invocations. Actual dry-run behavior
    # is controlled by env vars (OPENAI_ENABLED=false, UPSTASH_REDIS_REST_URL=disabled, etc.)
    parser.add_argument("--dry-run", action="store_true", help="No-op flag; dry-run is controlled by env vars")
    args = parser.parse_args()

    mode = "top-only" if args.top_only else "primary"
    logger.info("=" * 60)
    logger.info(f"[cron] Pipeline run starting at {datetime.utcnow().isoformat()}Z (mode: {mode})")
    logger.info("=" * 60)

    t0 = time.time()

    try:
        if args.top_only:
            _run_top_only()
        else:
            _run_primary()

        elapsed = time.time() - t0
        logger.info(f"[cron] Done. Total time: {elapsed:.1f}s")
        logger.info("=" * 60)
        sys.exit(0)

    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"[cron] Pipeline failed after {elapsed:.1f}s: {e}", exc_info=True)
        logger.info("=" * 60)
        sys.exit(1)  # non-zero exit so GitHub Actions marks the run as failed


if __name__ == "__main__":
    main()
