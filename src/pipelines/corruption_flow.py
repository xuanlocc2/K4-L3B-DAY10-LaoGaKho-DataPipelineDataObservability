from __future__ import annotations

import pandas as pd

from core.config import Settings, load_settings
from core.utils import now_utc, read_json, write_csv, write_dataframe_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_corruption_report
from pipelines.phase1 import run_phase1_pipeline
from retrieval.index import LocalEmbeddingIndex


def _load_dataframe(path) -> pd.DataFrame:
    payload = read_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON record list in {path}.")
    return pd.DataFrame(payload)


def repair_from_raw_snapshot(settings: Settings) -> pd.DataFrame:
    """Rebuild repaired clean data exclusively from the trusted raw snapshot."""
    raw_records = load_raw_records(settings.paths.raw_records_json)
    repaired_df = build_clean_dataframe(raw_records, now_utc())
    if repaired_df.empty:
        raise RuntimeError("Repair produced no clean records from the raw snapshot.")
    write_csv(repaired_df, settings.paths.repaired_clean_csv)
    write_dataframe_json(repaired_df, settings.paths.repaired_clean_json)
    return repaired_df


def run_corruption_flow_pipeline(settings: Settings) -> dict[str, object]:
    """Measure corruption impact, repair from raw data, and compare all states."""
    baseline_inputs = (
        settings.paths.clean_json,
        settings.paths.baseline_metrics,
        settings.paths.eval_testset,
    )
    if not all(path.exists() for path in baseline_inputs):
        run_phase1_pipeline(settings)

    baseline_metrics = read_json(settings.paths.baseline_metrics)
    baseline_df = _load_dataframe(settings.paths.clean_json)

    corrupted_df = corrupt_clean_dataframe(baseline_df, settings.paths.corruption_log)
    write_csv(corrupted_df, settings.paths.corrupted_clean_csv)
    write_dataframe_json(corrupted_df, settings.paths.corrupted_clean_json)
    corrupted_index = LocalEmbeddingIndex.build(
        corrupted_df,
        settings=settings,
        embeddings_output_path=settings.paths.corrupted_embeddings_json,
    )
    corrupted_evaluation = evaluate_pipeline(
        settings=settings,
        index=corrupted_index,
        test_set_path=settings.paths.eval_testset,
        metrics_output_path=settings.paths.corrupted_metrics,
        answers_output_path=settings.paths.corrupted_answers,
    )
    corrupted_quality = run_data_quality_checks(corrupted_df, settings, "corrupted")
    corrupted_freshness = build_freshness_report(
        corrupted_df,
        settings,
        settings.paths.quality_dir / "corrupted_freshness_report.json",
    )

    repaired_df = repair_from_raw_snapshot(settings)
    repaired_index = LocalEmbeddingIndex.build(
        repaired_df,
        settings=settings,
        embeddings_output_path=settings.paths.repaired_embeddings_json,
    )
    repaired_evaluation = evaluate_pipeline(
        settings=settings,
        index=repaired_index,
        test_set_path=settings.paths.eval_testset,
        metrics_output_path=settings.paths.repaired_metrics,
        answers_output_path=settings.paths.repaired_answers,
    )
    repaired_quality = run_data_quality_checks(repaired_df, settings, "repaired")
    repaired_freshness = build_freshness_report(
        repaired_df,
        settings,
        settings.paths.quality_dir / "repaired_freshness_report.json",
    )

    generate_corruption_report(
        settings.paths.comparison_report,
        baseline_metrics=baseline_metrics,
        corrupted_metrics=corrupted_evaluation.summary,
        repaired_metrics=repaired_evaluation.summary,
        corrupted_quality=corrupted_quality,
        repaired_quality=repaired_quality,
        corrupted_freshness=corrupted_freshness,
        repaired_freshness=repaired_freshness,
    )
    comparison = {
        "baseline": baseline_metrics,
        "corrupted": corrupted_evaluation.summary,
        "repaired": repaired_evaluation.summary,
        "report_path": settings.paths.comparison_report,
    }
    print("\nBaseline vs Corrupted vs Repaired")
    print("Metric                 Baseline  Corrupted  Repaired")
    for metric in ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score"):
        print(
            f"{metric:<22} "
            f"{baseline_metrics[metric]:>8.3f} "
            f"{corrupted_evaluation.summary[metric]:>10.3f} "
            f"{repaired_evaluation.summary[metric]:>9.3f}"
        )
    return comparison


def main() -> None:
    """CLI entrypoint for the corruption and repair pipeline."""
    run_corruption_flow_pipeline(load_settings())
