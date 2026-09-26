from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

import pandas as pd

from core.utils import normalize_whitespace
from ingestion.crossref import PaperRecord


_BASE_COLUMNS = tuple(PaperRecord.__dataclass_fields__)
_DERIVED_COLUMNS = (
    "authors_joined",
    "categories_joined",
    "summary_chars",
    "age_days",
    "ingested_at",
    "text_for_embedding",
)


def _clean_scalar(value: Any) -> str:
    if value is None:
        return ""
    return normalize_whitespace(str(value))


def _clean_list(value: Any) -> list[str]:
    """Normalize a string list while preserving order and removing duplicates."""
    if not isinstance(value, (list, tuple)):
        value = [value] if value else []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_scalar(item)
        key = text.casefold()
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
    return cleaned


def _embedding_text(row: pd.Series) -> str:
    return "\n".join(
        (
            f"Title: {row['title']}",
            f"Authors: {row['authors_joined']}",
            f"Published: {row['published']}",
            f"Categories: {row['categories_joined']}",
            f"Summary: {row['summary']}",
        )
    )


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Normalize raw paper records into the dataframe contract used for RAG.

    Invalid rows without a paper ID, title, or parseable publication date are
    removed. DOI comparison is case-insensitive because DOI identifiers are
    case-insensitive by definition.
    """
    if not records:
        return pd.DataFrame(columns=[*_BASE_COLUMNS, *_DERIVED_COLUMNS])

    df = pd.DataFrame(asdict(record) for record in records)
    for column in ("paper_id", "title", "summary", "primary_category", "abs_url", "pdf_url", "comment"):
        df[column] = df[column].map(_clean_scalar)
    df["paper_id"] = df["paper_id"].str.lower()
    df["authors"] = df["authors"].map(_clean_list)
    df["categories"] = df["categories"].map(_clean_list)

    published = pd.to_datetime(df["published"], errors="coerce", utc=True)
    updated = pd.to_datetime(df["updated"], errors="coerce", utc=True)
    valid_rows = df["paper_id"].ne("") & df["title"].ne("") & published.notna()
    df = df.loc[valid_rows].copy()
    published = published.loc[valid_rows]
    updated = updated.loc[valid_rows].fillna(published)

    df = df.loc[~df["paper_id"].duplicated(keep="first")].copy()
    published = published.loc[df.index]
    updated = updated.loc[df.index]

    run_timestamp = pd.Timestamp(run_date)
    if run_timestamp.tzinfo is None:
        run_timestamp = run_timestamp.tz_localize("UTC")
    else:
        run_timestamp = run_timestamp.tz_convert("UTC")

    df["published"] = published.dt.strftime("%Y-%m-%d")
    df["updated"] = updated.dt.strftime("%Y-%m-%d")
    df["authors_joined"] = df["authors"].map(lambda values: ", ".join(values))
    df["categories_joined"] = df["categories"].map(lambda values: ", ".join(values))
    df["summary_chars"] = df["summary"].str.len().astype("int64")
    df["age_days"] = (
        run_timestamp.normalize() - published.dt.normalize()
    ).dt.days.astype("int64")
    df["ingested_at"] = run_timestamp.isoformat()
    df["text_for_embedding"] = df.apply(_embedding_text, axis=1)

    return df.sort_values(
        by=["published", "paper_id"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
