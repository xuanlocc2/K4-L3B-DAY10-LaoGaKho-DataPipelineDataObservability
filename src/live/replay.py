from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import Settings, load_settings
from core.utils import ensure_parent, write_json
from ingestion.crossref import PaperRecord, parse_crossref_payload
from live.config import LiveConfig
from live.incremental import load_raw_response
from live.pipeline import run_once
from live.state import LiveState


def replay_run(
    run_id: str,
    settings: Settings | None = None,
    live_config: LiveConfig | None = None,
) -> dict[str, Any]:
    """Replay a captured raw Crossref response through the pipeline.
    
    Never fabricates metadata; uses the persisted raw response.
    """
    if settings is None:
        settings = load_settings()
    
    if live_config is None:
        live_config = LiveConfig.from_env()
    
    state = LiveState(settings.paths.project_dir / "data" / "live" / "state.json")
    
    try:
        raw_records = load_raw_response(run_id, settings.paths.project_dir)
    except FileNotFoundError:
        return {
            "success": False,
            "error": f"Raw response not found for run_id: {run_id}",
        }
    
    records = []
    for item in raw_records:
        records.append(PaperRecord(
            paper_id=item.get("paper_id", ""),
            title=item.get("title", ""),
            summary=item.get("summary", ""),
            authors=item.get("authors", []),
            categories=item.get("categories", []),
            primary_category=item.get("primary_category", ""),
            published=item.get("published", ""),
            updated=item.get("updated", ""),
            abs_url=item.get("abs_url", ""),
            pdf_url=item.get("pdf_url", ""),
            comment=item.get("comment", ""),
        ))
    
    clean_dir = settings.paths.project_dir / "data" / "live" / "clean"
    ensure_parent(clean_dir)
    write_json(
        clean_dir / f"{run_id}_replay_clean.json",
        [r.to_dict() for r in records],
    )
    
    result = run_once(settings, live_config, state)
    
    result["replay_run_id"] = run_id
    result["replay_timestamp"] = datetime.now(UTC).isoformat()
    
    return result
