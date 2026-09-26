from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import first_sentence, normalize_whitespace, write_json


def _text(value: Any) -> str:
   return normalize_whitespace(value) if isinstance(value, str) else ""


def _joined_values(value: Any) -> str:
   if isinstance(value, str):
      return _text(value)
   if isinstance(value, (list, tuple)):
      return ", ".join(text for item in value if (text := _text(item)))
   return ""


def build_test_set(df: pd.DataFrame, output_path: str | Path) -> list[dict[str, Any]]:
   """Build and save ten grounded questions distributed across four task types."""
   if len(df) < 10:
      raise ValueError(f"At least 10 cleaned papers are required; got {len(df)}.")

   papers: list[dict[str, str]] = []
   seen_ids: set[str] = set()
   for row in df.to_dict(orient="records"):
      paper_id = _text(row.get("paper_id"))
      title = _text(row.get("title"))
      if not paper_id or not title or paper_id.casefold() in seen_ids:
         continue
      seen_ids.add(paper_id.casefold())

      summary = _text(row.get("summary"))
      authors = _joined_values(row.get("authors_joined", row.get("authors", [])))
      categories = _joined_values(row.get("categories_joined", row.get("categories", [])))
      published = _text(row.get("published"))
      papers.append(
         {
            "paper_id": paper_id,
            "title": title,
            "summary": summary,
            "authors": authors,
            "categories": categories,
            "published": published,
         }
      )

   quotas = (("summary", 3), ("authors", 3), ("date", 2), ("categories", 2))
   test_cases: list[dict[str, Any]] = []
   used_ids: set[str] = set()

   for question_type, quota in quotas:
      added = 0
      for paper in papers:
         paper_id = paper["paper_id"]
         if paper_id.casefold() in used_ids:
            continue

         if question_type == "summary":
            ground_truth = first_sentence(paper["summary"])
            question = f"What is the summary of the paper '{paper['title']}'?"
         elif question_type == "authors":
            ground_truth = paper["authors"]
            question = f"Who authored the paper '{paper['title']}'?"
         elif question_type == "date":
            ground_truth = paper["published"]
            question = f"When was the paper '{paper['title']}' published?"
         else:
            ground_truth = paper["categories"]
            question = f"What categories describe the paper '{paper['title']}'?"

         if not ground_truth:
            continue

         test_cases.append(
            {
               "id": f"eval_{len(test_cases) + 1:03d}",
               "question_type": question_type,
               "question": question,
               "ground_truth": ground_truth,
               "ground_truth_doc_ids": [paper_id],
            }
         )
         used_ids.add(paper_id.casefold())
         added += 1
         if added == quota:
            break

      if added != quota:
         raise ValueError(
            f"Could only build {added} of {quota} '{question_type}' questions from the cleaned data."
         )

   write_json(Path(output_path), test_cases)
   return test_cases
