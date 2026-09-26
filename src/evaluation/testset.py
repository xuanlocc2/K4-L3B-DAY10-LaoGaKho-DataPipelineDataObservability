from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import first_sentence, normalize_whitespace, write_json


_QUESTION_TYPES = (
    "summary",
    "authors",
    "date",
    "categories",
    "summary",
    "authors",
    "date",
    "categories",
    "summary",
    "authors",
)


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(normalize_whitespace(str(item)) for item in value if str(item).strip())
    return normalize_whitespace(str(value))


def _ground_truth(row: pd.Series, question_type: str) -> str:
    if question_type == "summary":
        return first_sentence(_text(row.get("summary")))
    if question_type == "authors":
        return _text(row.get("authors_joined")) or _text(row.get("authors"))
    if question_type == "date":
        return _text(row.get("published"))
    return (
        _text(row.get("categories_joined"))
        or _text(row.get("categories"))
        or _text(row.get("primary_category"))
        or "Uncategorized"
    )


def _question(title: str, question_type: str) -> str:
    templates = {
        "summary": "What is the summary of the paper '{title}'?",
        "authors": "Who authored the paper '{title}'?",
        "date": "When was the paper '{title}' published?",
        "categories": "What categories does the paper '{title}' belong to?",
    }
    return templates[question_type].format(title=title)


def build_test_set(df: pd.DataFrame, output_path) -> list[dict[str, Any]]:
    """Create ten deterministic, source-grounded benchmark questions.

    The allocation is 3 summary, 3 authors, 2 date, and 2 categories
    questions. Every test example is tied to exactly one stable DOI.
    """
    required_columns = {"paper_id", "title", "summary", "published"}
    missing_columns = sorted(required_columns.difference(df.columns))
    if missing_columns:
        raise ValueError(
            f"Cannot build evaluation set; missing columns: {', '.join(missing_columns)}"
        )

    candidates = df.copy(deep=True)
    candidates["paper_id"] = candidates["paper_id"].map(_text)
    candidates["title"] = candidates["title"].map(_text)
    candidates = candidates.loc[
        candidates["paper_id"].ne("") & candidates["title"].ne("")
    ].drop_duplicates(subset="paper_id", keep="first")
    candidates = candidates.sort_values("paper_id", kind="stable")
    if len(candidates) < len(_QUESTION_TYPES):
        raise ValueError(
            f"Need at least {len(_QUESTION_TYPES)} unique papers; found {len(candidates)}."
        )

    test_set: list[dict[str, Any]] = []
    for number, (question_type, (_, row)) in enumerate(
        zip(_QUESTION_TYPES, candidates.head(len(_QUESTION_TYPES)).iterrows(), strict=True),
        start=1,
    ):
        title = _text(row["title"])
        ground_truth = _ground_truth(row, question_type)
        if not ground_truth:
            raise ValueError(
                f"Cannot create a {question_type} question for DOI {row['paper_id']}: missing ground truth."
            )
        test_set.append(
            {
                "id": f"eval_{number:03d}",
                "question_type": question_type,
                "question": _question(title, question_type),
                "ground_truth": ground_truth,
                "ground_truth_doc_ids": [_text(row["paper_id"])],
            }
        )

    write_json(Path(output_path), test_set)
    return test_set
