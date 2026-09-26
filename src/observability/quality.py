from __future__ import annotations

from pathlib import Path
from typing import Any

import great_expectations as gx
import pandas as pd

from core.config import Settings
from core.utils import write_json


def evaluate_freshness_sla(df: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    """Evaluate whether stale records stay within the configured freshness SLA."""
    total_rows = len(df)
    max_stale_ratio = 0.25

    if "age_days" in df.columns:
        ages = pd.to_numeric(df["age_days"], errors="coerce")
        invalid_age_rows = int(ages.isna().sum())
        stale_rows = int((ages > settings.freshness_threshold_days).sum())
    else:
        invalid_age_rows = total_rows
        stale_rows = 0

    stale_ratio = stale_rows / total_rows if total_rows else 0.0
    is_fresh = bool(
        total_rows > 0
        and invalid_age_rows == 0
        and stale_ratio <= max_stale_ratio
    )
    return {
        "threshold_days": settings.freshness_threshold_days,
        "max_stale_ratio": max_stale_ratio,
        "stale_rows": stale_rows,
        "invalid_age_rows": invalid_age_rows,
        "total_rows": total_rows,
        "stale_ratio": stale_ratio,
        "is_fresh": is_fresh,
    }


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, stage: str) -> dict[str, Any]:
    """Validate the dataframe with Great Expectations and the freshness SLA."""
    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas(name="papers_source")
    data_asset = data_source.add_dataframe_asset(name="papers_asset")
    batch_definition = data_asset.add_batch_definition_whole_dataframe("papers_batch")
    batch = batch_definition.get_batch(batch_parameters={"dataframe": df})

    suite = gx.ExpectationSuite(name=f"{stage}_data_quality")
    expectations = [
        gx.expectations.ExpectTableRowCountToBeBetween(min_value=5, max_value=5000),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="paper_id"),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="title"),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="text_for_embedding"),
        gx.expectations.ExpectColumnValuesToBeUnique(column="paper_id"),
        gx.expectations.ExpectColumnValueLengthsToBeBetween(column="summary", min_value=30),
    ]
    for expectation in expectations:
        suite.add_expectation(expectation)

    gx_result = batch.validate(suite).to_json_dict()
    freshness = evaluate_freshness_sla(df, settings)
    result = {
        "stage": stage,
        "success": bool(gx_result["success"] and freshness["is_fresh"]),
        "expectations_success": bool(gx_result["success"]),
        "freshness": freshness,
        "great_expectations": gx_result,
    }

    report_paths = {
        "baseline": settings.paths.baseline_quality_report,
        "corrupted": settings.paths.corrupted_quality_report,
    }
    report_path = report_paths.get(stage, settings.paths.quality_dir / f"{stage}_quality_report.json")
    write_json(report_path, result)
    return result


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path: Path) -> dict[str, Any]:
    """Write freshness counts and publication-date bounds to a JSON report."""
    published = pd.to_datetime(df["published"], errors="coerce", utc=True) if "published" in df.columns else pd.Series(dtype="datetime64[ns, UTC]")
    valid_dates = published.dropna()
    freshness = evaluate_freshness_sla(df, settings)
    report = {
        **freshness,
        "latest_published": valid_dates.max().date().isoformat() if not valid_dates.empty else None,
        "oldest_published": valid_dates.min().date().isoformat() if not valid_dates.empty else None,
    }
    write_json(report_path, report)
    return report
