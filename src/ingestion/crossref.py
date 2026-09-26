from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from core.config import Settings, load_settings
from core.utils import ensure_parent, read_json, write_json


CROSSREF_BASE_URL = "https://api.crossref.org/works"


@dataclass
class PaperRecord:
    paper_id: str
    title: str
    summary: str
    authors: list[str]
    categories: list[str]
    primary_category: str
    published: str
    updated: str
    abs_url: str
    pdf_url: str
    comment: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "summary": self.summary,
            "authors": self.authors,
            "categories": self.categories,
            "primary_category": self.primary_category,
            "published": self.published,
            "updated": self.updated,
            "abs_url": self.abs_url,
            "pdf_url": self.pdf_url,
            "comment": self.comment,
        }


def _get_crossref_headers(settings: Settings) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    mailto = os.getenv("CROSSREF_MAILTO", "")
    user_agent = os.getenv(
        "CROSSREF_USER_AGENT",
        settings.paths.project_dir.name + "/1.0"
    )
    if mailto:
        headers["User-Agent"] = f"{user_agent} (mailto:{mailto})"
    else:
        headers["User-Agent"] = user_agent
    return headers


def _parse_date(date_parts: list[list[int]] | None) -> str:
    if not date_parts or not date_parts[0]:
        return ""
    parts = date_parts[0]
    year = parts[0] if len(parts) > 0 else 1
    month = parts[1] if len(parts) > 1 else 1
    day = parts[2] if len(parts) > 2 else 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _strip_jats_xml(text: str) -> str:
    """Strip JATS/XML tags from abstract text safely."""
    if not text:
        return ""
    text = re.sub(r"<jats:[^>]+>", "", text)
    text = re.sub(r"</jats:[^>]+>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Parse Crossref API payload into list of PaperRecord."""
    records: list[PaperRecord] = []
    items = payload.get("message", {}).get("items", [])
    
    for item in items:
        doi = item.get("DOI", "")
        if not doi:
            continue
        
        title_list = item.get("title", [])
        title = title_list[0] if title_list else ""
        if not title:
            continue
        
        abstract = item.get("abstract", "")
        summary = _strip_jats_xml(abstract)
        
        authors_data = item.get("author", [])
        authors = []
        for author in authors_data:
            given = author.get("given", "")
            family = author.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)
        
        categories_data = item.get("subject", [])
        categories = [cat.strip() for cat in categories_data if cat.strip()]
        primary_category = categories[0] if categories else ""
        
        published_date = _parse_date(item.get("published", {}).get("date-parts"))
        created_date = item.get("created", {}).get("date-time", "")
        if created_date:
            created_date = created_date[:10]
        
        url = item.get("URL", f"https://doi.org/{doi}")
        pdf_url = item.get("URL", url)
        
        record = PaperRecord(
            paper_id=doi,
            title=title.strip(),
            summary=summary,
            authors=authors,
            categories=categories,
            primary_category=primary_category,
            published=published_date,
            updated=created_date or published_date,
            abs_url=url,
            pdf_url=pdf_url,
            comment=f"Crossref record {doi}",
        )
        records.append(record)
    
    return records


def _fetch_with_retry(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    timeout: int = 20,
    max_retries: int = 4,
) -> dict[str, Any]:
    """Fetch URL with exponential backoff for 429/5xx errors."""
    retry_after = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
            
            if response.status_code == 200:
                return response.json()
            
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 2))
                if attempt < max_retries:
                    time.sleep(retry_after)
                    continue
                raise RuntimeError(f"Crossref 429 after {max_retries} retries")
            
            if response.status_code in {500, 502, 503, 504}:
                if attempt < max_retries:
                    wait = (2 ** attempt) + retry_after if retry_after else 2 ** attempt
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Crossref {response.status_code} after {max_retries} retries")
            
            raise RuntimeError(f"Crossref API error: {response.status_code}")
            
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError("Crossref request timeout")
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Crossref request failed: {e}")
    
    raise RuntimeError("Max retries exceeded")


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """Fetch records from Crossref API or load from snapshot."""
    timeout = int(os.getenv("CROSSREF_TIMEOUT_SECONDS", "20"))
    max_retries = int(os.getenv("CROSSREF_MAX_RETRIES", "4"))
    
    headers = _get_crossref_headers(settings)
    
    params = {
        "query.bibliographic": settings.source_query,
        "filter": settings.source_filter,
        "rows": settings.max_results,
    }
    
    try:
        payload = _fetch_with_retry(
            CROSSREF_BASE_URL,
            headers=headers,
            params=params,
            timeout=timeout,
            max_retries=max_retries,
        )
        
        ensure_parent(settings.paths.raw_api_response)
        write_json(settings.paths.raw_api_response, payload)
        
    except Exception as e:
        if settings.paths.raw_api_response.exists():
            payload = read_json(settings.paths.raw_api_response)
        else:
            raise RuntimeError(f"Crossref fetch failed and no snapshot available: {e}")
    
    records = parse_crossref_payload(payload)
    
    ensure_parent(settings.paths.raw_records_json)
    write_json(
        settings.paths.raw_records_json,
        [r.to_dict() for r in records],
    )
    
    return records


def fetch_doi_record(doi: str, settings: Settings) -> PaperRecord | None:
    """Fetch a single DOI record from Crossref."""
    timeout = int(os.getenv("CROSSREF_TIMEOUT_SECONDS", "20"))
    max_retries = int(os.getenv("CROSSREF_MAX_RETRIES", "4"))
    
    headers = _get_crossref_headers(settings)
    
    try:
        payload = _fetch_with_retry(
            f"{CROSSREF_BASE_URL}/{doi}",
            headers=headers,
            params={},
            timeout=timeout,
            max_retries=max_retries,
        )
        
        records = parse_crossref_payload(payload)
        return records[0] if records else None
        
    except Exception:
        return None


def fetch_records_by_date_range(
    settings: Settings,
    from_index_date: str,
    until_index_date: str,
) -> list[PaperRecord]:
    """Fetch records from Crossref filtered by index date range."""
    timeout = int(os.getenv("CROSSREF_TIMEOUT_SECONDS", "20"))
    max_retries = int(os.getenv("CROSSREF_MAX_RETRIES", "4"))
    
    headers = _get_crossref_headers(settings)
    
    filter_str = f"from-index-date:{from_index_date},until-index-date:{until_index_date},has-abstract:true"
    if settings.source_filter:
        filter_str = f"{filter_str},{settings.source_filter}"
    
    params = {
        "query.bibliographic": settings.source_query,
        "filter": filter_str,
        "rows": int(os.getenv("LIVE_MAX_RESULTS", "50")),
    }
    
    try:
        payload = _fetch_with_retry(
            CROSSREF_BASE_URL,
            headers=headers,
            params=params,
            timeout=timeout,
            max_retries=max_retries,
        )
        
        return parse_crossref_payload(payload)
        
    except Exception:
        return []


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Load PaperRecord list from JSON snapshot."""
    data = read_json(path)
    if isinstance(data, dict) and "message" in data:
        return parse_crossref_payload(data)
    
    records = []
    for item in data:
        records.append(PaperRecord(
            paper_id=item.get("paper_id", ""),
            title=item.get("title", ""),
            summary=item.get("summary", ""),
            authors=item.get("authors", []),
            categories=item.get("categories", []),
            primary_category=item.get("primary_category", ""),
            published=item.get("published", ""),
            updated=item.get("updated", ""),
            abs_url=item.get("abs_url", ""),
            pdf_url=item.get("pdf_url", ""),
            comment=item.get("comment", ""),
        ))
    return records
