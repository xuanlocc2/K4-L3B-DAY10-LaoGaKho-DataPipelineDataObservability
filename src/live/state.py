from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


STATE_FILE = Path("data/live/state.json")


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically using temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        suffix=".tmp",
        prefix=".state_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=True)
        shutil.move(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


class LiveState:
    """Manages live ingestion state with atomic persistence.

    Extended fields:
      - stage: current pipeline stage ("IDLE", "MONITORING", "RECOVERING")
      - active_incident: bool
      - dataset_path: Path to the monitored authoritative dataset
      - dataset_fingerprint: sha256 of the authoritative dataset
      - dataset_fingerprints: dict of path → sha256 for multiple monitored files
      - record_count: number of records in the authoritative dataset
      - last_poll_at: ISO timestamp of last poll
      - last_change_at: ISO timestamp of last detected change
      - last_validation_at: ISO timestamp of last validation run
      - gx_status: "PASS" | "FAIL" | "UNKNOWN"
      - freshness_status: "PASS" | "FAIL" | "UNKNOWN"
      - index_status: "OK" | "ERROR" | "UNKNOWN"
      - live_events: number of events in events.jsonl
    """

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or STATE_FILE
        self.data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return self._default_state()

    def _default_state(self) -> dict[str, Any]:
        return {
            "last_successful_index_time": None,
            "last_poll_time": None,
            "last_successful_run": None,
            "last_run_id": None,
            "records_seen": 0,
            "records_new": 0,
            "records_updated": 0,
            "records_rejected": 0,
            "last_error": None,
            # New fields
            "stage": "IDLE",
            "active_incident": False,
            "dataset_path": str(Path("data/clean/papers_clean.csv")),
            "dataset_fingerprint": None,
            "dataset_fingerprints": {},
            "record_count": 0,
            "last_poll_at": None,
            "last_change_at": None,
            "last_validation_at": None,
            "gx_status": "UNKNOWN",
            "freshness_status": "UNKNOWN",
            "index_status": "UNKNOWN",
            "live_events": 0,
        }

    def save(self) -> None:
        """Atomically persist state to disk."""
        _atomic_write(self.state_path, self.data)

    def update_poll(self, run_id: str, fetched: int) -> None:
        """Update state after a poll cycle starts."""
        self.data["last_poll_time"] = datetime.now(UTC).isoformat()
        self.data["last_poll_at"] = datetime.now(UTC).isoformat()
        self.data["last_run_id"] = run_id
        self.data["records_seen"] = self.data.get("records_seen", 0) + fetched

    def update_success(
        self,
        run_id: str,
        new_count: int = 0,
        updated_count: int = 0,
        rejected_count: int = 0,
    ) -> None:
        """Update state after successful ingestion."""
        self.data["last_successful_run"] = datetime.now(UTC).isoformat()
        self.data["last_successful_index_time"] = datetime.now(UTC).isoformat()
        self.data["last_run_id"] = run_id
        self.data["records_new"] = self.data.get("records_new", 0) + new_count
        self.data["records_updated"] = self.data.get("records_updated", 0) + updated_count
        self.data["records_rejected"] = self.data.get("records_rejected", 0) + rejected_count
        self.data["last_error"] = None
        self.save()

    def update_error(self, error: str) -> None:
        """Update state with error information."""
        self.data["last_error"] = error
        self.save()

    def get_watermark(self) -> str | None:
        """Get the last successful index time as ISO string."""
        return self.data.get("last_successful_index_time")

    def reset(self) -> None:
        """Reset state to defaults."""
        self.data = self._default_state()
        self.save()

    # ---- Phase 4: Extended state helpers ----

    def set_stage(self, stage: str) -> None:
        """Set current pipeline stage."""
        self.data["stage"] = stage
        self.save()

    def set_active_incident(self, active: bool) -> None:
        """Set active incident flag."""
        self.data["active_incident"] = active
        self.save()

    def update_dataset_fingerprint(
        self,
        dataset_path: str,
        fingerprint: str,
        record_count: int,
    ) -> None:
        """Update the dataset fingerprint and record count."""
        self.data["dataset_path"] = dataset_path
        self.data["dataset_fingerprint"] = fingerprint
        self.data["dataset_fingerprints"] = self.data.get("dataset_fingerprints", {})
        self.data["dataset_fingerprints"][dataset_path] = fingerprint
        self.data["record_count"] = record_count
        self.data["last_poll_at"] = datetime.now(UTC).isoformat()
        self.save()

    def update_change_detected(self, run_id: str) -> None:
        """Update state when a dataset change is detected."""
        self.data["last_change_at"] = datetime.now(UTC).isoformat()
        self.data["last_run_id"] = run_id
        self.data["active_incident"] = True
        self.data["stage"] = "RECOVERING"
        self.save()

    def update_validation(
        self,
        gx_status: str,
        freshness_status: str,
        index_status: str,
    ) -> None:
        """Update validation statuses."""
        self.data["gx_status"] = gx_status
        self.data["freshness_status"] = freshness_status
        self.data["index_status"] = index_status
        self.data["last_validation_at"] = datetime.now(UTC).isoformat()
        self.save()

    def update_event_count(self, count: int) -> None:
        """Update total event count."""
        self.data["live_events"] = count
        self.save()

    def recovery_complete(self, status: str) -> None:
        """Mark recovery as complete."""
        self.data["active_incident"] = (status != "success")
        self.data["stage"] = "IDLE"
        self.data["last_validation_at"] = datetime.now(UTC).isoformat()
        self.save()
