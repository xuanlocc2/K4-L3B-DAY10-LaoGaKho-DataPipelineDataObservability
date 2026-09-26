#!/usr/bin/env python3
"""Live monitoring loop: polls the target dataset for changes and auto-recovers.

Usage:
    python script/run_live_monitor.py

Environment variables:
    LIVE_POLL_INTERVAL_SECONDS  (default 15)
    LIVE_MONITOR_TARGET         (default "auto")
    LIVE_AUTO_RECOVER          (default "false")

The monitor reads from data/live/state.json and writes heartbeats to
last_monitor_poll_time on each cycle.
"""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.config import load_settings
from live.config import LiveConfig
from live.monitor import run_monitoring_cycle


_shutdown_requested = False


def _handle_signal(signum, frame):
    global _shutdown_requested
    print("\n[Monitor] Shutdown requested, finishing current cycle...")
    _shutdown_requested = True


def main() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    settings = load_settings(PROJECT_ROOT)
    live_config = LiveConfig.from_env()

    poll_interval = live_config.poll_interval_seconds
    target = live_config.monitor_target

    print(f"[Monitor] Starting live monitor")
    print(f"[Monitor] Poll interval: {poll_interval}s")
    print(f"[Monitor] Target: {target}")
    print(f"[Monitor] Auto-recover: {live_config.auto_recover}")
    print(f"[Monitor] Press Ctrl+C to stop")
    print()

    cycle_count = 0

    while not _shutdown_requested:
        cycle_count += 1
        cycle_start = time.time()

        try:
            result = run_monitoring_cycle(settings, live_config)

            changed = result.get("changed", False)
            recovery_status = result.get("recovery_status", "N/A")

            if changed:
                print(
                    f"[Cycle {cycle_count}] CHANGE DETECTED → "
                    f"rows {result['diff'].get('row_count_before', '?')}→"
                    f"{result['diff'].get('row_count_after', '?')} | "
                    f"recovery={recovery_status}"
                )
            else:
                print(f"[Cycle {cycle_count}] No change | target={result.get('target_path', 'N/A')}")

        except Exception as e:
            print(f"[Cycle {cycle_count}] ERROR: {e}")

        # Sleep for remaining time (or until shutdown)
        elapsed = time.time() - cycle_start
        sleep_time = max(0.0, poll_interval - elapsed)

        if _shutdown_requested:
            break

        time.sleep(sleep_time)

    print(f"\n[Monitor] Stopped after {cycle_count} cycles.")


if __name__ == "__main__":
    main()
