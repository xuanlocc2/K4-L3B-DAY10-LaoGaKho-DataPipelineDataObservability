"""Live monitoring module for detecting dataset drift.

Provides:
  - check_target_for_change: fingerprints target and compares against known-good baseline
  - run_monitoring_cycle: full cycle with optional auto-recovery
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import Settings
from core.utils import ensure_parent, read_json, write_json
from live.config import LiveConfig
from live.incremental import generate_run_id
from live.repair import log_event
from observability.diff import dataset_fingerprint
from observability.quality import build_freshness_report, run_data_quality_checks


def _atomic_write_json(path: Path, data: Any) -> None:
    """Atomic JSON write using temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=".fingerprint_",
    )
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=True)
        Path(tmp_path).replace(path)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise


def check_target_for_change(
    settings: Settings,
    target_path: Path,
) -> tuple[bool, dict[str, Any]]:
    """Check if the target file has changed from its stored known-good fingerprint.

    Returns (changed: bool, fingerprint_diff: dict).
    The known-good fingerprint is stored at data/live/known_good_fingerprint.json.
    On first run, the fingerprint is saved as the new baseline.
    """
    target_path = Path(target_path)
    if not target_path.exists():
        return True, {"error": "file_not_found", "current": None, "stored": None}

    # Load current data
    current_data = read_json(target_path)
    if isinstance(current_data, dict):
        current_records = current_data.get("records", [])
    else:
        current_records = current_data

    fp_current = dataset_fingerprint(current_records)

    # Load stored fingerprint
    fingerprint_path = settings.paths.project_dir / "data" / "live" / "known_good_fingerprint.json"

    if fingerprint_path.exists():
        try:
            stored_fp = read_json(fingerprint_path)
        except Exception:
            stored_fp = None
    else:
        stored_fp = None

    if stored_fp is None:
        # First time: save current as known-good baseline
        _atomic_write_json(fingerprint_path, fp_current)
        return False, {
            "event": "baseline_established",
            "current": fp_current,
            "stored": None,
        }

    # Compare fingerprints
    file_same = fp_current.get("file_sha256") == stored_fp.get("file_sha256")
    count_same = fp_current.get("row_count") == stored_fp.get("row_count")

    changed = not (file_same and count_same)

    diff: dict[str, Any] = {
        "current": fp_current,
        "stored": stored_fp,
        "file_sha256_changed": fp_current.get("file_sha256") != stored_fp.get("file_sha256"),
        "row_count_changed": fp_current.get("row_count") != stored_fp.get("row_count"),
        "row_count_before": stored_fp.get("row_count", 0),
        "row_count_after": fp_current.get("row_count", 0),
    }

    # Update stored fingerprint if changed
    if changed:
        _atomic_write_json(fingerprint_path, fp_current)
        diff["event"] = "change_detected"
    else:
        diff["event"] = "no_change"

    return changed, diff


def run_monitoring_cycle(
    settings: Settings,
    live_config: LiveConfig,
) -> dict[str, Any]:
    """Run a single monitoring cycle.

    Checks the target file for changes; if changed, logs events and
    optionally triggers detect_and_recover.

    Returns a summary dict of the cycle.
    """
    from live.recovery import detect_and_recover

    project_dir = settings.paths.project_dir
    run_id = generate_run_id()
    cycle_time = datetime.now(UTC).isoformat()

    # Resolve target
    target_str = live_config.monitor_target
    if target_str == "auto" or not target_str:
        # Pick latest data/live/clean/*_clean.json
        clean_dir = project_dir / "data" / "live" / "clean"
        if clean_dir.exists():
            candidates = sorted(clean_dir.glob("*_clean.json"), key=lambda f: f.stat().st_mtime, reverse=True)
            if candidates:
                target_path = candidates[0]
            else:
                # Fall back to data/clean/papers_clean.json
                target_path = project_dir / "data" / "clean" / "papers_clean.json"
        else:
            target_path = project_dir / "data" / "clean" / "papers_clean.json"
    else:
        target_path = Path(target_str)

    target_path = Path(target_path)

    # Check for change
    changed, diff = check_target_for_change(settings, target_path)

    # Update state heartbeat
    state_path = project_dir / "data" / "live" / "state.json"
    try:
        state = read_json(state_path) if state_path.exists() else {}
    except Exception:
        state = {}
    state["last_monitor_poll_time"] = cycle_time
    if changed:
        state["last_change_time"] = cycle_time
        state["last_recovery_run_id"] = run_id
    ensure_parent(state_path)
    _atomic_write_json(state_path, state)

    cycle_summary: dict[str, Any] = {
        "run_id": run_id,
        "cycle_time": cycle_time,
        "target_path": str(target_path),
        "changed": changed,
        "diff": diff,
        "recovery_triggered": False,
        "recovery_report": None,
    }

    if changed:
        log_event(
            project_dir,
            "DETECTION_STARTED",
            run_id,
            None,
            "monitoring_cycle",
            "change_detected",
            {"target": str(target_path), "diff": diff},
        )

        log_event(
            project_dir,
            "DATA_CHANGE_DETECTED",
            run_id,
            None,
            "monitoring_cycle",
            "change_detected",
            {
                "row_count_before": diff.get("row_count_before", 0),
                "row_count_after": diff.get("row_count_after", 0),
            },
        )

        if live_config.auto_recover:
            log_event(
                project_dir,
                "RECOVERY_STARTED",
                run_id,
                None,
                "monitoring_cycle",
                "auto_recovery",
                {},
            )
            try:
                report = detect_and_recover(
                    settings=settings,
                    live_config=live_config,
                    run_id=run_id,
                    target_path=target_path,
                )
                cycle_summary["recovery_triggered"] = True
                cycle_summary["recovery_report"] = str(
                    project_dir / "data" / "live" / "recovery" / f"recovery_{run_id}.json"
                )
                cycle_summary["recovery_status"] = report.get("status", "unknown")
            except Exception as e:
                cycle_summary["recovery_error"] = str(e)
                log_event(
                    project_dir,
                    "RECOVERY_FAILED",
                    run_id,
                    None,
                    "monitoring_cycle",
                    "auto_recovery_failed",
                    {"error": str(e)},
                )
        else:
            log_event(
                project_dir,
                "ISSUE_DIAGNOSED",
                run_id,
                None,
                "monitoring_cycle",
                "change_detected_no_auto_recover",
                {"note": "auto_recover=False, manual intervention required"},
            )
    else:
        log_event(
            project_dir,
            "MONITORING_POLL",
            run_id,
            None,
            "monitoring_cycle",
            "no_change",
            {"target": str(target_path)},
        )

    return cycle_summary
