from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.utils import ensure_parent, write_text


def generate_phase1_report(
    report_path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
) -> None:
    """Generate markdown report for baseline phase."""
    ensure_parent(report_path)
    
    lines = [
        "# Phase 1: Baseline Pipeline Report",
        "",
        f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Source Summary",
        "",
        f"- **Records fetched:** {source_summary.get('records_fetched', 'N/A')}",
        f"- **API used:** {source_summary.get('api', 'N/A')}",
        f"- **Query:** {source_summary.get('query', 'N/A')}",
        f"- **Rows in clean dataset:** {source_summary.get('clean_rows', 'N/A')}",
        "",
        "## Retrieval & Evaluation Metrics",
        "",
    ]
    
    if metrics:
        lines.extend([
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Samples | {metrics.get('samples', 'N/A')} |",
            f"| Retrieval Hit Rate | {metrics.get('retrieval_hit_rate', 0.0):.2%} |",
            f"| Mean Token F1 | {metrics.get('mean_token_f1', 0.0):.4f} |",
            f"| Judge Accuracy | {metrics.get('judge_accuracy', 0.0):.2%} |",
            f"| Mean Judge Score | {metrics.get('mean_judge_score', 0.0):.2f} |",
            "",
        ])
        
        if "ragas" in metrics and not metrics["ragas"].get("skipped"):
            ragas = metrics["ragas"]
            lines.extend([
                "### RAGAS Metrics",
                "",
                f"- **Answer Relevancy:** {ragas.get('answer_relevancy', 'N/A')}",
                f"- **Context Precision:** {ragas.get('context_precision', 'N/A')}",
                f"- **Context Recall:** {ragas.get('context_recall', 'N/A')}",
                f"- **Faithfulness:** {ragas.get('faithfulness', 'N/A')}",
                "",
            ])
    else:
        lines.append("*No metrics available.*\n")
    
    lines.extend([
        "## Data Quality Status",
        "",
    ])
    
    if quality:
        gx_status = "PASS" if quality.get("success") else "FAIL"
        lines.extend([
            f"- **GX Status:** {gx_status}",
            f"- **GX Available:** {quality.get('gx_available', False)}",
            f"- **Validation Time:** {quality.get('validation_run_time', 0.0):.3f}s",
            f"- **Row Count:** {quality.get('statistics', {}).get('row_count', 0)}",
            f"- **Null paper_ids:** {quality.get('statistics', {}).get('null_paper_ids', 0)}",
            f"- **Duplicate paper_ids:** {quality.get('statistics', {}).get('duplicate_paper_ids', 0)}",
            "",
        ])
        
        if quality.get("failed_expectations"):
            lines.append("**Failed Expectations:**")
            for exp in quality["failed_expectations"]:
                lines.append(f"  - {exp}")
            lines.append("")
    else:
        lines.append("*No quality data available.*\n")
    
    lines.extend([
        "## Freshness Status",
        "",
    ])
    
    if freshness:
        fresh_status = "PASS" if freshness.get("is_fresh") else "FAIL"
        lines.extend([
            f"- **Status:** {fresh_status}",
            f"- **Threshold:** {freshness.get('threshold_days', 180)} days",
            f"- **Stale Ratio:** {freshness.get('stale_ratio', 0.0):.2%}",
            f"- **Stale Rows:** {freshness.get('stale_rows', 0)} / {freshness.get('total_rows', 0)}",
            f"- **Latest Published:** {freshness.get('latest_published', 'N/A')}",
            f"- **Oldest Published:** {freshness.get('oldest_published', 'N/A')}",
            "",
        ])
    else:
        lines.append("*No freshness data available.*\n")
    
    write_text(report_path, "\n".join(lines))


def generate_corruption_report(
    report_path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    baseline_quality: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
) -> None:
    """Generate markdown comparison report for baseline/corrupted/repaired."""
    ensure_parent(report_path)
    
    timestamp = datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    lines = [
        "# Corruption & Repair Experiment Report",
        "",
        f"**Generated:** {timestamp}",
        "",
        "## Metrics Comparison",
        "",
        "| Metric | Baseline | Corrupted | Repaired |",
        "|--------|----------|-----------|----------|",
    ]
    
    def _get(m: dict, key: str, default: str = "N/A") -> str:
        val = m.get(key, default)
        if isinstance(val, float):
            return f"{val:.4f}" if key != "retrieval_hit_rate" and key != "judge_accuracy" else f"{val:.2%}"
        return str(val)
    
    for key, label in [
        ("samples", "Samples"),
        ("retrieval_hit_rate", "Retrieval Hit Rate"),
        ("mean_token_f1", "Mean Token F1"),
        ("judge_accuracy", "Judge Accuracy"),
        ("mean_judge_score", "Mean Judge Score"),
    ]:
        lines.append(
            f"| {label} | {_get(baseline_metrics, key)} | {_get(corrupted_metrics, key)} | {_get(repaired_metrics, key)} |"
        )
    
    lines.extend([
        "",
        "## Data Quality",
        "",
        "| Check | Baseline | Corrupted | Repaired |",
        "|-------|----------|-----------|----------|",
    ])
    
    def _gx_status(q: dict) -> str:
        if not q:
            return "N/A"
        return "PASS" if q.get("success") else "FAIL"
    
    def _gx_available(q: dict) -> str:
        if not q:
            return "N/A"
        return "Yes" if q.get("gx_available") else "No"
    
    def _row_count(q: dict) -> str:
        if not q:
            return "N/A"
        return str(q.get("statistics", {}).get("row_count", "N/A"))
    
    lines.extend([
        f"| GX Status | {_gx_status(baseline_quality)} | {_gx_status(corrupted_quality)} | {_gx_status(repaired_quality)} |",
        f"| GX Executed | {_gx_available(baseline_quality)} | {_gx_available(corrupted_quality)} | {_gx_available(repaired_quality)} |",
        f"| Row Count | {_row_count(baseline_quality)} | {_row_count(corrupted_quality)} | {_row_count(repaired_quality)} |",
        "",
        "## Freshness",
        "",
        "| Metric | Corrupted | Repaired |",
        "|--------|-----------|----------|",
    ])
    
    def _fresh(q: dict) -> str:
        if not q:
            return "N/A"
        return "PASS" if q.get("is_fresh") else "FAIL"
    
    def _stale_ratio(q: dict) -> str:
        if not q:
            return "N/A"
        return f"{q.get('stale_ratio', 0.0):.2%}"
    
    lines.extend([
        f"| Status | {_fresh(corrupted_freshness)} | {_fresh(repaired_freshness)} |",
        f"| Stale Ratio | {_stale_ratio(corrupted_freshness)} | {_stale_ratio(repaired_freshness)} |",
        f"| Stale Rows | {corrupted_freshness.get('stale_rows', 'N/A') if corrupted_freshness else 'N/A'} | {repaired_freshness.get('stale_rows', 'N/A') if repaired_freshness else 'N/A'} |",
        "",
        "## Dataset Size",
        "",
        f"- **Baseline:** {baseline_metrics.get('samples', 'N/A')} papers",
        f"- **Corrupted:** {corrupted_metrics.get('samples', 'N/A')} papers",
        f"- **Repaired:** {repaired_metrics.get('samples', 'N/A')} papers",
        "",
        f"**Timestamp:** {timestamp}",
    ])
    
    write_text(report_path, "\n".join(lines))
