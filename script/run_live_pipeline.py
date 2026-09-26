"""Live dataset-monitor polling loop.

Monitors the authoritative live dataset (data/clean/papers_clean.csv) for
modifications by comparing its content fingerprint (sha256) on each cycle.

On change detection:
  1. Logs DATA_CHANGE_DETECTED event
  2. Calls src/live/recovery.detect_and_recover() to diagnose, quarantine,
     restore from raw, re-embed, update Chroma, and validate.
  3. Writes recovery report to data/live/recovery/recovery_<run_id>.json
  4. Updates state.json with new fingerprint and record count

On no change:
  - Logs NO_CHANGE event
  - Updates last_poll_at timestamp

Loops forever until SIGINT/SIGTERM.

Usage:
  python script/run_live_pipeline.py
"""
from __future__ import annotations

import hashlib
import json
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Ensure src/ is on path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import logging
import os

from core.config import load_settings
from core.utils import ensure_parent
from live.config import LiveConfig, LIVE_DATASET_PATH_KEY
from live.incremental import generate_run_id
from live.recovery import detect_and_recover
from live.repair import log_event
from live.state import LiveState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _compute_file_fingerprint(path: Path) -> dict | None:
    """Compute fingerprint of a file: sha256 of content, size, mtime."""
    if not path.exists():
        return None
    try:
        content = path.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        stat = path.stat()
        return {
            "sha256": sha,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "record_count": _count_records(path),
        }
    except Exception as e:
        logger.warning(f"Cannot fingerprint {path}: {e}")
        return None


def _count_records(path: Path) -> int:
    """Count records in a CSV or JSON file."""
    if not path.exists():
        return 0
    try:
        if path.suffix.lower() == ".csv":
            import pandas as pd
            df = pd.read_csv(path)
            return len(df)
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return len(data)
            if isinstance(data, dict):
                return len(data.get("records", []))
    except Exception:
        pass
    return 0


def _get_dataset_path(live_config: LiveConfig) -> Path:
    """Resolve the monitored dataset path from config."""
    if live_config.monitor_target_override:
        raw = live_config.monitor_target_override
    else:
        raw = os.getenv("LIVE_MONITOR_TARGET", LIVE_DATASET_PATH_KEY)
    project_dir = PROJECT_ROOT
    return (project_dir / raw).resolve()


def _load_fingerprints(state: LiveState) -> dict[str, dict]:
    """Load stored fingerprints from state."""
    return state.data.get("dataset_fingerprints", {})


