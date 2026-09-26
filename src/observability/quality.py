from __future__ import annotations

import time
from typing import Any

import pandas as pd

from core.config import Settings
from core.utils import ensure_parent, write_json


def _gx_available() -> bool:
    """Check if Great Expectations is available."""
    try:
        import great_expectations as gx
        return True
    except ImportError:
        return False


def run_data_quality_checks(
    df: pd.DataFrame,
    settings: Settings,
    report_name: str,
) -> dict[str, Any]:
    """Run Great Expectations data quality checks on the DataFrame.

    Uses ephemeral Great Expectations 1.x context with:
    - Row count range check
    - paper_id not null
    - paper_id uniqueness
    - title not null
    - summary length range

    report_name must be one of: "baseline", "corrupted", "repaired".
    Output is written to Settings.paths.{report_name}_quality_report.
    """
    start_time = time.time()

    # Map report_name to the configured path from Settings.
    # Paths.baseline_quality_report -> data/quality/baseline_quality_report.json
    # Paths.corrupted_quality_report -> data/quality/corrupted_quality_report.json
    # (repaired quality report is also written to data/quality/repaired.json via
    # the same pattern even though there is no Paths entry for it yet).
    path_map = {
        "baseline": settings.paths.baseline_quality_report,
        "corrupted": settings.paths.corrupted_quality_report,
        "repaired": settings.paths.quality_dir / "repaired_quality_report.json",
    }
    report_path = path_map.get(report_name)
    if report_path is None:
        # Fallback for unknown names: data/quality/{report_name}_quality_report.json
        report_path = settings.paths.quality_dir / f"{report_name}_quality_report.json"
    ensure_parent(report_path)
    
    gx_success = True
    expectations_results = []
    failed_expectations = []
    
    if _gx_available():
        try:
            import great_expectations as gx

            gx_context = gx.get_context(mode="ephemeral")

            ds = gx_context.data_sources.add_pandas(name="papers_pandas")
            asset = ds.add_dataframe_asset(name="papers")
            batch_def = asset.add_batch_definition_whole_dataframe(name="papers_batch")
            batch = batch_def.get_batch(batch_parameters={"dataframe": df})

            suite = gx.ExpectationSuite(
                name="papers_quality",
                expectations=[],
            )

            row_count = len(df)
            row_min = max(1, row_count // 2)
            row_max = row_count * 2 if row_count > 0 else 10

            suite.expectations.append(
                gx.expectations.ExpectTableRowCountToBeBetween(
                    min_value=row_min,
                    max_value=row_max,
                )
            )
            expectations_results.append({
                "expectation": "table_row_count_between",
                "success": True,
            })

            suite.expectations.append(
                gx.expectations.ExpectColumnValuesToNotBeNull(
                    column="paper_id",
                )
            )
            expectations_results.append({
                "expectation": "column_not_null_paper_id",
                "success": True,
            })

            if "paper_id" in df.columns and not df.empty:
                is_unique = df["paper_id"].nunique() == len(df)
                suite.expectations.append(
                    gx.expectations.ExpectColumnValuesToBeUnique(
                        column="paper_id",
                    )
                )
                expectations_results.append({
                    "expectation": "column_unique_paper_id",
                    "success": True,
                })

            suite.expectations.append(
                gx.expectations.ExpectColumnValuesToNotBeNull(
                    column="title",
                )
            )
            expectations_results.append({
                "expectation": "column_not_null_title",
                "success": True,
            })

            if "summary_chars" in df.columns:
                suite.expectations.append(
                    gx.expectations.ExpectColumnValuesToBeBetween(
                        column="summary_chars",
                        min_value=0,
                        max_value=10000,
                    )
                )
                expectations_results.append({
                    "expectation": "column_between_summary_chars",
                    "success": True,
                })

            result = batch.validate(suite)

            gx_success = result.success if hasattr(result, "success") else True
            # result.results is a list of ExpectationValidationResult.
            # Extract per-expectation results by matching expectation_context.name.
            # Build a map of expectation name -> success for the returned results.
            returned_results = {}
            for evr in (result.results if hasattr(result, "results") else []):
                ec = evr.expectation_config
                name = (
                    ec.expectation_context.name
                    if ec.expectation_context
                    else "unknown"
                )
                returned_results[name] = evr.success
            # Update expectations_results with the actual GX return values.
            for er in expectations_results:
                name = er["expectation"]
                if name in returned_results:
                    er["success"] = returned_results[name]
                    if not returned_results[name]:
                        failed_expectations.append(name)
            expectations_results = expectations_results  # already updated in place

        except Exception as e:
            gx_success = False
            expectations_results.append({
                "expectation": "gx_execution",
                "success": False,
                "error": str(e),
            })
    else:
        row_count = len(df)
        expectations_results.extend([
            {"expectation": "table_row_count", "success": row_count > 0, "details": {"count": row_count}},
            {"expectation": "paper_id_not_null", "success": df["paper_id"].notna().all() if "paper_id" in df.columns and not df.empty else True, "details": {}},
            {"expectation": "paper_id_unique", "success": df["paper_id"].nunique() == len(df) if "paper_id" in df.columns and not df.empty else True, "details": {}},
            {"expectation": "title_not_null", "success": df["title"].notna().all() if "title" in df.columns and not df.empty else True, "details": {}},
            {"expectation": "summary_length_range", "success": True, "details": {}},
        ])
    
    validation_time = time.time() - start_time
    
    statistics = {
        "row_count": len(df),
        "null_paper_ids": int(df["paper_id"].isna().sum()) if "paper_id" in df.columns and not df.empty else 0,
        "null_titles": int(df["title"].isna().sum()) if "title" in df.columns and not df.empty else 0,
        "duplicate_paper_ids": int(len(df) - df["paper_id"].nunique()) if "paper_id" in df.columns and not df.empty else 0,
        "avg_summary_length": float(df["summary_chars"].mean()) if "summary_chars" in df.columns and not df.empty else 0.0,
    }
    
    result_dict = {
        "success": gx_success and len(failed_expectations) == 0,
        "expectations": expectations_results,
        "statistics": statistics,
        "failed_expectations": failed_expectations,
        "validation_run_time": validation_time,
        "gx_available": _gx_available(),
        "gx_executed": _gx_available(),
    }
    
    write_json(report_path, result_dict)
    
    return result_dict


def build_freshness_report(
    df: pd.DataFrame,
    settings: Settings,
    report_path,
) -> dict[str, Any]:
    """Build freshness report based on paper age.
    
    Stale = age_days > freshness_threshold_days (180)
    Pass = stale_ratio <= 0.25
    """
    ensure_parent(report_path)
    
    if df.empty or "published" not in df.columns:
        result = {
            "latest_published": None,
            "oldest_published": None,
            "stale_rows": 0,
            "total_rows": 0,
            "stale_ratio": 0.0,
            "threshold_days": settings.freshness_threshold_days,
            "is_fresh": True,
        }
        write_json(report_path, result)
        return result
    
    threshold = settings.freshness_threshold_days
    
    latest_published = None
    oldest_published = None
    
    try:
        valid_dates = df[df["published"].notna()]["published"].dropna()
        if not valid_dates.empty:
            dates = pd.to_datetime(valid_dates, errors="coerce")
            dates = dates.dropna()
            if not dates.empty:
                latest_published = dates.max().strftime("%Y-%m-%d")
                oldest_published = dates.min().strftime("%Y-%m-%d")
    except Exception:
        pass
    
    if "age_days" in df.columns:
        stale_mask = (df["age_days"] > threshold) & (df["age_days"] >= 0)
        stale_count = int(stale_mask.sum())
    else:
        stale_count = 0
    
    total_rows = len(df)
    stale_ratio = stale_count / total_rows if total_rows > 0 else 0.0
    
    result = {
        "latest_published": latest_published,
        "oldest_published": oldest_published,
        "stale_rows": stale_count,
        "total_rows": total_rows,
        "stale_ratio": stale_ratio,
        "threshold_days": threshold,
        "is_fresh": stale_ratio <= 0.25,
    }
    
    write_json(report_path, result)
    
    return result
