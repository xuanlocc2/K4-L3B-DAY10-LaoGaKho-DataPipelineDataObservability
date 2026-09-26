from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.config import Settings, load_settings
from core.utils import now_utc, read_json, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_corruption_report
from retrieval.index import LocalEmbeddingIndex


def repair_from_raw_snapshot(settings: Settings) -> pd.DataFrame:
    """Rebuild clean data from the preserved raw records without calling Crossref."""
    records = load_raw_records(settings.paths.raw_records_json)
    repaired = build_clean_dataframe(records, now_utc())
    if repaired.empty:
        raise ValueError("Repair produced no valid papers from the raw snapshot.")

    write_csv(repaired, settings.paths.repaired_clean_csv)
    write_json(settings.paths.repaired_clean_json, repaired.to_dict(orient="records"))
    return repaired


def _evaluate_state(
    dataframe: pd.DataFrame,
    settings: Settings,
    embeddings_path: Path,
    metrics_path: Path,
    answers_path: Path,
) -> dict[str, Any]:
    index = LocalEmbeddingIndex.build(dataframe, settings, embeddings_output_path=embeddings_path)
    evaluation = evaluate_pipeline(
        settings,
        index,
        settings.paths.eval_testset,
        metrics_path,
        answers_path,
    )
    return evaluation.summary


def run_corruption_flow_pipeline(settings: Settings) -> dict[str, Any]:
    """Measure corruption impact, repair from raw data, and compare all three states."""
    required_inputs = (
        settings.paths.clean_json,
        settings.paths.eval_testset,
        settings.paths.baseline_metrics,
        settings.paths.raw_records_json,
    )
    missing_inputs = [str(path) for path in required_inputs if not path.is_file()]
    if missing_inputs:
        raise FileNotFoundError(
            "Phase 2 requires Phase 1 outputs and a raw snapshot; missing: "
            + ", ".join(missing_inputs)
        )

    baseline_metrics = read_json(settings.paths.baseline_metrics)
    baseline_dataframe = pd.read_json(settings.paths.clean_json)

    corrupted_dataframe = corrupt_clean_dataframe(baseline_dataframe, settings.paths.corruption_log)
    write_csv(corrupted_dataframe, settings.paths.corrupted_clean_csv)
    write_json(settings.paths.corrupted_clean_json, corrupted_dataframe.to_dict(orient="records"))
    corrupted_metrics = _evaluate_state(
        corrupted_dataframe,
        settings,
        settings.paths.corrupted_embeddings_json,
        settings.paths.corrupted_metrics,
        settings.paths.corrupted_answers,
    )
    corrupted_quality = run_data_quality_checks(corrupted_dataframe, settings, "corrupted")
    corrupted_freshness = build_freshness_report(
        corrupted_dataframe,
        settings,
        settings.paths.quality_dir / "corrupted_freshness_report.json",
    )

    repaired_dataframe = repair_from_raw_snapshot(settings)
    repaired_metrics = _evaluate_state(
        repaired_dataframe,
        settings,
        settings.paths.repaired_embeddings_json,
        settings.paths.repaired_metrics,
        settings.paths.repaired_answers,
    )
    repaired_quality = run_data_quality_checks(repaired_dataframe, settings, "repaired")
    repaired_freshness = build_freshness_report(
        repaired_dataframe,
        settings,
        settings.paths.quality_dir / "repaired_freshness_report.json",
    )

    generate_corruption_report(
        settings.paths.comparison_report,
        baseline_metrics,
        corrupted_metrics,
        repaired_metrics,
        corrupted_quality,
        repaired_quality,
        corrupted_freshness,
        repaired_freshness,
    )

    return {
        "baseline": baseline_metrics,
        "corrupted": corrupted_metrics,
        "repaired": repaired_metrics,
        "corrupted_quality": corrupted_quality,
        "repaired_quality": repaired_quality,
        "corrupted_freshness": corrupted_freshness,
        "repaired_freshness": repaired_freshness,
    }


def main() -> None:
    results = run_corruption_flow_pipeline(load_settings())
    metrics = ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy")
    print(f"{'Metric':<24} | {'Baseline':>10} | {'Corrupted':>10} | {'Repaired':>10}")
    print("-" * 65)
    for metric in metrics:
        values = [results[state].get(metric, 0.0) for state in ("baseline", "corrupted", "repaired")]
        print(f"{metric:<24} | {values[0]:>10.4f} | {values[1]:>10.4f} | {values[2]:>10.4f}")
