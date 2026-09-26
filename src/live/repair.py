from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import Settings
from core.utils import ensure_parent, write_json
from ingestion.crossref import PaperRecord
from live.config import LiveConfig
from live.incremental import fetch_single_doi


class QuarantineReason:
    """Quarantine reasons for invalid records."""
    INVALID_ID = "invalid_paper_id"
    MISSING_TITLE = "missing_title"
    QUALITY_CHECK_FAILED = "quality_check_failed"
    PARSE_ERROR = "parse_error"


def quarantine_record(
    run_id: str,
    paper_id: str,
    record_data: dict[str, Any],
    reason: str,
    project_dir: Path,
) -> Path:
    """Move invalid record to quarantine directory."""
    quarantine_dir = project_dir / "data" / "live" / "quarantine"
    ensure_parent(quarantine_dir)
    
    filename = f"{run_id}_{paper_id.replace('/', '_')}.json"
    path = quarantine_dir / filename
    
    payload = {
        "run_id": run_id,
        "paper_id": paper_id,
        "reason": reason,
        "timestamp": datetime.now(UTC).isoformat(),
        "record_data": record_data,
    }
    
    write_json(path, payload)
    return path


def log_event(
    project_dir: Path,
    event_type: str,
    run_id: str,
    paper_id: str | None,
    action: str,
    result: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Append JSONL event to events log."""
    events_dir = project_dir / "data" / "live" / "events"
    events_path = events_dir / "events.jsonl"
    ensure_parent(events_path)
    
    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "run_id": run_id,
        "paper_id": paper_id,
        "action": action,
        "result": result,
        "details": details or {},
    }
    
    with open(events_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def attempt_repair(
    doi: str,
    settings: Settings,
    live_config: LiveConfig,
    project_dir: Path,
    run_id: str,
) -> tuple[PaperRecord | None, bool]:
    """Attempt to repair a quarantined record by refetching from Crossref.
    
    Returns (repaired_record, success).
    """
    if not live_config.auto_repair:
        log_event(
            project_dir=project_dir,
            event_type="repair_attempt",
            run_id=run_id,
            paper_id=doi,
            action="skip",
            result="auto_repair_disabled",
        )
        return None, False
    
    refetched = fetch_single_doi(doi, settings)
    
    if refetched is None:
        log_event(
            project_dir=project_dir,
            event_type="repair_attempt",
            run_id=run_id,
            paper_id=doi,
            action="refetch",
            result="failed",
            details={"reason": "Crossref fetch returned no record"},
        )
        return None, False
    
    log_event(
        project_dir=project_dir,
        event_type="repair_attempt",
        run_id=run_id,
        paper_id=doi,
        action="refetch",
        result="success",
        details={"title": refetched.title},
    )
    
    return refetched, True


def validate_record(record: PaperRecord) -> tuple[bool, str | None]:
    """Validate a record for quality gate.
    
    Returns (is_valid, reason_if_invalid).
    """
    if not record.paper_id or len(record.paper_id) < 5:
        return False, QuarantineReason.INVALID_ID
    
    if not record.title or len(record.title.strip()) < 5:
        return False, QuarantineReason.MISSING_TITLE
    
    return True, None
