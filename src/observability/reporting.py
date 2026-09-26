from __future__ import annotations

from pathlib import Path
from typing import Any

from core.utils import write_text


def generate_phase1_report(
    report_path: Path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
) -> None:
    """Write the baseline source, evaluation, quality, and freshness results."""
    def format_metric(name: str, digits: int = 4) -> str:
        value = metrics.get(name)
        return f"{value:.{digits}f}" if isinstance(value, (int, float)) else "N/A"

    quality_status = "PASS" if quality.get("success") else "FAIL"
    expectation_status = "PASS" if quality.get("expectations_success") else "FAIL"
    freshness_status = "FRESH" if freshness.get("is_fresh") else "STALE"
    lines = [
        "# Phase 1: Baseline Pipeline Report",
        "",
        "## Data Source",
        f"- Source: {source_summary.get('source', 'N/A')}",
        f"- Query: {source_summary.get('query', 'N/A')}",
        f"- Records ingested: {source_summary.get('records_ingested', 0)}",
        f"- Records cleaned: {source_summary.get('records_cleaned', 0)}",
        "",
        "## Baseline Evaluation",
        "| Metric | Result |",
        "|---|---:|",
        f"| Evaluation samples | {metrics.get('samples', 0)} |",
        f"| Retrieval Hit Rate | {format_metric('retrieval_hit_rate')} |",
        f"| Mean Token F1 | {format_metric('mean_token_f1')} |",
        f"| Judge Accuracy | {format_metric('judge_accuracy')} |",
        f"| Mean Judge Score | {format_metric('mean_judge_score')} |",
        "",
        "## Data Quality",
        f"- Overall Quality Gate: **{quality_status}**",
        f"- Great Expectations: **{expectation_status}**",
        "",
        "## Freshness",
        f"- Status: **{freshness_status}**",
        f"- Latest publication date: {freshness.get('latest_published', 'N/A')}",
        f"- Oldest publication date: {freshness.get('oldest_published', 'N/A')}",
        f"- Stale rows: {freshness.get('stale_rows', 0)} / {freshness.get('total_rows', 0)}",
        f"- Stale ratio: {float(freshness.get('stale_ratio', 0.0)):.2%}",
        "",
        "## Artifacts",
        f"- Clean data: `{source_summary.get('clean_csv', 'data/clean/papers_clean.csv')}`",
        "- Benchmark: `data/eval/test_set.json`",
        "- Metrics: `data/results/baseline_metrics.json`",
        "- Quality: `data/quality/baseline_quality_report.json`",
        "",
    ]
    write_text(report_path, "\n".join(lines))


def generate_corruption_report(
    report_path: Path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
) -> None:
    """Write a three-state metric comparison with quality and freshness results."""
    metric_names = (
        ("retrieval_hit_rate", "Retrieval Hit Rate"),
        ("mean_token_f1", "Mean Token F1"),
        ("judge_accuracy", "Judge Accuracy"),
        ("mean_judge_score", "Mean Judge Score"),
    )

    def format_metric(metrics: dict[str, Any], name: str) -> str:
        value = metrics.get(name)
        return f"{value:.4f}" if isinstance(value, (int, float)) else "N/A"

    corrupted_quality_status = "PASS" if corrupted_quality.get("success") else "FAIL"
    repaired_quality_status = "PASS" if repaired_quality.get("success") else "FAIL"
    corrupted_freshness_status = "FRESH" if corrupted_freshness.get("is_fresh") else "STALE"
    repaired_freshness_status = "FRESH" if repaired_freshness.get("is_fresh") else "STALE"

    lines = [
        "# Data Corruption and Repair Report",
        "",
        "## RAG Evaluation",
        "| Metric | Baseline | Corrupted | Repaired |",
        "|---|---:|---:|---:|",
    ]
    for key, label in metric_names:
        lines.append(
            f"| {label} | {format_metric(baseline_metrics, key)} "
            f"| {format_metric(corrupted_metrics, key)} | {format_metric(repaired_metrics, key)} |"
        )

    lines.extend(
        [
            "",
            "## Data Quality Gate",
            "| State | Gate | Great Expectations | Freshness |",
            "|---|---|---|---|",
            f"| Corrupted | {corrupted_quality_status} | "
            f"{'PASS' if corrupted_quality.get('expectations_success') else 'FAIL'} | {corrupted_freshness_status} |",
            f"| Repaired | {repaired_quality_status} | "
            f"{'PASS' if repaired_quality.get('expectations_success') else 'FAIL'} | {repaired_freshness_status} |",
            "",
            "## Freshness Details",
            f"- Corrupted stale rows: {corrupted_freshness.get('stale_rows', 0)} / {corrupted_freshness.get('total_rows', 0)} "
            f"({float(corrupted_freshness.get('stale_ratio', 0.0)):.2%})",
            f"- Repaired stale rows: {repaired_freshness.get('stale_rows', 0)} / {repaired_freshness.get('total_rows', 0)} "
            f"({float(repaired_freshness.get('stale_ratio', 0.0)):.2%})",
            "",
            "## Interpretation",
            "Compare the corrupted metrics with baseline to observe impact, then compare repaired metrics "
            "with baseline to assess recovery. Values above are produced by the evaluation pipeline.",
            "",
        ]
    )
    write_text(report_path, "\n".join(lines))
