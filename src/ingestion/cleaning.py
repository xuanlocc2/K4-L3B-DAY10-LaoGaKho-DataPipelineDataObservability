from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

from ingestion.crossref import PaperRecord


def _strip_jats_xml(text: str) -> str:
    """Strip JATS/XML tags from abstract text safely using regex."""
    if not text:
        return ""
    text = re.sub(r"<jats:[^>]+>", "", text)
    text = re.sub(r"</jats:[^>]+>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_text_for_embedding(row: dict) -> str:
    """Build deterministic text_for_embedding with exactly 5 sections."""
    sections = [
        f"Title: {row.get('title', '').strip()}",
        f"Summary: {row.get('summary', '').strip()}",
        f"Authors: {row.get('authors_joined', '').strip()}",
        f"Categories: {row.get('categories_joined', '').strip()}",
        f"Published: {row.get('published', '').strip()}",
    ]
    return "\n\n".join(section for section in sections)


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Clean raw records into a DataFrame ready for embedding."""
    rows = []
    seen_ids = set()
    
    for record in records:
        if not record.paper_id or record.paper_id in seen_ids:
            continue
        seen_ids.add(record.paper_id)
        
        summary = _strip_jats_xml(record.summary)
        
        published = record.published or ""
        updated = record.updated or published
        
        try:
            if published:
                pub_dt = datetime.fromisoformat(published)
                age_days = (run_date - pub_dt).days
            else:
                age_days = -1
        except (ValueError, TypeError):
            age_days = -1
        
        rows.append({
            "paper_id": record.paper_id,
            "title": record.title.strip(),
            "summary": summary,
            "authors": record.authors,
            "categories": record.categories,
            "primary_category": record.primary_category,
            "published": published,
            "updated": updated,
            "abs_url": record.abs_url,
            "pdf_url": record.pdf_url,
            "comment": record.comment,
            "authors_joined": ", ".join(a.strip() for a in record.authors if a.strip()),
            "categories_joined": ", ".join(c.strip() for c in record.categories if c.strip()),
            "summary_chars": len(summary),
            "age_days": age_days,
        })
    
    df = pd.DataFrame(rows)
    
    if df.empty:
        return df
    
    df = df.drop_duplicates(subset=["paper_id"], keep="first")
    
    df = df[df["title"].notna() & (df["title"].str.strip() != "")]
    
    df = df.sort_values("paper_id").reset_index(drop=True)
    
    df["text_for_embedding"] = df.apply(_build_text_for_embedding, axis=1)
    
    return df
