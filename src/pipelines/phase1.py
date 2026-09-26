from __future__ import annotations

from typing import Any

from core.config import Settings, load_settings
from core.utils import now_utc, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import build_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.index import LocalEmbeddingIndex


def run_phase1_pipeline(settings: Settings) -> dict[str, Any]:
    """Run ingestion, cleaning, indexing, benchmark evaluation, and observability."""
    records = fetch_source_records(settings)
    dataframe = build_clean_dataframe(records, now_utc())
    if dataframe.empty:
        raise ValueError("Phase 1 cannot continue because cleaning produced no valid papers.")

    write_csv(dataframe, settings.paths.clean_csv)
    write_json(settings.paths.clean_json, dataframe.to_dict(orient="records"))

    index = LocalEmbeddingIndex.build(dataframe, settings)
    build_test_set(dataframe, settings.paths.eval_testset)
    evaluation = evaluate_pipeline(
        settings,
        index,
        settings.paths.eval_testset,
        settings.paths.baseline_metrics,
        settings.paths.baseline_answers,
    )

    quality = run_data_quality_checks(dataframe, settings, "baseline")
    freshness = build_freshness_report(dataframe, settings, settings.paths.freshness_report)
    source_summary = {
        "source": settings.source_api,
        "query": settings.source_query,
        "records_ingested": len(records),
        "records_cleaned": len(dataframe),
    }
    generate_phase1_report(
        settings.paths.baseline_report,
        source_summary,
        evaluation.summary,
        quality,
        freshness,
    )

    return {
        "source": source_summary,
        "metrics": evaluation.summary,
        "quality": quality,
        "freshness": freshness,
    }


def main() -> None:
    result = run_phase1_pipeline(load_settings())
    metrics = result["metrics"]
    print(
        "Phase 1 complete: "
        f"{result['source']['records_cleaned']} clean papers, "
        f"hit rate={metrics['retrieval_hit_rate']:.3f}, "
        f"token F1={metrics['mean_token_f1']:.3f}"
    )
