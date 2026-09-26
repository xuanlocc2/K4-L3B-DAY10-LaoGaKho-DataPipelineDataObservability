from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import Settings
from core.utils import ensure_parent, write_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import PaperRecord
from live.config import LiveConfig
from live.incremental import RecordStatus, classify_record, generate_run_id, persist_raw_response
from live.monitor import check_target_for_change
from live.repair import attempt_repair, log_event, quarantine_record, validate_record
from live.state import LiveState
from observability.quality import build_freshness_report, run_data_quality_checks
from retrieval.index import LocalEmbeddingIndex, upsert_documents


def run_once(
    settings: Settings,
    live_config: LiveConfig,
    state: LiveState | None = None,
) -> dict[str, Any]:
    """Run a single live ingestion cycle.
    
    Returns summary dict with run_id, fetched/new/updated/unchanged/rejected, latency, gx_success, freshness.
    """
    start_time = time.time()
    
    if state is None:
        state = LiveState(settings.paths.project_dir / "data" / "live" / "state.json")
    
    run_id = generate_run_id()
    
    watermark = state.get_watermark()
    from_date, until_date = _compute_date_range(watermark, live_config.overlap_seconds)
    
    try:
        from ingestion.crossref import fetch_records_by_date_range
        records = fetch_records_by_date_range(
            settings=settings,
            from_index_date=from_date,
            until_index_date=until_date,
        )
    except Exception as e:
        state.update_error(str(e))
        return {
            "run_id": run_id,
            "fetched": 0,
            "new": 0,
            "updated": 0,
            "unchanged": 0,
            "rejected": 0,
            "latency_ms": int((time.time() - start_time) * 1000),
            "gx_success": False,
            "freshness_pass": False,
            "error": str(e),
        }
    
    state.update_poll(run_id, len(records))
    
    if records:
        persist_raw_response(run_id, records, settings.paths.project_dir)
    
    existing_ids, existing_timestamps = _load_existing_index(settings)
    
    new_records = []
    updated_records = []
    unchanged_count = 0
    rejected_count = 0
    quarantined_records = []
    
    for record in records:
        status = classify_record(record, existing_ids, existing_timestamps)
        
        if status == RecordStatus.UNCHANGED:
            unchanged_count += 1
            continue
        
        is_valid, reason = validate_record(record)
        
        if not is_valid:
            quarantine_record(
                run_id=run_id,
                paper_id=record.paper_id,
                record_data=record.to_dict(),
                reason=reason or "unknown",
                project_dir=settings.paths.project_dir,
            )
            rejected_count += 1
            
            if live_config.auto_repair:
                repaired, success = attempt_repair(
                    record.paper_id,
                    settings,
                    live_config,
                    settings.paths.project_dir,
                    run_id,
                )
                if success and repaired:
                    is_valid, _ = validate_record(repaired)
                    if is_valid:
                        new_records.append(repaired)
                        rejected_count -= 1
                        log_event(
                            settings.paths.project_dir,
                            "repair_success",
                            run_id,
                            repaired.paper_id,
                            "upsert_repaired",
                            "success",
                        )
                    else:
                        quarantined_records.append(record.paper_id)
                        log_event(
                            settings.paths.project_dir,
                            "repair_failed",
                            run_id,
                            record.paper_id,
                            "remain_quarantined",
                            "failed",
                        )
                else:
                    quarantined_records.append(record.paper_id)
            else:
                quarantined_records.append(record.paper_id)
            
            continue
        
        if status == RecordStatus.NEW:
            new_records.append(record)
        elif status == RecordStatus.UPDATED:
            updated_records.append(record)
    
    run_date = datetime.now(UTC)
    
    records_to_embed = new_records + updated_records
    
    gx_success = True
    freshness_pass = True
    
    if records_to_embed:
        df_new = build_clean_dataframe(records_to_embed, run_date)
        
        quality_result = run_data_quality_checks(
            df_new,
            settings,
            f"live_{run_id}",
        )
        gx_success = quality_result.get("success", True)
        
        if not gx_success and not live_config.auto_repair:
            for _, row in df_new.iterrows():
                quarantine_record(
                    run_id=run_id,
                    paper_id=row["paper_id"],
                    record_data=row.to_dict(),
                    reason="quality_check_failed",
                    project_dir=settings.paths.project_dir,
                )
            rejected_count += len(df_new)
            records_to_embed = []
            df_new = pd.DataFrame()
        
        if not df_new.empty:
            freshness_result = build_freshness_report(
                df_new,
                settings,
                settings.paths.project_dir / "data" / "live" / "quality" / f"{run_id}_freshness.json",
            )
            freshness_pass = freshness_result.get("is_fresh", True)
            
            clean_dir = settings.paths.project_dir / "data" / "live" / "clean"
            ensure_parent(clean_dir)
            write_json(clean_dir / f"{run_id}_clean.json", df_new.to_dict(orient="records"))
            
            upsert_documents(
                df=df_new,
                settings=settings,
                collection_name=live_config.collection_name,
            )
    
    manifest = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "collection": live_config.collection_name,
        "records_indexed": len(records_to_embed),
        "quality_passed": gx_success,
        "freshness_passed": freshness_pass,
    }
    
    manifest_path = settings.paths.project_dir / "data" / "live" / "index_manifest.json"
    write_json(manifest_path, manifest)
    
    state.update_success(
        run_id=run_id,
        new_count=len(new_records),
        updated_count=len(updated_records),
        rejected_count=rejected_count,
    )
    
    latency_ms = int((time.time() - start_time) * 1000)
    
    # After successful ingestion, check the latest live clean file for changes
    clean_dir = settings.paths.project_dir / "data" / "live" / "clean"
    latest_clean = None
    if clean_dir.exists():
        candidates = sorted(clean_dir.glob("*_clean.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if candidates:
            latest_clean = candidates[0]

    if latest_clean:
        changed, diff = check_target_for_change(settings, latest_clean)
        if changed:
            log_event(
                settings.paths.project_dir,
                "DETECTION_STARTED",
                run_id,
                None,
                "post_ingestion_check",
                "change_from_baseline",
                {"target": str(latest_clean), "diff": diff},
            )

    return {
        "run_id": run_id,
        "fetched": len(records),
        "new": len(new_records),
        "updated": len(updated_records),
        "unchanged": unchanged_count,
        "rejected": rejected_count,
        "latency_ms": latency_ms,
        "gx_success": gx_success,
        "freshness_pass": freshness_pass,
    }


def _compute_date_range(
    last_index_time: str | None,
    overlap_seconds: int,
) -> tuple[str, str]:
    """Compute from/until date range for incremental fetch."""
    from datetime import timedelta
    
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


def _load_existing_index(settings: Settings) -> tuple[set[str], dict[str, str]]:
    """Load existing paper IDs and timestamps from Chroma or manifest."""
    existing_ids: set[str] = set()
    existing_timestamps: dict[str, str] = {}
    
    manifest_path = settings.paths.project_dir / "data" / "live" / "index_manifest.json"
    
    if manifest_path.exists():
        try:
            manifest = manifest_path.read_text(encoding="utf-8")
            import json
            data = json.loads(manifest)
            if "indexed_paper_ids" in data:
                existing_ids = set(data.get("indexed_paper_ids", []))
        except Exception:
            pass
    
    chroma_dir = settings.paths.chroma_dir
    collection_name = "papers-live"
    
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(chroma_dir))
        collection = client.get_collection(name=collection_name)
        
        results = collection.get(include=["metadatas"])
        for metadata in results.get("metadatas", []):
            if metadata and "paper_id" in metadata:
                existing_ids.add(str(metadata["paper_id"]))
                if "published" in metadata:
                    existing_timestamps[str(metadata["paper_id"])] = str(metadata["published"])
    except Exception:
        pass
    
    return existing_ids, existing_timestamps
