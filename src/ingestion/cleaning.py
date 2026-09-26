from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

import pandas as pd

from core.utils import normalize_whitespace
from ingestion.crossref import PaperRecord


_COLUMNS = [
   "paper_id",
   "title",
   "summary",
   "authors",
   "categories",
   "primary_category",
   "published",
   "updated",
   "abs_url",
   "pdf_url",
   "comment",
   "authors_joined",
   "categories_joined",
   "summary_chars",
   "age_days",
   "text_for_embedding",
]


def _clean_text(value: Any) -> str:
   return normalize_whitespace(value) if isinstance(value, str) else ""


def _clean_items(value: Any) -> list[str]:
   if isinstance(value, str):
      value = [value]
   if not isinstance(value, (list, tuple)):
      return []
   return [text for item in value if (text := _clean_text(item))]


def _parse_date(value: Any) -> date | None:
   if isinstance(value, datetime):
      return value.date()
   if isinstance(value, date):
      return value
   text = _clean_text(value)
   if not text:
      return None
   try:
      return date.fromisoformat(text[:10])
   except ValueError:
      try:
         return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
      except ValueError:
         return None


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
   """Normalize Crossref records and prepare rows for embedding and evaluation."""
   run_day = run_date.date()
   rows: list[dict[str, Any]] = []
   seen_paper_ids: set[str] = set()

   for record in records:
      row = asdict(record)
      paper_id = _clean_text(row.get("paper_id"))
      title = _clean_text(row.get("title"))
      published_day = _parse_date(row.get("published"))
      if not paper_id or not title or published_day is None:
         continue

      paper_key = paper_id.casefold()
      if paper_key in seen_paper_ids:
         continue
      seen_paper_ids.add(paper_key)

      summary = _clean_text(row.get("summary"))
      authors = _clean_items(row.get("authors"))
      categories = _clean_items(row.get("categories"))
      primary_category = _clean_text(row.get("primary_category"))
      if not categories and primary_category:
         categories = [primary_category]
      elif not primary_category and categories:
         primary_category = categories[0]

      authors_joined = ", ".join(authors)
      categories_joined = ", ".join(categories)
      published = published_day.isoformat()
      text_for_embedding = "\n".join(
         (
            f"Title: {title}",
            f"Authors: {authors_joined}",
            f"Published: {published}",
            f"Categories: {categories_joined}",
            f"Summary: {summary}",
         )
      )

      rows.append(
         {
            "paper_id": paper_id,
            "title": title,
            "summary": summary,
            "authors": authors,
            "categories": categories,
            "primary_category": primary_category,
            "published": published,
            "updated": _clean_text(row.get("updated")),
            "abs_url": _clean_text(row.get("abs_url")),
            "pdf_url": _clean_text(row.get("pdf_url")),
            "comment": _clean_text(row.get("comment")),
            "authors_joined": authors_joined,
            "categories_joined": categories_joined,
            "summary_chars": len(summary),
            "age_days": (run_day - published_day).days,
            "text_for_embedding": text_for_embedding,
         }
      )

   dataframe = pd.DataFrame(rows, columns=_COLUMNS)
   if not dataframe.empty:
      dataframe = dataframe.sort_values(["published", "paper_id"], kind="stable", ignore_index=True)
   return dataframe
