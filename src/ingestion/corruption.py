from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import write_json


_NOISE = " [CORRUPTED_NOISE: xqzv-000 ### unrelated-token]"


def _json_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _snapshot(row: pd.Series) -> dict[str, Any]:
    return {column: _json_value(value) for column, value in row.to_dict().items()}


def _rebuild_derived_columns(df: pd.DataFrame) -> None:
    """Keep embedding text and helper columns consistent with corrupted values."""
    if "authors_joined" not in df.columns:
        df["authors_joined"] = ""
    if "categories_joined" not in df.columns:
        df["categories_joined"] = ""
    df["summary"] = df["summary"].fillna("").astype(str)
    df["title"] = df["title"].fillna("").astype(str)
    df["published"] = df["published"].fillna("").astype(str)
    df["summary_chars"] = df["summary"].str.len().astype("int64")
    df["text_for_embedding"] = df.apply(
        lambda row: "\n".join(
            (
                f"Title: {row['title']}",
                f"Authors: {row['authors_joined']}",
                f"Published: {row['published']}",
                f"Categories: {row['categories_joined']}",
                f"Summary: {row['summary']}",
            )
        ),
        axis=1,
    )


def _event(name: str, changes: list[dict[str, Any]], description: str) -> dict[str, Any]:
    return {
        "type": name,
        "description": description,
        "affected_count": len(changes),
        "affected_paper_ids": [change["paper_id"] for change in changes],
        "changes": changes,
    }


def corrupt_clean_dataframe(df: pd.DataFrame, output_log_path) -> pd.DataFrame:
    """Apply six deterministic corruption scenarios and write an audit log.

    The input dataframe is not modified. Each logged change includes complete
    snapshots of the affected row before and after the scenario is applied.
    """
    required_columns = {"paper_id", "title", "summary", "published"}
    missing_columns = sorted(required_columns.difference(df.columns))
    if missing_columns:
        raise ValueError(
            f"Cannot corrupt dataframe; missing columns: {', '.join(missing_columns)}"
        )
    if len(df) < 2:
        raise ValueError("Need at least two rows to simulate corruption.")

    corrupted = df.copy(deep=True).reset_index(drop=True)
    input_rows = len(corrupted)
    events: list[dict[str, Any]] = []

    # 1. Remove the newest 20% according to published date.
    published_dates = pd.to_datetime(corrupted["published"], errors="coerce", utc=True)
    drop_count = min(max(1, round(input_rows * 0.20)), input_rows - 1)
    drop_indices = published_dates.sort_values(ascending=False, na_position="last").index[:drop_count]
    drop_changes = [
        {"paper_id": str(corrupted.at[index, "paper_id"]), "before": _snapshot(corrupted.loc[index]), "after": None}
        for index in drop_indices
    ]
    corrupted = corrupted.drop(index=drop_indices).reset_index(drop=True)
    events.append(_event("drop_latest_records", drop_changes, "Removed the newest 20% of records."))

    candidates = corrupted.index.tolist()
    group_size = min(2, len(candidates))
    groups = [
        candidates[offset:offset + group_size] or candidates[-group_size:]
        for offset in range(0, group_size * 4, group_size)
    ]

    # 2. Blank summaries.
    blank_indices = groups[0]
    blank_before = {index: _snapshot(corrupted.loc[index]) for index in blank_indices}
    corrupted.loc[blank_indices, "summary"] = ""
    _rebuild_derived_columns(corrupted)
    blank_changes = [
        {"paper_id": str(corrupted.at[index, "paper_id"]), "before": blank_before[index], "after": _snapshot(corrupted.loc[index])}
        for index in blank_indices
    ]
    events.append(_event("blank_summary", blank_changes, "Replaced summaries with empty strings."))

    # 3. Inject deterministic garbage text into summaries.
    noise_indices = groups[1]
    noise_before = {index: _snapshot(corrupted.loc[index]) for index in noise_indices}
    corrupted.loc[noise_indices, "summary"] = (
        corrupted.loc[noise_indices, "summary"].fillna("").astype(str) + _NOISE
    )
    _rebuild_derived_columns(corrupted)
    noise_changes = [
        {"paper_id": str(corrupted.at[index, "paper_id"]), "before": noise_before[index], "after": _snapshot(corrupted.loc[index])}
        for index in noise_indices
    ]
    events.append(_event("inject_noise", noise_changes, "Appended noise tokens to summaries."))

    # 4. Shorten titles below the eight-character quality threshold.
    title_indices = groups[2]
    title_before = {index: _snapshot(corrupted.loc[index]) for index in title_indices}
    corrupted.loc[title_indices, "title"] = (
        corrupted.loc[title_indices, "title"].fillna("").astype(str).str.slice(0, 7)
    )
    _rebuild_derived_columns(corrupted)
    title_changes = [
        {"paper_id": str(corrupted.at[index, "paper_id"]), "before": title_before[index], "after": _snapshot(corrupted.loc[index])}
        for index in title_indices
    ]
    events.append(_event("truncate_title", title_changes, "Truncated titles to at most seven characters."))

    # 5. Move published dates exactly one year (365 days) into the past.
    stale_indices = groups[3]
    stale_before = {index: _snapshot(corrupted.loc[index]) for index in stale_indices}
    old_dates = pd.to_datetime(corrupted.loc[stale_indices, "published"], errors="coerce")
    corrupted.loc[stale_indices, "published"] = (old_dates - pd.Timedelta(days=365)).dt.strftime("%Y-%m-%d")
    if "age_days" in corrupted.columns:
        corrupted.loc[stale_indices, "age_days"] = (
            pd.to_numeric(corrupted.loc[stale_indices, "age_days"], errors="coerce").fillna(0) + 365
        ).astype("int64")
    _rebuild_derived_columns(corrupted)
    stale_changes = [
        {"paper_id": str(corrupted.at[index, "paper_id"]), "before": stale_before[index], "after": _snapshot(corrupted.loc[index])}
        for index in stale_indices
    ]
    events.append(_event("stale_date", stale_changes, "Moved published dates back by 365 days."))

    # 6. Append exact duplicate rows with the same paper_id.
    duplicate_indices = candidates[-group_size:]
    duplicate_rows = corrupted.loc[duplicate_indices].copy(deep=True)
    duplicate_changes = [
        {
            "paper_id": str(row["paper_id"]),
            "before": _snapshot(row),
            "after": _snapshot(row),
        }
        for _, row in duplicate_rows.iterrows()
    ]
    corrupted = pd.concat([corrupted, duplicate_rows], ignore_index=True)
    events.append(_event("duplicate_rows", duplicate_changes, "Appended exact duplicate rows."))

    write_json(
        Path(output_log_path),
        {
            "input_rows": input_rows,
            "output_rows": len(corrupted),
            "scenario_count": len(events),
            "corruptions": events,
        },
    )
    return corrupted
