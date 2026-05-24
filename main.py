"""
English Native Expression Database — Pipeline Orchestrator
============================================================
Main entry point that orchestrates the 3-agent pipeline:
  Agent 1: Data Scraper
  Agent 2: LLM Processor
  Agent 3: Database Manager
"""

import os
import sys
import json
import datetime
import argparse

import config
from utils.dedup import load_index, save_index, get_total_count, add_expression
from utils.logger import setup_logger
from agents.scraper import scrape_all_sources
from agents.processor import process_and_extract
from agents.db_manager import save_expressions


def update_run_log(log_file: str, run_info: dict) -> None:
    """Append a run record to the JSON run log file."""
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            try:
                log_data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                log_data = []
    else:
        log_data = []

    log_data.append(run_info)

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)


def main() -> None:
    """Run the full expression-extraction pipeline."""

    # ── Argument parsing ──────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="English Native Expression DB — daily pipeline"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the pipeline without saving to the database",
    )
    args = parser.parse_args()

    # ── Setup ─────────────────────────────────────────────────────────
    os.makedirs(config.DATA_DIR, exist_ok=True)
    logger = setup_logger()
    start_time = datetime.datetime.now()

    logger.info("=" * 60)
    logger.info("🚀 English Expression DB Pipeline — START")
    logger.info(f"   Timestamp : {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"   Dry-run   : {args.dry_run}")
    logger.info("=" * 60)

    try:
        # ── Step 0: Check stop condition ──────────────────────────────
        index_data = load_index(config.INDEX_FILE)
        current_count = get_total_count(index_data)

        if current_count >= config.MAX_EXPRESSIONS:
            logger.info(
                f"[PIPELINE COMPLETE] {current_count} expressions reached. "
                f"Target: {config.MAX_EXPRESSIONS}. Shutting down."
            )
            sys.exit(0)

        logger.info(
            f"📊 Progress: {current_count}/{config.MAX_EXPRESSIONS} "
            f"expressions collected so far"
        )

        # ── Step 1: Scrape (Agent 1) ─────────────────────────────────
        logger.info("-" * 50)
        logger.info("🔍 Agent 1: Data Scraper starting...")

        used_episodes = index_data.get("used_episodes", [])
        raw_texts, new_episode_urls = scrape_all_sources(
            config.SOURCES, used_episodes
        )

        sources_scraped = len(config.SOURCES)
        logger.info(
            f"   Scraped {len(raw_texts)} text chunks "
            f"from {sources_scraped} sources"
        )

        if not raw_texts:
            logger.error("❌ No texts scraped. Exiting pipeline.")
            sys.exit(1)

        # ── Step 2: Process (Agent 2) ─────────────────────────────────
        logger.info("-" * 50)
        logger.info("🤖 Agent 2: LLM Processor starting...")

        expressions = process_and_extract(
            raw_texts, index_data, config.DAILY_TARGET
        )

        logger.info(f"   Extracted {len(expressions)} unique expressions")

        if not expressions:
            logger.error("❌ No expressions extracted. Exiting pipeline.")
            sys.exit(1)

        # ── Step 3: Save (Agent 3) ────────────────────────────────────
        logger.info("-" * 50)

        if args.dry_run:
            logger.info(
                f"[DRY RUN] Skipping DB save. "
                f"Would save {len(expressions)} expressions."
            )
            logger.info("Preview (first 5):")
            for i, expr in enumerate(expressions[:5], 1):
                logger.info(f"  {i}. {expr}")
            rows_saved = 0
        else:
            logger.info("💾 Agent 3: Database Manager starting...")
            rows_saved = save_expressions(expressions, index_data)
            logger.info(f"   Saved {rows_saved} expressions to database")

        # ── Step 4: Update index ──────────────────────────────────────
        logger.info("-" * 50)
        logger.info("📝 Updating index...")

        for expr in expressions:
            add_expression(expr["expression"], index_data)

        if new_episode_urls:
            existing_episodes = index_data.get("used_episodes", [])
            existing_episodes.extend(new_episode_urls)
            index_data["used_episodes"] = existing_episodes

        index_data["last_updated"] = datetime.date.today().isoformat()
        save_index(index_data, config.INDEX_FILE)

        updated_count = get_total_count(index_data)
        logger.info(
            f"   Index updated. Total: "
            f"{updated_count}/{config.MAX_EXPRESSIONS}"
        )

        # ── Step 5: Update run log ────────────────────────────────────
        run_info = {
            "date": datetime.date.today().isoformat(),
            "expressions_added": len(expressions),
            "total_count": updated_count,
            "sources_scraped": sources_scraped,
            "status": "dry_run" if args.dry_run else "success",
        }
        update_run_log(config.RUN_LOG_FILE, run_info)

    except Exception:
        logger.exception("🔥 Pipeline failed with unexpected error")
        # Attempt to record the failure in the run log
        try:
            update_run_log(
                config.RUN_LOG_FILE,
                {
                    "date": datetime.date.today().isoformat(),
                    "expressions_added": 0,
                    "total_count": get_total_count(
                        load_index(config.INDEX_FILE)
                    ),
                    "sources_scraped": 0,
                    "status": "error",
                },
            )
        except Exception:
            logger.exception("Failed to write error entry to run log")
        sys.exit(1)

    # ── Done ──────────────────────────────────────────────────────────
    elapsed = datetime.datetime.now() - start_time
    logger.info("=" * 60)
    logger.info("✅ Pipeline finished successfully")
    logger.info(f"   Total time: {elapsed}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
