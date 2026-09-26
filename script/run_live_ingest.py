"""Live Crossref ingestion polling loop.

Continuously polls Crossref for new/updated papers and ingests them.
This is the original polling behavior from the data pipeline.

Usage:
  python script/run_live_ingest.py
"""
from __future__ import annotations

import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Ensure src/ is on path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import logging

from core.config import load_settings
from live.config import LiveConfig
from live.pipeline import run_once
from live.state import LiveState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    """Run live ingestion pipeline in a loop with configurable poll interval."""
    settings = load_settings(PROJECT_ROOT)
    live_config = LiveConfig.from_env()

    poll_interval = live_config.poll_interval_seconds

    state = LiveState(settings.paths.project_dir / "data" / "live" / "state.json")

    logger.info(f"Starting live ingestion loop (poll interval: {poll_interval}s)")
    logger.info(f"Collection: {live_config.collection_name}")
    logger.info("Press Ctrl+C to stop gracefully")

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        logger.info("Shutdown signal received, finishing current run...")
        running = False

    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except (AttributeError, ValueError):
        pass

    run_count = 0
    error_count = 0

    while running:
        run_id_prefix = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

        try:
            logger.info(f"[{run_id_prefix}] Starting ingest cycle...")

            result = run_once(settings, live_config, state)

            run_count += 1

            if "error" in result:
                error_count += 1
                logger.error(f"[{result['run_id']}] Error: {result['error']}")
            else:
                logger.info(
                    f"[{result['run_id']}] Poll complete: "
                    f"fetched={result['fetched']} "
                    f"new={result['new']} "
                    f"updated={result['updated']} "
                    f"unchanged={result['unchanged']} "
                    f"rejected={result['rejected']} "
                    f"latency={result['latency_ms']}ms "
                    f"gx={'PASS' if result['gx_success'] else 'FAIL'} "
                    f"freshness={'PASS' if result['freshness_pass'] else 'FAIL'}"
                )

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            break
        except Exception as e:
            error_count += 1
            logger.exception(f"[{run_id_prefix}] Unexpected error: {e}")

        if running:
            logger.info(f"Sleeping for {poll_interval}s until next poll...")
            time.sleep(poll_interval)

    logger.info(f"Live ingestion stopped. Runs: {run_count}, Errors: {error_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
