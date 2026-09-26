from __future__ import annotations

from pathlib import Path
from typing import Any

import great_expectations as gx
from great_expectations.expectations import (
    ExpectColumnValueLengthsToBeBetween,
    ExpectColumnValuesToBeUnique,
    ExpectColumnValuesToNotBeNull,
    ExpectTableRowCountToBeBetween,
)
import pandas as pd

from core.config import Settings
from core.utils import safe_slug, write_json


def evaluate_freshness_sla(
    df: pd.DataFrame,
    threshold_days: int,
    max_stale_ratio: float = 0.25,
) -> dict[str, Any]:
    """Evaluate whether the proportion of stale rows remains within the SLA."""
    total_rows = len(df)
    if "age_days" not in df.columns:
        return {
            "threshold_days": threshold_days,
            "max_stale_ratio": max_stale_ratio,
            "total_rows": total_rows,
            "stale_rows": total_rows,
            "stale_ratio": 1.0 if total_rows else 0.0,
            "is_fresh": False,
            "error": "Missing required column: age_days",
        }

    ages = pd.to_numeric(df["age_days"], errors="coerce")
    stale_mask = ages.gt(threshold_days) | ages.isna()
    stale_rows = int(stale_mask.sum())
    stale_ratio = stale_rows / total_rows if total_rows else 0.0
    return {
        "threshold_days": threshold_days,
        "max_stale_ratio": max_stale_ratio,
        "total_rows": total_rows,
        "stale_rows": stale_rows,
        "stale_ratio": stale_ratio,
        "is_fresh": total_rows > 0 and stale_ratio <= max_stale_ratio,
    }


def _quality_report_path(settings: Settings, stage: str) -> Path:
    normalized_stage = safe_slug(stage)
    if normalized_stage == "baseline":
        return settings.paths.baseline_quality_report
    if normalized_stage == "corrupted":
        return settings.paths.corrupted_quality_report
    return settings.paths.quality_dir / f"{normalized_stage}_quality_report.json"


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, stage: str) -> dict[str, Any]:
    """Run the required GX 1.x expectations and the freshness SLA gate."""
    validation_df = df.copy(deep=True)
    for column in ("paper_id", "title", "text_for_embedding"):
        if column in validation_df.columns:
            validation_df[column] = validation_df[column].replace(r"^\s*$", pd.NA, regex=True)

    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas(name="papers_source")
    data_asset = data_source.add_dataframe_asset(name="papers_asset")
    batch_def = data_asset.add_batch_definition_whole_dataframe("papers_batch")
    batch = batch_def.get_batch(batch_parameters={"dataframe": validation_df})

    expectations = [
        ExpectTableRowCountToBeBetween(min_value=5, max_value=5000),
        ExpectColumnValuesToNotBeNull(column="paper_id"),
        ExpectColumnValuesToNotBeNull(column="title"),
        ExpectColumnValuesToNotBeNull(column="text_for_embedding"),
        ExpectColumnValuesToBeUnique(column="paper_id"),
        ExpectColumnValueLengthsToBeBetween(column="summary", min_value=30),
    ]
    validation_results = [
        batch.validate(expectation, result_format="SUMMARY")
        for expectation in expectations
    ]
    gx_success = all(bool(result.success) for result in validation_results)
    freshness = evaluate_freshness_sla(
        df,
        threshold_days=settings.freshness_threshold_days,
        max_stale_ratio=0.25,
    )
    payload = {
        "stage": stage,
        "success": gx_success and freshness["is_fresh"],
        "row_count": len(df),
        "great_expectations": {
            "success": gx_success,
            "expectation_count": len(validation_results),
            "results": [result.to_json_dict() for result in validation_results],
        },
        "freshness": freshness,
    }
    write_json(_quality_report_path(settings, stage), payload)
    return payload


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path) -> dict[str, Any]:
    """Build and persist a detailed freshness report for a dataframe."""
    freshness = evaluate_freshness_sla(
        df,
        threshold_days=settings.freshness_threshold_days,
        max_stale_ratio=0.25,
    )
    if "published" in df.columns:
        published = pd.to_datetime(df["published"], errors="coerce", utc=True).dropna()
    else:
        published = pd.Series([], dtype="datetime64[ns, UTC]")
    payload = {
        **freshness,
        "latest_published": published.max().strftime("%Y-%m-%d") if not published.empty else None,
        "oldest_published": published.min().strftime("%Y-%m-%d") if not published.empty else None,
    }
    write_json(Path(report_path), payload)
    return payload
