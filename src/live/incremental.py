from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from core.config import Settings, load_settings
from core.utils import ensure_parent, write_json
from ingestion.crossref import PaperRecord, fetch_doi_record, fetch_records_by_date_range
from live.config import LiveConfig
from live.state import LiveState


class RecordStatus(Enum):
    """Classification of records during incremental ingestion."""
    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def compute_date_range(
    last_index_time: str | None,
    overlap_seconds: int,
) -> tuple[str, str]:
    """Compute from/until date range for incremental fetch.
    
    Returns (from_date, until_date) in ISO 8601 format.
    """
    now = datetime.now(UTC)
    
    if last_index_time:
        try:
            from_dt = datetime.fromisoformat(last_index_time.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            from_dt = now - timedelta(seconds=overlap_seconds)
    else:
        from_dt = now - timedelta(seconds=overlap_seconds)
    
    until_dt = now
    
    return (
        from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        until_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def classify_record(
    record: PaperRecord,
    existing_ids: set[str],
    existing_timestamps: dict[str, str],
) -> RecordStatus:
    """Classify a record as NEW, UPDATED, or UNCHANGED."""
    paper_id = record.paper_id
    
    if paper_id not in existing_ids:
        return RecordStatus.NEW
    
    existing_ts = existing_timestamps.get(paper_id, "")
    if not existing_ts:
        return RecordStatus.NEW
    
    try:
        existing_dt = datetime.fromisoformat(existing_ts.replace("Z", "+00:00"))
        new_dt_str = record.updated or record.published
        if new_dt_str:
            new_dt = datetime.fromisoformat(new_dt_str)
            if new_dt > existing_dt:
                return RecordStatus.UPDATED
    
    except (ValueError, AttributeError):
        return RecordStatus.UPDATED
    
    return RecordStatus.UNCHANGED


def generate_run_id() -> str:
    """Generate unique run ID for a live ingestion run."""
    return f"live_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}"


def persist_raw_response(run_id: str, records: list[PaperRecord], project_dir: Path) -> Path:
    """Persist raw Crossref response to file."""
    raw_dir = project_dir / "data" / "live" / "raw"
    ensure_parent(raw_dir)
    
    path = raw_dir / f"{run_id}.json"
    
    payload = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "records": [r.to_dict() for r in records],
    }
    
    write_json(path, payload)
    return path


def load_raw_response(run_id: str, project_dir: Path) -> list[dict[str, Any]]:
    """Load persisted raw Crossref response."""
    raw_dir = project_dir / "data" / "live" / "raw"
    path = raw_dir / f"{run_id}.json"
    
    if not path.exists():
        raise FileNotFoundError(f"Raw response not found: {path}")
    
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    
    return data.get("records", [])


def incremental_fetch(
    settings: Settings,
    live_config: LiveConfig,
    state: LiveState,
) -> tuple[list[PaperRecord], str]:
    """Perform incremental fetch from Crossref.
    
    Returns (records, run_id).
    """
    run_id = generate_run_id()
    
    watermark = state.get_watermark()
    from_date, until_date = compute_date_range(watermark, live_config.overlap_seconds)
    
    records = fetch_records_by_date_range(
        settings=settings,
        from_index_date=from_date,
        until_index_date=until_date,
    )
    
    state.update_poll(run_id, len(records))
    
    if records:
        persist_raw_response(run_id, records, settings.paths.project_dir)
    
    return records, run_id


def fetch_single_doi(doi: str, settings: Settings) -> PaperRecord | None:
    """Fetch a single DOI record from Crossref."""
    return fetch_doi_record(doi, settings)
