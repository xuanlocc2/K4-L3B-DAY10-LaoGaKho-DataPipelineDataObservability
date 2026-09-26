from __future__ import annotations

from typing import Any

import pandas as pd

from core.utils import write_json


def _make_summary_question(row: dict, idx: int) -> dict[str, Any]:
    """Create a summary-related question."""
    return {
        "id": f"q{idx:03d}",
        "question_type": "summary",
        "question": f"What is the main contribution or focus of the paper titled '{row['title']}'?",
        "ground_truth": row["summary"],
        "ground_truth_doc_ids": [row["paper_id"]],
    }


def _make_authors_question(row: dict, idx: int) -> dict[str, Any]:
    """Create an authors-related question."""
    authors = row["authors_joined"]
    return {
        "id": f"q{idx:03d}",
        "question_type": "authors",
        "question": f"Who are the authors of the paper titled '{row['title']}'?",
        "ground_truth": authors,
        "ground_truth_doc_ids": [row["paper_id"]],
    }


def _make_date_question(row: dict, idx: int) -> dict[str, Any]:
    """Create a date-related question."""
    return {
        "id": f"q{idx:03d}",
        "question_type": "date",
        "question": f"When was the paper titled '{row['title']}' published?",
        "ground_truth": row["published"],
        "ground_truth_doc_ids": [row["paper_id"]],
    }


def _make_categories_question(row: dict, idx: int) -> dict[str, Any]:
    """Create a categories-related question."""
    return {
        "id": f"q{idx:03d}",
        "question_type": "categories",
        "question": f"What are the research categories or domains of the paper titled '{row['title']}'?",
        "ground_truth": row["categories_joined"],
        "ground_truth_doc_ids": [row["paper_id"]],
    }


def build_test_set(df: pd.DataFrame, output_path) -> list[dict[str, Any]]:
    """Build evaluation test set from cleaned DataFrame.

    Creates exactly 10 deterministic questions:
    - 3 summary questions
    - 3 authors questions
    - 2 date questions
    - 2 categories questions

    Selection is fully deterministic: df is sorted by paper_id (DOI), then
    rows are iterated in that fixed order. All 24 papers in papers_clean.json
    have all required fields (paper_id, title, summary, authors_joined,
    published, categories_joined) so the first-valid-row heuristic always
    picks the same 10 distinct papers (indices 0,1,2,3,4,5,6,7,8,9 of the
    sorted order = the 10 original Crossref papers, not the 14 advanced
    "Advanced Perspectives" variants at the end).
    """
    if len(df) < 4:
        raise ValueError(f"Need at least 4 papers for test set, got {len(df)}")

    # Sort by paper_id (DOI) for deterministic, reproducible ordering.
    # All paper_ids are DOIs so lexicographic sort is stable.
    df_sorted = df.sort_values("paper_id").reset_index(drop=True)
    
    questions: list[dict[str, Any]] = []
    idx = 1
    
    summary_count = 0
    for i in range(len(df_sorted)):
        if summary_count >= 3:
            break
        row = df_sorted.iloc[i].to_dict()
        if row.get("summary") and len(row["summary"]) > 20:
            questions.append(_make_summary_question(row, idx))
            idx += 1
            summary_count += 1
    
    authors_count = 0
    for i in range(len(df_sorted)):
        if authors_count >= 3:
            break
        row = df_sorted.iloc[i].to_dict()
        if row.get("authors_joined") and len(row["authors_joined"]) > 0:
            questions.append(_make_authors_question(row, idx))
            idx += 1
            authors_count += 1
    
    date_count = 0
    for i in range(len(df_sorted)):
        if date_count >= 2:
            break
        row = df_sorted.iloc[i].to_dict()
        if row.get("published"):
            questions.append(_make_date_question(row, idx))
            idx += 1
            date_count += 1
    
    categories_count = 0
    for i in range(len(df_sorted)):
        if categories_count >= 2:
            break
        row = df_sorted.iloc[i].to_dict()
        if row.get("categories_joined") and len(row["categories_joined"]) > 0:
            questions.append(_make_categories_question(row, idx))
            idx += 1
            categories_count += 1
    
    write_json(output_path, questions)
    
    return questions