def _main() -> int:
    settings = load_settings(PROJECT_ROOT)
    live_config = LiveConfig.from_env()
    poll_interval = int(os.getenv("LIVE_POLL_INTERVAL_SECONDS", "15"))
    dataset_path = _get_dataset_path(live_config)

    state = LiveState(settings.paths.project_dir / "data" / "live" / "state.json")

    logger.info(f"=== Live Dataset Monitor ===")
    logger.info(f"Dataset: {dataset_path}")
    logger.info(f"Poll interval: {poll_interval}s")
    logger.info(f"Press Ctrl+C to stop gracefully")

    running = True

    def _signal_handler(sig, frame):
        nonlocal running
        logger.info("Shutdown signal received, finishing current cycle...")
        running = False

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except (AttributeError, ValueError):
        pass

    # Initialize: compute baseline fingerprint if not set
    stored_fps = _load_fingerprints(state)
    if str(dataset_path) not in stored_fps or not stored_fps[str(dataset_path)]:
        fp = _compute_file_fingerprint(dataset_path)
        if fp:
            state.update_dataset_fingerprint(
                str(dataset_path), fp["sha256"], fp.get("record_count", 0)
            )
            logger.info(f"Baseline fingerprint established: {fp['sha256'][:16]}... ({fp['record_count']} rows)")

    state.set_stage("MONITORING")
    cycle_count = 0
    error_count = 0

    while running:
        run_id = generate_run_id()
        cycle_start = datetime.now(UTC)
        cycle_count += 1

        log_event(
            settings.paths.project_dir,
            "LIVE_POLL_STARTED",
            run_id,
            None,
            "dataset_monitor",
            "poll_cycle",
            {"dataset": str(dataset_path), "cycle": cycle_count},
        )

        logger.info(f"[{run_id[:20]}] Poll cycle {cycle_count} started at {cycle_start.isoformat()}")

        if not dataset_path.exists():
            logger.warning(f"Target not found: {dataset_path} — skipping cycle")
            log_event(
                settings.paths.project_dir,
                "NO_CHANGE",
                run_id,
                None,
                "dataset_monitor",
                "target_not_found",
                {"dataset": str(dataset_path)},
            )
            state.update_poll(run_id, 0)
            state.save()
            if running:
                time.sleep(poll_interval)
            continue

        current_fp = _compute_file_fingerprint(dataset_path)
        if current_fp is None:
            logger.warning(f"Cannot compute fingerprint for {dataset_path}")
            log_event(
                settings.paths.project_dir,
                "NO_CHANGE",
                run_id,
                None,
                "dataset_monitor",
                "fingerprint_error",
                {"dataset": str(dataset_path)},
            )
            state.update_poll(run_id, 0)
            state.save()
            if running:
                time.sleep(poll_interval)
            continue

        stored_fps = _load_fingerprints(state)
        stored_fp = stored_fps.get(str(dataset_path), {})
        stored_sha = stored_fp.get("sha256", "")

        if current_fp["sha256"] != stored_sha:
            # === CHANGE DETECTED ===
            logger.info(
                f"Change detected! "
                f"Stored: {stored_sha[:16] if stored_sha else 'none'}... "
                f"Current: {current_fp['sha256'][:16]}... "
                f"Rows: {stored_fp.get('record_count', '?')} → {current_fp['record_count']}"
            )
            log_event(
                settings.paths.project_dir,
                "DATA_CHANGE_DETECTED",
                run_id,
                None,
                "dataset_monitor",
                "change_detected",
                {
                    "dataset": str(dataset_path),
                    "stored_sha": stored_sha,
                    "current_sha": current_fp["sha256"],
                    "rows_before": stored_fp.get("record_count", 0),
                    "rows_after": current_fp["record_count"],
                },
            )

            state.update_change_detected(run_id)

            try:
                report = detect_and_recover(
                    settings=settings,
                    live_config=live_config,
                    run_id=run_id,
                    target_path=dataset_path,
                )
                status = report.get("status", "unknown")
                logger.info(f"Recovery completed with status: {status}")

                # Update state with new fingerprint after recovery
                restored_fp = _compute_file_fingerprint(dataset_path)
                if restored_fp:
                    state.update_dataset_fingerprint(
                        str(dataset_path),
                        restored_fp["sha256"],
                        restored_fp.get("record_count", 0),
                    )
                    logger.info(
                        f"Post-recovery fingerprint: {restored_fp['sha256'][:16]}... "
                        f"({restored_fp['record_count']} rows)"
                    )

                # Update validation statuses from report
                val = report.get("validation", {})
                gx_s = "PASS" if val.get("gx_after", {}).get("success") else "FAIL"
                fr_s = "PASS" if val.get("freshness_after", {}).get("is_fresh") else "FAIL"
                rv_s = "OK" if val.get("retrieval_validation", {}).get("status") == "PASS" else "ERROR"
                state.update_validation(gx_s, fr_s, rv_s)

                # Count events
                events_path = settings.paths.project_dir / "data" / "live" / "events" / "events.jsonl"
                if events_path.exists():
                    try:
                        event_count = sum(1 for _ in open(events_path, encoding="utf-8") if _.strip())
                        state.update_event_count(event_count)
                    except Exception:
                        pass

                state.recovery_complete(status)

                log_event(
                    settings.paths.project_dir,
                    "RECOVERY_TRIGGERED",
                    run_id,
                    None,
                    "dataset_monitor",
                    status,
                    {
                        "status": status,
                        "issues": report.get("detection", {}).get("issues_detected", 0),
                        "records_restored": report.get("repair", {}).get("records_restored", 0),
                    },
                )

            except Exception as e:
                error_count += 1
                logger.exception(f"Recovery failed: {e}")
                state.update_error(str(e))
                state.set_stage("IDLE")
                log_event(
                    settings.paths.project_dir,
                    "RECOVERY_FAILED",
                    run_id,
                    None,
                    "dataset_monitor",
                    "failed",
                    {"error": str(e)},
                )

        else:
            # === NO CHANGE ===
            logger.info(f"No change detected (sha256: {current_fp['sha256'][:16]}...)")
            log_event(
                settings.paths.project_dir,
                "NO_CHANGE",
                run_id,
                None,
                "dataset_monitor",
                "no_change",
                {"dataset": str(dataset_path)},
            )
            state.update_poll(run_id, 0)
            state.save()

        cycle_end = datetime.now(UTC)
        elapsed = (cycle_end - cycle_start).total_seconds()
        logger.info(f"Cycle {cycle_count} completed in {elapsed:.1f}s")

        if running:
            logger.info(f"Sleeping for {poll_interval}s until next poll...")
            time.sleep(poll_interval)

    state.set_stage("IDLE")
    logger.info(f"Live dataset monitor stopped. Cycles: {cycle_count}, Errors: {error_count}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
