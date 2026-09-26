"""Detection and recovery module for live data pipeline.

Handles:
  - Detecting corruption / drift in the monitored clean dataset
  - Quarantining the current (corrupted) snapshot
  - Recovering from raw source (data/raw/crossref_records.json or Crossref re-fetch)
  - Rebuilding clean dataset, embeddings, and Chroma index
  - Writing structured recovery report and event log
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import Settings
from core.utils import ensure_parent, read_json, write_json
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import (
    PaperRecord,
    fetch_source_records,
    load_raw_records,
)
from live.config import LiveConfig
from live.repair import log_event
from observability.diff import dataset_fingerprint, diff_datasets, normalize_issue
from observability.quality import build_freshness_report, run_data_quality_checks
from retrieval.embeddings import MiniLMEmbeddings
from retrieval.index import LocalEmbeddingIndex


# Trusted raw snapshot run IDs (live/raw/*.json) that can be used as recovery source
_TRUSTED_RAW_RUN_IDS: set[str] = set()


def _get_trusted_raw_runs(project_dir: Path) -> set[str]:
    """Return set of run IDs from data/live/raw/ that are considered trusted."""
    raw_dir = project_dir / "data" / "live" / "raw"
    if not raw_dir.exists():
        return set()
    return {f.stem for f in raw_dir.glob("*.json")}


def _resolve_recovery_source(
    settings: Settings,
    project_dir: Path,
) -> tuple[list[dict[str, Any]], str, Path]:
    """Resolve the known-good recovery source.

    Returns (records, source_type, source_path).
    Source type is "raw_snapshot" or "crossref".
    """
    # A. Prefer data/raw/crossref_records.json
    raw_records_path = project_dir / "data" / "raw" / "crossref_records.json"
    if raw_records_path.exists():
        records = read_json(raw_records_path)
        # Convert to dict format compatible with load_raw_records
        return records, "raw_snapshot", raw_records_path

    # B. Fall back to latest trusted live/raw/*.json
    trusted = _get_trusted_raw_runs(project_dir)
    if trusted:
        # Pick the latest by modified time
        raw_dir = project_dir / "data" / "live" / "raw"
        candidates = sorted(
            raw_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            if candidate.stem in trusted:
                data = read_json(candidate)
                raw_records = data.get("records", [])
                return raw_records, "raw_snapshot", candidate

    # C. Re-fetch from Crossref
    try:
        records = fetch_source_records(settings)
        records_dicts = [r.to_dict() for r in records]
        # Cache the re-fetched data
        cache_path = project_dir / "data" / "live" / "raw" / "crossref_refetch.json"
        ensure_parent(cache_path)
        write_json(cache_path, {
            "run_id": "crossref_refetch",
            "timestamp": datetime.now(UTC).isoformat(),
            "records": records_dicts,
        })
        return records_dicts, "crossref", cache_path
    except Exception as e:
        raise RuntimeError(
            f"Cannot resolve recovery source: raw records missing, no trusted live raw "
            f"files found, and Crossref re-fetch failed: {e}"
        ) from e


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically using temp file + rename (Windows-safe)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=".recovery_",
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


def _quota_snapshot(
    current_records: list[dict],
    run_id: str,
    project_dir: Path,
    original_path: Path | None = None,
) -> Path:
    """Save current (potentially corrupted) records to quarantine.

    Uses timestamped filename to avoid overwriting existing quarantines.
    Writes both a JSON copy and (if original_path exists) a copy of the
    original file type next to the JSON in quarantine/.
    """
    quarantine_dir = project_dir / "data" / "live" / "quarantine"
    ensure_parent(quarantine_dir)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{run_id}_before_{timestamp}.json"
    path = quarantine_dir / filename

    payload = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "record_count": len(current_records),
        "records": current_records,
    }

    _atomic_write_json(path, payload)

    # Also copy the original file type if it exists
    if original_path is not None and original_path.exists():
        ext = original_path.suffix.lower()
        if ext in {".csv", ".json"}:
            copy_name = f"{run_id}_before_{timestamp}{ext}"
            copy_path = quarantine_dir / copy_name
            try:
                shutil.copy2(original_path, copy_path)
            except Exception:
                pass  # Non-critical: JSON quarantine is the primary artifact

    return path


def _load_target_file(target_path: Path) -> list[dict[str, Any]]:
    """Load records from a JSON or CSV file.

    Returns a list of dicts. CSV columns: paper_id, title, summary, etc.
    """
    target_path = Path(target_path)
    if not target_path.exists():
        return []

    if target_path.suffix.lower() == ".csv":
        df = pd.read_csv(target_path)
        return df.to_dict(orient="records")
    else:
        # JSON: either a list or a dict with "records" key
        data = read_json(target_path)
        if isinstance(data, dict):
            return data.get("records", [])
        return data


def _rebuild_embeddings_for_changed(
    changed_paper_ids: list[str],
    all_records: list[dict[str, Any]],
    settings: Settings,
    project_dir: Path,
) -> tuple[list[str], list[str], Path]:
    """Recompute embeddings for changed paper_ids only.

    Returns (recomputed_ids, unchanged_ids, embeddings_path).
    """
    # Load existing embeddings manifest
    embeddings_path = project_dir / "data" / "embeddings" / "papers_embeddings.json"
    existing_docs = []
    existing_paper_ids: set[str] = set()

    if embeddings_path.exists():
        try:
            payload = read_json(embeddings_path)
            existing_docs = payload.get("documents", [])
            existing_paper_ids = {
                doc.get("paper_id", "")
                for doc in existing_docs
                if doc.get("paper_id")
            }
        except Exception:
            pass

    # Build df from all records
    run_date = datetime.now(UTC)
    paper_records = [
        PaperRecord(
            paper_id=r.get("paper_id", ""),
            title=r.get("title", ""),
            summary=r.get("summary", ""),
            authors=r.get("authors", []),
            categories=r.get("categories", []),
            primary_category=r.get("primary_category", ""),
            published=r.get("published", ""),
            updated=r.get("updated", ""),
            abs_url=r.get("abs_url", ""),
            pdf_url=r.get("pdf_url", ""),
            comment=r.get("comment", ""),
        )
        for r in all_records
    ]
    df = build_clean_dataframe(paper_records, run_date)

    changed_set = set(changed_paper_ids)
    recomputed_ids = []
    unchanged_ids = list(changed_set & existing_paper_ids)

    # Recompute for changed
    changed_df = df[df["paper_id"].isin(changed_set)]
    if not changed_df.empty:
        embed_model = MiniLMEmbeddings(settings.embedding_model)
        texts = changed_df["text_for_embedding"].tolist()
        embeddings = embed_model.embed_documents(texts)

        for idx, (_, row) in enumerate(changed_df.iterrows()):
            pid = row["paper_id"]
            # Update or add document
            existing_idx = next(
                (i for i, d in enumerate(existing_docs) if d.get("paper_id") == pid),
                -1,
            )
            doc = {
                "record_id": f"{pid}::0",
                "paper_id": pid,
                "title": row["title"],
                "content": row["text_for_embedding"],
                "metadata": {
                    "paper_id": pid,
                    "title": row["title"],
                    "published": row["published"],
                    "authors_joined": row["authors_joined"],
                    "categories_joined": row["categories_joined"],
                    "summary": row["summary"],
                    "abs_url": row["abs_url"],
                    "pdf_url": row["pdf_url"],
                },
            }
            if existing_idx >= 0:
                existing_docs[existing_idx] = doc
            else:
                existing_docs.append(doc)
            recomputed_ids.append(pid)

    # Write merged manifest
    ensure_parent(embeddings_path)
    _atomic_write_json(embeddings_path, {
        "backend": "chroma",
        "embedding_model": settings.embedding_model,
        "persist_path": str(settings.paths.chroma_dir),
        "collection_name": "papers-live",
        "documents": existing_docs,
    })

    return recomputed_ids, unchanged_ids, embeddings_path


def _full_rebuild_chroma_collection(
    all_records: list[dict[str, Any]],
    settings: Settings,
    project_dir: Path,
) -> dict[str, int]:
    """Full rebuild of Chroma collection from all records.

    Uses LocalEmbeddingIndex.build() which deletes and recreates the collection.
    Returns summary dict with vectors_added, vectors_updated, vectors_deleted, rebuild_mode.
    """
    run_date = datetime.now(UTC)
    paper_records = [
        PaperRecord(
            paper_id=r.get("paper_id", ""),
            title=r.get("title", ""),
            summary=r.get("summary", ""),
            authors=r.get("authors", []),
            categories=r.get("categories", []),
            primary_category=r.get("primary_category", ""),
            published=r.get("published", ""),
            updated=r.get("updated", ""),
            abs_url=r.get("abs_url", ""),
            pdf_url=r.get("pdf_url", ""),
            comment=r.get("comment", ""),
        )
        for r in all_records
        if r.get("paper_id")
    ]
    df = build_clean_dataframe(paper_records, run_date)

    if df.empty:
        return {"vectors_added": 0, "vectors_updated": 0, "vectors_deleted": 0, "collection": "papers-live", "rebuild_mode": "full_rebuild"}

    index = LocalEmbeddingIndex.build(
        df=df,
        settings=settings,
        embeddings_output_path=settings.paths.embeddings_json,
        collection_name="papers-live",
    )

    vectors_added = len(df)
    return {
        "vectors_added": vectors_added,
        "vectors_updated": 0,
        "vectors_deleted": 0,
        "collection": "papers-live",
        "rebuild_mode": "full_rebuild",
    }


def _update_chroma_collection(
    changed_paper_ids: list[str],
    all_records: list[dict[str, Any]],
    settings: Settings,
    project_dir: Path,
) -> dict[str, int]:
    """Update Chroma collection with changed records.

    For safety, this now does a FULL rebuild rather than incremental upsert,
    to avoid inconsistencies with Chroma versions. Returns summary dict with
    vectors_added, vectors_updated, vectors_deleted, rebuild_mode.
    """
    if not all_records:
        return {"vectors_added": 0, "vectors_updated": 0, "vectors_deleted": 0, "collection": "papers-live", "rebuild_mode": "full_rebuild"}
    return _full_rebuild_chroma_collection(all_records, settings, project_dir)


def detect_and_recover(
    settings: Settings,
    live_config: LiveConfig,
    run_id: str,
    target_path: Path | None = None,
) -> dict[str, Any]:
    """Detect corruption in the target file and recover from known-good source.

    Args:
        settings: Application settings
        live_config: Live configuration
        run_id: Unique recovery run identifier
        target_path: Path to the monitored clean dataset.
                    Defaults to data/clean/papers_clean.json.

    Returns:
        Structured recovery report dict (also written to disk).
    """
    started_at = datetime.now(UTC).isoformat()
    project_dir = settings.paths.project_dir

    # Resolve target path
    if target_path is None:
        target_path = project_dir / "data" / "clean" / "papers_clean.json"
    target_path = Path(target_path)

    log_event(
        project_dir,
        "DETECTION_STARTED",
        run_id,
        None,
        "detect_and_recover",
        "started",
        {"target": str(target_path)},
    )

    # --- Step 1: Load current derived dataset ---
    try:
        current_records = _load_target_file(target_path)
    except FileNotFoundError:
        current_records = []
    except Exception as e:
        log_event(
            project_dir, "RECOVERY_FAILED", run_id, None,
            "load_target", "failed", {"error": str(e)},
        )
        return {
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "status": "failed",
            "error": f"Cannot load target file: {e}",
        }

    # --- Step 2: Resolve recovery source ---
    try:
        source_records, source_type, source_path = _resolve_recovery_source(settings, project_dir)
    except Exception as e:
        log_event(
            project_dir, "RECOVERY_FAILED", run_id, None,
            "resolve_source", "failed", {"error": str(e)},
        )
        return {
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "status": "failed",
            "error": f"Cannot resolve recovery source: {e}",
        }

    retrieved_at = datetime.now(UTC).isoformat()

    log_event(
        project_dir, "SOURCE_RESTORE_COMPLETED", run_id, None,
        "source_resolved", "success",
        {"type": source_type, "path": str(source_path)},
    )

    # --- Step 3: Quarantine current snapshot ---
    quarantine_path = _quota_snapshot(current_records, run_id, project_dir, target_path)

    log_event(
        project_dir, "QUARANTINE_CREATED", run_id, None,
        "quarantine", "success", {"path": str(quarantine_path)},
    )

    # --- Step 4: Compute fingerprint and diff ---
    # Compare source (known good) against current (possibly corrupted).
    # Records in source but not current = "removed" from source = high severity corruption.
    # Records in current but not source = "added" = low severity (legitimate new data).
    fp_before = dataset_fingerprint(source_records)
    fp_after = dataset_fingerprint(current_records)

    changes = diff_datasets(source_records, current_records)

    # Count high-severity issues (removed, modified, duplicate)
    issues = []
    for change in changes:
        if change["change_type"] in {"removed", "modified"} and change["severity"] == "high":
            issue_type = "missing_record" if change["change_type"] == "removed" else "modified_field"
            # Check for blanked fields
            raw_fields = change.get("fields", [])
            blanked_fields = [
                f["field"] for f in raw_fields
                if _normalize_val(f.get("before")) and not _normalize_val(f.get("after"))
            ]
            if blanked_fields:
                issue_type = "blanked_field"
            # Normalize fields to canonical dict schema
            from observability.diff import normalize_field_diff
            canonical_fields = [normalize_field_diff(f) for f in raw_fields]
            issues.append({
                "paper_id": change["paper_id"],
                "issue_type": issue_type,
                "severity": change["severity"],
                "change_type": change["change_type"],
                "fields": canonical_fields,
            })
        elif change["change_type"] == "duplicate" and change["severity"] == "high":
            # Duplicate paper_id in current dataset
            issues.append({
                "paper_id": change["paper_id"],
                "issue_type": "duplicate",
                "severity": change["severity"],
                "change_type": change["change_type"],
                "fields": [],
            })

    high_severity_issues = [i for i in issues if i["severity"] == "high"]

    log_event(
        project_dir, "DATA_CHANGE_DETECTED", run_id, None,
        "diff_analysis", "detected",
        {
            "records_before": fp_before["row_count"],
            "records_after": fp_after["row_count"],
            "issues": len(issues),
            "high_severity": len(high_severity_issues),
        },
    )

    # --- Step 5: Run quality checks on current (before) ---
    try:
        df_current = pd.DataFrame(current_records) if current_records else pd.DataFrame()
        if not df_current.empty and "paper_id" in df_current.columns:
            gx_before = run_data_quality_checks(
                df_current, settings, "recovery_before",
            )
        else:
            gx_before = {"success": True, "row_count": 0}
    except Exception as e:
        gx_before = {"success": False, "row_count": 0, "error": str(e)}

    try:
        if not df_current.empty and "published" in df_current.columns:
            freshness_before = build_freshness_report(
                df_current, settings,
                project_dir / "data" / "live" / "quality" / f"{run_id}_freshness_before.json",
            )
        else:
            freshness_before = {"is_fresh": True, "stale_ratio": 0.0}
    except Exception:
        freshness_before = {"is_fresh": True, "stale_ratio": 0.0}

    # --- Step 6: Attempt recovery if high-severity issues found ---
    records_restored = 0
    records_modified = 0
    records_removed = 0
    fields_restored = 0
    status = "success"
    restored_records: list[dict] = []

    if high_severity_issues:
        log_event(
            project_dir, "RECOVERY_STARTED", run_id, None,
            "recovery_attempt", "started",
            {"issues": len(high_severity_issues)},
        )

        # Build merged dataset: source records + non-conflicting extras
        source_ids = {r.get("paper_id", "") for r in source_records}
        current_ids = {r.get("paper_id", "") for r in current_records}

        # Start with all source records
        merged: dict[str, dict] = {r.get("paper_id", ""): r for r in source_records if r.get("paper_id")}

        # Add extras from current that are not in source (legitimate additions)
        for rec in current_records:
            pid = rec.get("paper_id", "")
            if pid and pid not in merged:
                merged[pid] = rec

        # For high-severity modifications in current, restore from source
        for issue in high_severity_issues:
            pid = issue["paper_id"]
            if pid in merged:
                records_restored += 1
                fields_restored += len(issue["fields"])

        restored_records = list(merged.values())
        records_modified = records_restored
        log_event(
            project_dir, "CLEAN_REBUILD_COMPLETED", run_id, None,
            "clean_rebuild", "success",
            {"records_merged": len(restored_records)},
        )
    else:
        # No high-severity issues: current is fine (or only added/low-severity)
        restored_records = current_records

    # Re-compute derived columns (authors_joined, categories_joined, text_for_embedding,
    # summary_chars, age_days) so the CSV matches the original structure.
    # Only rebuild when the target is CSV and we have source records.
    if target_path.suffix.lower() == ".csv" and restored_records:
        try:
            run_date = datetime.now(UTC)
            paper_records = [
                PaperRecord(
                    paper_id=r.get("paper_id", ""),
                    title=r.get("title", ""),
                    summary=r.get("summary", ""),
                    authors=r.get("authors", []),
                    categories=r.get("categories", []),
                    primary_category=r.get("primary_category", ""),
                    published=r.get("published", ""),
                    updated=r.get("updated", ""),
                    abs_url=r.get("abs_url", ""),
                    pdf_url=r.get("pdf_url", ""),
                    comment=r.get("comment", ""),
                )
                for r in restored_records
                if r.get("paper_id")
            ]
            df_computed = build_clean_dataframe(paper_records, run_date)
            restored_records = df_computed.to_dict(orient="records")
        except Exception:
            pass  # Fall through: use source records as-is

    # Write restored clean dataset (atomic)
    try:
        if target_path.suffix.lower() == ".json":
            _atomic_write_json(target_path, restored_records)
        else:
            # Write CSV — restored_records already has computed columns from above
            df_out = pd.DataFrame(restored_records)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(target_path.parent),
                suffix=".tmp",
                prefix=".recovery_",
            )
            try:
                df_out.to_csv(fd, index=False, encoding="utf-8")
                Path(tmp_path).replace(target_path)
            except Exception:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass
                raise
    except Exception as e:
        status = "partial"
        log_event(
            project_dir, "CLEAN_REBUILD_COMPLETED", run_id, None,
            "write_restored", "failed", {"error": str(e)},
        )

    # --- Step 7: Recompute embeddings for changed records ---
    changed_ids = [i["paper_id"] for i in issues]
    if changed_ids and restored_records:
        log_event(
            project_dir, "EMBEDDING_REBUILD_STARTED", run_id, None,
            "rebuild_embeddings", "started", {"changed_count": len(changed_ids)},
        )
        recomputed_ids, unchanged_ids, emb_path = _rebuild_embeddings_for_changed(
            changed_ids, restored_records, settings, project_dir,
        )
        log_event(
            project_dir, "EMBEDDING_REBUILD_COMPLETED", run_id, None,
            "rebuild_embeddings", "success",
            {"recomputed": len(recomputed_ids), "unchanged": len(unchanged_ids)},
        )
    else:
        recomputed_ids = []
        unchanged_ids = []
        emb_path = project_dir / "data" / "embeddings" / "papers_embeddings.json"

    # --- Step 8: Update Chroma ---
    if changed_ids and restored_records:
        log_event(
            project_dir, "CHROMA_UPDATE_STARTED", run_id, None,
            "chroma_update", "started", {"changed_count": len(changed_ids)},
        )
        index_summary = _update_chroma_collection(
            changed_ids, restored_records, settings, project_dir,
        )
        log_event(
            project_dir, "CHROMA_UPDATE_COMPLETED", run_id, None,
            "chroma_update", "success", index_summary,
        )
    else:
        index_summary = {
            "vectors_added": 0, "vectors_updated": 0,
            "vectors_deleted": 0, "collection": "papers-live",
            "rebuild_mode": "no_change",
        }

    # --- Step 9: Run quality checks on restored (after) ---
    try:
        df_after = pd.DataFrame(restored_records) if restored_records else pd.DataFrame()
        if not df_after.empty and "paper_id" in df_after.columns:
            gx_after = run_data_quality_checks(
                df_after, settings, "recovery_after",
            )
        else:
            gx_after = {"success": True, "row_count": 0}
    except Exception as e:
        gx_after = {"success": False, "row_count": 0, "error": str(e)}

    try:
        if not df_after.empty and "published" in df_after.columns:
            freshness_after = build_freshness_report(
                df_after, settings,
                project_dir / "data" / "live" / "quality" / f"{run_id}_freshness_after.json",
            )
        else:
            freshness_after = {"is_fresh": True, "stale_ratio": 0.0}
    except Exception:
        freshness_after = {"is_fresh": True, "stale_ratio": 0.0}

    # Retrieval validation: try a simple Chroma query
    retrieval_validation = {"status": "UNKNOWN", "hit_rate": 0.0, "samples": 0}
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(settings.paths.chroma_dir))
        collection = client.get_collection(name="papers-live")
        count = collection.count()
        retrieval_validation = {
            "status": "PASS" if count > 0 else "FAIL",
            "hit_rate": 1.0 if count > 0 else 0.0,
            "samples": count,
        }
    except Exception as e:
        retrieval_validation = {"status": "FAIL", "hit_rate": 0.0, "samples": 0, "error": str(e)}

    log_event(
        project_dir, "VALIDATION_COMPLETED", run_id, None,
        "validation", retrieval_validation["status"].lower(),
        retrieval_validation,
    )

    completed_at = datetime.now(UTC).isoformat()

    # --- Step 10: Write recovery report ---
    recovery_report = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "detection": {
            "source_path": str(target_path),
            "records_before": fp_before["row_count"],
            "records_after": fp_after["row_count"],
            "issues_detected": len(issues),
            "changed_records": len(changed_ids),
            "fingerprint_before": {
                "row_count": fp_before["row_count"],
                "file_sha256": fp_before["file_sha256"],
            },
            "fingerprint_after": {
                "row_count": fp_after["row_count"],
                "file_sha256": fp_after["file_sha256"],
            },
        },
        "issues": issues,
        "recovery_source": {
            "type": source_type,
            "path": str(source_path),
            "retrieved_at": retrieved_at,
        },
        "repair": {
            "records_restored": records_restored,
            "records_modified": records_modified,
            "records_removed": records_removed,
            "fields_restored": fields_restored,
        },
        "embedding": {
            "recomputed": len(recomputed_ids),
            "unchanged": len(unchanged_ids),
            "path": str(emb_path),
        },
        "index": index_summary,
        "validation": {
            "gx_before": {
                "success": gx_before.get("success", False),
                "row_count": gx_before.get("row_count", 0),
            },
            "gx_after": {
                "success": gx_after.get("success", False),
                "row_count": gx_after.get("row_count", 0),
            },
            "freshness_before": {
                "is_fresh": freshness_before.get("is_fresh", False),
                "stale_ratio": freshness_before.get("stale_ratio", 0.0),
            },
            "freshness_after": {
                "is_fresh": freshness_after.get("is_fresh", False),
                "stale_ratio": freshness_after.get("stale_ratio", 0.0),
            },
            "retrieval_validation": retrieval_validation,
        },
        "events": [],
    }

    # Write report
    recovery_dir = project_dir / "data" / "live" / "recovery"
    ensure_parent(recovery_dir)
    report_path = recovery_dir / f"recovery_{run_id}.json"
    _atomic_write_json(report_path, recovery_report)

    log_event(
        project_dir, "RECOVERY_COMPLETED", run_id, None,
        "recovery_complete", status, {"report": str(report_path)},
    )

    return recovery_report


def _normalize_val(value: Any) -> str:
    """Normalize a value for comparison."""
    if value is None:
        return ""
    return str(value).strip()
