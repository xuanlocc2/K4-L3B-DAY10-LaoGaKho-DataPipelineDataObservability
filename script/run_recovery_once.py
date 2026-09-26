#!/usr/bin/env python3
"""One-shot recovery script: detect and recover from corruption in a clean dataset.

Usage:
    python script/run_recovery_once.py [--target data/clean/papers_clean.json]

This script runs detect_and_recover on the specified target file (or the default
data/clean/papers_clean.json) and prints a summary of the recovery report.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is on path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.config import load_settings
from live.config import LiveConfig
from live.incremental import generate_run_id
from live.recovery import detect_and_recover


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one-shot recovery on a clean dataset")
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help=(
            "Path to the clean dataset to recover. "
            "Defaults to data/clean/papers_clean.json. "
            "Use data/live/clean/<run_id>_clean.json for live targets."
        ),
    )
    args = parser.parse_args()

    settings = load_settings(PROJECT_ROOT)
    live_config = LiveConfig.from_env()

    if args.target:
        target_path = PROJECT_ROOT / args.target
    elif settings.live_recovery_target_file:
        target_path = Path(settings.live_recovery_target_file)
    else:
        target_path = settings.paths.clean_json

    run_id = generate_run_id()

    print(f"[Recovery] Starting recovery run: {run_id}")
    print(f"[Recovery] Target: {target_path}")
    print(f"[Recovery] Source: Crossref records or live raw snapshot")
    print()

    try:
        report = detect_and_recover(
            settings=settings,
            live_config=live_config,
            run_id=run_id,
            target_path=target_path,
        )
    except Exception as e:
        print(f"[Recovery] FAILED: {e}")
        return 1

    # Print summary
    report_path = PROJECT_ROOT / "data" / "live" / "recovery" / f"recovery_{run_id}.json"
    status = report.get("status", "unknown")

    print("=" * 60)
    print("RECOVERY SUMMARY")
    print("=" * 60)
    print(f"Run ID:           {run_id}")
    print(f"Status:           {status.upper()}")
    print(f"Started:          {report.get('started_at', 'N/A')}")
    print(f"Completed:        {report.get('completed_at', 'N/A')}")
    print()
    print("DETECTION:")
    det = report.get("detection", {})
    print(f"  Source path:    {det.get('source_path', 'N/A')}")
    print(f"  Records before: {det.get('records_before', 0)}")
    print(f"  Records after:  {det.get('records_after', 0)}")
    print(f"  Issues found:  {det.get('issues_detected', 0)}")
    print(f"  Changed recs:  {det.get('changed_records', 0)}")
    print()
    print("RECOVERY SOURCE:")
    src = report.get("recovery_source", {})
    print(f"  Type:          {src.get('type', 'N/A')}")
    print(f"  Path:          {src.get('path', 'N/A')}")
    print()
    print("REPAIR:")
    rep = report.get("repair", {})
    print(f"  Records restored: {rep.get('records_restored', 0)}")
    print(f"  Records modified: {rep.get('records_modified', 0)}")
    print(f"  Fields restored:  {rep.get('fields_restored', 0)}")
    print()
    print("EMBEDDINGS:")
    emb = report.get("embedding", {})
    print(f"  Recomputed:    {emb.get('recomputed', 0)}")
    print(f"  Unchanged:     {emb.get('unchanged', 0)}")
    print()
    print("CHROMA INDEX:")
    idx = report.get("index", {})
    print(f"  Vectors added:   {idx.get('vectors_added', 0)}")
    print(f"  Vectors updated: {idx.get('vectors_updated', 0)}")
    print(f"  Vectors deleted: {idx.get('vectors_deleted', 0)}")
    print(f"  Rebuild mode:    {idx.get('rebuild_mode', 'N/A')}")
    print()
    print("VALIDATION:")
    val = report.get("validation", {})
    gx_b = val.get("gx_before", {})
    gx_a = val.get("gx_after", {})
    fr_b = val.get("freshness_before", {})
    fr_a = val.get("freshness_after", {})
    rv = val.get("retrieval_validation", {})
    print(f"  GX before:      success={gx_b.get('success')}, rows={gx_b.get('row_count', 0)}")
    print(f"  GX after:       success={gx_a.get('success')}, rows={gx_a.get('row_count', 0)}")
    print(f"  Freshness before: is_fresh={fr_b.get('is_fresh')}, stale_ratio={fr_b.get('stale_ratio', 0.0):.2%}")
    print(f"  Freshness after:  is_fresh={fr_a.get('is_fresh')}, stale_ratio={fr_a.get('stale_ratio', 0.0):.2%}")
    print(f"  Retrieval:       status={rv.get('status', 'UNKNOWN')}, samples={rv.get('samples', 0)}")
    print()

    if report.get("issues"):
        print("ISSUES:")
        for issue in report["issues"]:
            print(f"  [{issue['severity'].upper()}] {issue['issue_type']}: paper_id={issue['paper_id']}")
            if issue.get("fields"):
                print(f"    Fields: {', '.join(issue['fields'])}")

    print()
    print(f"Full report: {report_path}")
    print("=" * 60)

    return 0 if status in {"success", "no_change"} else 1


if __name__ == "__main__":
    sys.exit(main())
