from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from core.config import Settings, load_settings
from core.utils import ensure_parent, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_corruption_report
from retrieval.index import LocalEmbeddingIndex


def main() -> int:
    """Run corruption → evaluate → repair → compare flow.
    
    Steps:
    1. Load baseline metrics and clean dataset
    2. Create corrupted dataframe
    3. Save corrupted artifacts
    4. Rebuild index and evaluate on corrupted
    5. Run quality checks/freshness on corrupted
    6. Repair from raw records (re-clean)
    7. Evaluate repaired dataset
    8. Generate comparison report
    """
    settings = load_settings()
    
    run_date = datetime.now(UTC)
    
    ensure_parent(settings.paths.quality_dir)
    ensure_parent(settings.paths.comparison_report.parent)
    
    baseline_metrics = {}
    baseline_quality = {}
    try:
        import json

        if settings.paths.baseline_metrics.exists():
            baseline_metrics = json.loads(settings.paths.baseline_metrics.read_text())
        if settings.paths.baseline_quality_report.exists():
            baseline_quality = json.loads(settings.paths.baseline_quality_report.read_text())
    except Exception:
        pass
    
    clean_df = pd.read_csv(settings.paths.clean_csv) if settings.paths.clean_csv.exists() else None
    if clean_df is None or clean_df.empty:
        records = load_raw_records(settings.paths.raw_records_json)
        clean_df = build_clean_dataframe(records, run_date)
    
    corrupted_df = corrupt_clean_dataframe(
        clean_df.copy(),
        settings.paths.corruption_log,
    )
    
    ensure_parent(settings.paths.corrupted_clean_csv)
    ensure_parent(settings.paths.corrupted_clean_json)
    write_csv(corrupted_df, settings.paths.corrupted_clean_csv)
    write_json(settings.paths.corrupted_clean_json, corrupted_df.to_dict(orient="records"))
    
    corrupted_index = LocalEmbeddingIndex.build(
        df=corrupted_df,
        settings=settings,
        embeddings_output_path=settings.paths.corrupted_embeddings_json,
    )
    
    corrupted_metrics_bundle = evaluate_pipeline(
        settings=settings,
        index=corrupted_index,
        test_set_path=settings.paths.eval_testset,
        metrics_output_path=settings.paths.corrupted_metrics,
        answers_output_path=settings.paths.corrupted_answers,
    )
    
    corrupted_quality = run_data_quality_checks(
        corrupted_df,
        settings,
        "corrupted",
    )
    
    corrupted_freshness = build_freshness_report(
        corrupted_df,
        settings,
        settings.paths.quality_dir / "corrupted_freshness_report.json",
    )
    
    records = load_raw_records(settings.paths.raw_records_json)
    repaired_df = build_clean_dataframe(records, run_date)
    
    ensure_parent(settings.paths.repaired_clean_csv)
    ensure_parent(settings.paths.repaired_clean_json)
    write_csv(repaired_df, settings.paths.repaired_clean_csv)
    write_json(settings.paths.repaired_clean_json, repaired_df.to_dict(orient="records"))
    
    repaired_index = LocalEmbeddingIndex.build(
        df=repaired_df,
        settings=settings,
        embeddings_output_path=settings.paths.repaired_embeddings_json,
    )
    
    repaired_metrics_bundle = evaluate_pipeline(
        settings=settings,
        index=repaired_index,
        test_set_path=settings.paths.eval_testset,
        metrics_output_path=settings.paths.repaired_metrics,
        answers_output_path=settings.paths.repaired_answers,
    )
    
    repaired_quality = run_data_quality_checks(
        repaired_df,
        settings,
        "repaired",
    )
    
    repaired_freshness = build_freshness_report(
        repaired_df,
        settings,
        settings.paths.quality_dir / "repaired_freshness_report.json",
    )
    
    generate_corruption_report(
        report_path=settings.paths.comparison_report,
        baseline_metrics=baseline_metrics,
        corrupted_metrics=corrupted_metrics_bundle.summary,
        repaired_metrics=repaired_metrics_bundle.summary,
        baseline_quality=baseline_quality,
        corrupted_quality=corrupted_quality,
        repaired_quality=repaired_quality,
        corrupted_freshness=corrupted_freshness,
        repaired_freshness=repaired_freshness,
    )
    
    print("Corruption & Repair flow completed successfully.")
    print(f"  - Baseline samples: {baseline_metrics.get('samples', 'N/A')}")
    print(f"  - Corrupted samples: {corrupted_metrics_bundle.summary.get('samples', 'N/A')}")
    print(f"  - Corrupted retrieval hit rate: {corrupted_metrics_bundle.summary.get('retrieval_hit_rate', 0.0):.2%}")
    print(f"  - Repaired samples: {repaired_metrics_bundle.summary.get('samples', 'N/A')}")
    print(f"  - Repaired retrieval hit rate: {repaired_metrics_bundle.summary.get('retrieval_hit_rate', 0.0):.2%}")
    print(f"  - Report: {settings.paths.comparison_report}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
