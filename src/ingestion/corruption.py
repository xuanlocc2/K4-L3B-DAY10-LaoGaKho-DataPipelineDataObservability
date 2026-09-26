from __future__ import annotations

from datetime import date, timedelta
from math import ceil
from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import write_json


def _as_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _rebuild_embedding_fields(row: pd.Series) -> dict[str, Any]:
    title = _as_text(row.get("title"))
    summary = _as_text(row.get("summary"))
    authors = _as_text(row.get("authors_joined"))
    categories = _as_text(row.get("categories_joined"))
    if not authors and isinstance(row.get("authors"), (list, tuple)):
        authors = ", ".join(_as_text(value) for value in row["authors"] if _as_text(value))
    if not categories and isinstance(row.get("categories"), (list, tuple)):
        categories = ", ".join(_as_text(value) for value in row["categories"] if _as_text(value))
    return {
        "summary_chars": len(summary),
        "text_for_embedding": "\n".join(
            (
                f"Title: {title}",
                f"Authors: {authors}",
                f"Published: {_as_text(row.get('published'))}",
                f"Categories: {categories}",
                f"Summary: {summary}",
            )
        ),
    }


def _row_details(row: pd.Series, row_index: int, **changes: Any) -> dict[str, Any]:
    details = {
        "row_index": int(row_index),
        "paper_id": _as_text(row.get("paper_id")),
        "title": _as_text(row.get("title")),
        "published": _as_text(row.get("published")),
    }
    details.update(changes)
    return details


def corrupt_clean_dataframe(df: pd.DataFrame, output_log_path: str | Path) -> pd.DataFrame:
    """Apply six repeatable data-corruption scenarios and record each affected row."""
    corrupted = df.copy().reset_index(drop=True)
    original_rows = len(corrupted)
    operations: list[dict[str, Any]] = []

    drop_count = min(max(original_rows - 1, 0), ceil(original_rows * 0.2))
    if drop_count and "published" in corrupted.columns:
        published_dates = pd.to_datetime(corrupted["published"], errors="coerce", utc=True)
        dropped_indices = published_dates.sort_values(kind="stable", na_position="first").tail(drop_count).index.tolist()
    else:
        dropped_indices = []
    dropped_rows = [
        _row_details(corrupted.loc[index], index)
        for index in dropped_indices
    ]
    corrupted = corrupted.drop(index=dropped_indices).reset_index(drop=True)
    operations.append({"name": "drop_latest_records", "count": len(dropped_rows), "affected_rows": dropped_rows})

    row_count = len(corrupted)
    affected_count = min(row_count, max(1, ceil(row_count * 0.1))) if row_count else 0
    operation_offsets = (0, affected_count * 2, affected_count * 4, affected_count * 6)

    for operation_name, column, offset in (
        ("blank_summary", "summary", operation_offsets[0]),
        ("inject_noise", "summary", operation_offsets[1]),
        ("truncate_title", "title", operation_offsets[2]),
        ("stale_date", "published", operation_offsets[3]),
    ):
        affected_rows: list[dict[str, Any]] = []
        if row_count and column in corrupted.columns:
            indices = [(offset + step) % row_count for step in range(affected_count)]
            for index in indices:
                old_value = _as_text(corrupted.at[index, column])
                if operation_name == "blank_summary":
                    new_value = ""
                elif operation_name == "inject_noise":
                    noise = "@@@###CORRUPTED_NOISE###@@@"
                    new_value = f"{old_value} {noise}".strip()
                elif operation_name == "truncate_title":
                    new_value = old_value[:7]
                    if new_value == old_value:
                        new_value = old_value[:6] if old_value else "Title"
                    if new_value == old_value:
                        new_value = "X"
                else:
                    new_value = (date.today() - timedelta(days=365)).isoformat()

                corrupted.at[index, column] = new_value
                if operation_name == "stale_date" and "age_days" in corrupted.columns:
                    corrupted.at[index, "age_days"] = 365
                if operation_name in {"blank_summary", "inject_noise", "truncate_title", "stale_date"}:
                    derived_fields = _rebuild_embedding_fields(corrupted.loc[index])
                    for derived_column, derived_value in derived_fields.items():
                        if derived_column in corrupted.columns:
                            corrupted.at[index, derived_column] = derived_value
                affected_rows.append(
                    _row_details(
                        corrupted.loc[index],
                        index,
                        field=column,
                        before=old_value,
                        after=new_value,
                    )
                )
        operations.append({"name": operation_name, "count": len(affected_rows), "affected_rows": affected_rows})

    duplicate_count = min(len(corrupted), max(1, ceil(len(corrupted) * 0.1))) if len(corrupted) else 0
    duplicate_rows: list[dict[str, Any]] = []
    for source_index in range(duplicate_count):
        source_row = corrupted.iloc[source_index].copy()
        duplicate_index = len(corrupted)
        corrupted.loc[duplicate_index] = source_row
        duplicate_rows.append(
            {
                "source_row_index": source_index,
                "duplicate_row_index": duplicate_index,
                "paper_id": _as_text(source_row.get("paper_id")),
                "title": _as_text(source_row.get("title")),
            }
        )
    corrupted = corrupted.reset_index(drop=True)
    operations.append({"name": "duplicate_rows", "count": len(duplicate_rows), "affected_rows": duplicate_rows})

    log = {
        "original_rows": original_rows,
        "rows_after_drop": original_rows - len(dropped_rows),
        "corrupted_rows": len(corrupted),
        "total_affected_rows": sum(operation["count"] for operation in operations),
        "operations": operations,
    }
    write_json(Path(output_log_path), log)
    return corrupted
