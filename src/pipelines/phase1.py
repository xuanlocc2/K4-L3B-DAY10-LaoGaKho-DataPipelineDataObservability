from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.config import Settings, load_settings
from core.utils import ensure_parent, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import build_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records, load_raw_records, parse_crossref_payload
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.index import LocalEmbeddingIndex
from retrieval.qa import answer_question


def main() -> int:
    """Run baseline pipeline end-to-end.
    
    Steps:
    1. Load settings
    2. Ingest raw records (from API or snapshot)
    3. Clean data
    4. Save clean CSV/JSON
    5. Run quality checks
    6. Build freshness report
    7. Build test set
    8. Build Chroma index
    9. Evaluate
    10. Generate report
    """
    settings = load_settings()
    
    run_date = datetime.now(UTC)
    
    ensure_parent(settings.paths.quality_dir)
    ensure_parent(settings.paths.baseline_report.parent)
    
    try:
        if settings.refresh_source:
            records = fetch_source_records(settings)
        else:
            if settings.paths.raw_records_json.exists():
                records = load_raw_records(settings.paths.raw_records_json)
            else:
                records = fetch_source_records(settings)
    except Exception as e:
        if settings.paths.raw_records_json.exists():
            records = load_raw_records(settings.paths.raw_records_json)
        else:
            raise RuntimeError(f"Failed to fetch records: {e}")
    
    source_summary = {
        "records_fetched": len(records),
        "api": settings.source_api,
        "query": settings.source_query,
        "clean_rows": 0,
    }
    
    df = build_clean_dataframe(records, run_date)
    
    source_summary["clean_rows"] = len(df)
    
    ensure_parent(settings.paths.clean_csv)
    ensure_parent(settings.paths.clean_json)
    write_csv(df, settings.paths.clean_csv)
    write_json(settings.paths.clean_json, df.to_dict(orient="records"))
    
    quality = run_data_quality_checks(df, settings, "baseline")
    
    freshness = build_freshness_report(df, settings, settings.paths.freshness_report)
    
    if settings.refresh_test_set or not settings.paths.eval_testset.exists():
        build_test_set(df, settings.paths.eval_testset)
    
    index = LocalEmbeddingIndex.build(
        df=df,
        settings=settings,
        embeddings_output_path=settings.paths.embeddings_json,
        collection_name="papers-live",
    )
    
    metrics_bundle = evaluate_pipeline(
        settings=settings,
        index=index,
        test_set_path=settings.paths.eval_testset,
        metrics_output_path=settings.paths.baseline_metrics,
        answers_output_path=settings.paths.baseline_answers,
    )
    
    generate_phase1_report(
        report_path=settings.paths.baseline_report,
        source_summary=source_summary,
        metrics=metrics_bundle.summary,
        quality=quality,
        freshness=freshness,
    )
    
    print(f"Phase 1 baseline pipeline completed successfully.")
    print(f"  - Records: {len(records)}")
    print(f"  - Clean rows: {len(df)}")
    print(f"  - Quality: {'PASS' if quality.get('success') else 'FAIL'}")
    print(f"  - Freshness: {'PASS' if freshness.get('is_fresh') else 'FAIL'}")
    print(f"  - Report: {settings.paths.baseline_report}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
