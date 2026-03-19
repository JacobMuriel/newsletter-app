# cron_pipeline.py

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


def main():
    logger.info("=" * 60)
    logger.info(f"[cron] Pipeline run starting at {datetime.utcnow().isoformat()}Z")
    logger.info("=" * 60)

    t0 = time.time()

    try:
        from news_pipeline.pipeline_api import get_ranked_stories, get_story_summary
        from news_pipeline.redis_cache import save_sections_cache, save_summaries_cache

        logger.info("[cron] Running full pipeline...")
        result = get_ranked_stories()

        story_count = sum(len(v) for v in result.get("sections", {}).values())
        logger.info(f"[cron] Pipeline complete — {story_count} stories across {len(result.get('sections', {}))} sections")

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

        # NBA Stats (BallDontLie API — gated by NBA_STATS_ENABLED, default true)
        nba_stats_enabled = os.environ.get("NBA_STATS_ENABLED", "true").lower() == "true"
        if nba_stats_enabled:
            logger.info("[cron] Fetching NBA game stats from BallDontLie...")
            from news_pipeline.nba_stats import get_nba_game_stats
            from news_pipeline.redis_cache import save_nba_stats_cache
            nba_stats = get_nba_game_stats()
            if nba_stats is not None:
                save_nba_stats_cache(nba_stats)
                logger.info(
                    f"[cron] NBA stats written to Redis "
                    f"({len(nba_stats.get('all_games', []))} games, "
                    f"Rockets played: {nba_stats.get('rockets_game', {}).get('played')})"
                )
            else:
                logger.warning("[cron] NBA stats unavailable — get_nba_game_stats() returned None (see above for details)")
        else:
            logger.info("[cron] NBA_STATS_ENABLED is false — skipping NBA stats")

        elapsed = time.time() - t0
        logger.info(f"[cron] Done. Total time: {elapsed:.1f}s")
        logger.info("=" * 60)
        sys.exit(0)

    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"[cron] Pipeline failed after {elapsed:.1f}s: {e}", exc_info=True)
        logger.info("=" * 60)
        sys.exit(1)  # non-zero exit so Render marks the cron run as failed


if __name__ == "__main__":
    main()
