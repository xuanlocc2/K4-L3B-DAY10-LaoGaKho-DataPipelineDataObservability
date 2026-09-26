from __future__ import annotations

from core.config import Settings, load_settings
from core.utils import now_utc, write_csv, write_dataframe_json
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import build_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records, load_raw_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.index import LocalEmbeddingIndex


def run_phase1_pipeline(settings: Settings) -> dict[str, object]:
    """Run ingest → clean → index → test set → evaluation → quality/reporting."""
    run_time = now_utc()

    if settings.refresh_source or not settings.paths.raw_records_json.exists():
        records = fetch_source_records(settings)
    else:
        records = load_raw_records(settings.paths.raw_records_json)
    if not records:
        raise RuntimeError("The source returned no valid paper records.")

    clean_df = build_clean_dataframe(records, run_time)
    if clean_df.empty:
        raise RuntimeError("Cleaning removed every source record.")
    write_csv(clean_df, settings.paths.clean_csv)
    write_dataframe_json(clean_df, settings.paths.clean_json)

    index = LocalEmbeddingIndex.build(
        clean_df,
        settings=settings,
        embeddings_output_path=settings.paths.embeddings_json,
    )
    if settings.refresh_test_set or not settings.paths.eval_testset.exists():
        build_test_set(clean_df, settings.paths.eval_testset)

    evaluation = evaluate_pipeline(
        settings=settings,
        index=index,
        test_set_path=settings.paths.eval_testset,
        metrics_output_path=settings.paths.baseline_metrics,
        answers_output_path=settings.paths.baseline_answers,
    )
    quality = run_data_quality_checks(clean_df, settings, "baseline")
    freshness = build_freshness_report(clean_df, settings, settings.paths.freshness_report)
    source_summary = {
        "source": settings.source_api,
        "query": settings.source_query,
        "filter": settings.source_filter,
        "records": len(clean_df),
        "run_at": run_time.isoformat(),
    }
    generate_phase1_report(
        settings.paths.baseline_report,
        source_summary=source_summary,
        metrics=evaluation.summary,
        quality=quality,
        freshness=freshness,
    )

    print(
        "Baseline complete: "
        f"records={len(clean_df)}, "
        f"retrieval_hit_rate={evaluation.summary['retrieval_hit_rate']:.3f}, "
        f"mean_token_f1={evaluation.summary['mean_token_f1']:.3f}"
    )
    return {
        "records": len(clean_df),
        "metrics": evaluation.summary,
        "quality": quality,
        "freshness": freshness,
        "report_path": settings.paths.baseline_report,
    }


def main() -> None:
    """CLI entrypoint for the baseline pipeline."""
    run_phase1_pipeline(load_settings())
