from __future__ import annotations

from dataclasses import asdict, dataclass
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from typing import Any

import requests

from core.config import Settings
from core.utils import ensure_parent, write_json


@dataclass(frozen=True)
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


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _clean_text(value: Any) -> str:
    if isinstance(value, list):
        value = next((item for item in value if item), "")
    if not isinstance(value, str):
        return ""
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _crossref_date(value: Any) -> str:
    if isinstance(value, dict):
        date_parts = value.get("date-parts")
        if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list):
            parts = date_parts[0]
            if parts and all(isinstance(part, int) for part in parts[:3]):
                return "-".join(f"{part:02d}" if index else f"{part:04d}" for index, part in enumerate(parts[:3]))
        date_time = value.get("date-time") or value.get("timestamp")
        if isinstance(date_time, str):
            return date_time[:10]
    if isinstance(value, str):
        return value.strip()[:10]
    return ""


def _author_name(author: Any) -> str:
    if not isinstance(author, dict):
        return _clean_text(author)
    name = _clean_text(author.get("name"))
    if name:
        return name
    return _clean_text(" ".join(part for part in (author.get("given"), author.get("family")) if part))


def parse_crossref_payload(payload: dict[str, Any]) -> list[PaperRecord]:
    """Parse Crossref's works response into normalized paper records."""
    message = payload.get("message", {})
    items = message.get("items", []) if isinstance(message, dict) else []
    if not isinstance(items, list):
        return []

    records: list[PaperRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        paper_id = _clean_text(item.get("DOI") or item.get("doi"))
        title = _clean_text(item.get("title"))
        if not paper_id or not title:
            continue

        raw_authors = item.get("author", [])
        authors = [_author_name(author) for author in raw_authors] if isinstance(raw_authors, list) else []
        authors = [author for author in authors if author]

        raw_categories = item.get("subject", [])
        categories = [_clean_text(category) for category in raw_categories] if isinstance(raw_categories, list) else []
        categories = list(dict.fromkeys(category for category in categories if category))

        published = next(
            (_crossref_date(item.get(field)) for field in ("published", "published-online", "published-print", "issued") if _crossref_date(item.get(field))),
            "",
        )
        updated = _crossref_date(item.get("updated")) or _crossref_date(item.get("indexed"))

        pdf_url = ""
        raw_links = item.get("link", [])
        if isinstance(raw_links, list):
            for link in raw_links:
                if isinstance(link, dict) and "pdf" in str(link.get("content-type", "")).lower():
                    pdf_url = _clean_text(link.get("URL"))
                    if pdf_url:
                        break

        raw_comment = item.get("comment", "")
        if isinstance(raw_comment, list):
            comment = "; ".join(filter(None, (_clean_text(entry.get("text", "") if isinstance(entry, dict) else entry) for entry in raw_comment)))
        else:
            comment = _clean_text(raw_comment)

        records.append(
            PaperRecord(
                paper_id=paper_id,
                title=title,
                summary=_clean_text(item.get("abstract")),
                authors=authors,
                categories=categories,
                primary_category=categories[0] if categories else "",
                published=published,
                updated=updated,
                abs_url=_clean_text(item.get("URL")),
                pdf_url=pdf_url,
                comment=comment,
            )
        )
    return records


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """Fetch Crossref works, preserving the response and falling back to its snapshot."""
    raw_response_path = settings.paths.raw_api_response
    raw_records_path = settings.paths.raw_records_json

    def load_snapshot() -> tuple[dict[str, Any], list[PaperRecord]]:
        if not raw_response_path.is_file():
            raise FileNotFoundError(f"Crossref snapshot not found: {raw_response_path}")
        snapshot = json.loads(raw_response_path.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict):
            raise ValueError("Crossref snapshot must contain a JSON object.")
        return snapshot, parse_crossref_payload(snapshot)

    if not settings.refresh_source and raw_response_path.is_file():
        payload, records = load_snapshot()
    else:
        params = {
            "query": settings.source_query,
            "filter": settings.source_filter,
            "rows": settings.max_results,
        }
        payload = None
        response_body = b""
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.get("https://api.crossref.org/works", params=params, timeout=20)
                if response.status_code in {429, 503} and attempt < 2:
                    time.sleep(0.5 * (2**attempt))
                    continue
                response.raise_for_status()
                payload = response.json()
                response_body = response.content
                break
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (2**attempt))

        if payload is None:
            try:
                payload, records = load_snapshot()
            except (OSError, ValueError, json.JSONDecodeError) as snapshot_error:
                raise RuntimeError(f"Crossref request failed and offline snapshot could not be loaded: {snapshot_error}") from last_error
        else:
            ensure_parent(raw_response_path)
            raw_response_path.write_bytes(response_body)
            records = parse_crossref_payload(payload)

    write_json(raw_records_path, [asdict(record) for record in records])
    return records


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Load either saved PaperRecord rows or an unparsed Crossref response."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return parse_crossref_payload(payload)
    if not isinstance(payload, list):
        raise ValueError(f"Expected a list of records or Crossref payload in {path}.")

    records: list[PaperRecord] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        paper_id = _clean_text(row.get("paper_id"))
        title = _clean_text(row.get("title"))
        if not paper_id or not title:
            continue
        records.append(
            PaperRecord(
                paper_id=paper_id,
                title=title,
                summary=_clean_text(row.get("summary")),
                authors=[_clean_text(value) for value in row.get("authors", []) if _clean_text(value)],
                categories=[_clean_text(value) for value in row.get("categories", []) if _clean_text(value)],
                primary_category=_clean_text(row.get("primary_category")),
                published=_clean_text(row.get("published")),
                updated=_clean_text(row.get("updated")),
                abs_url=_clean_text(row.get("abs_url")),
                pdf_url=_clean_text(row.get("pdf_url")),
                comment=_clean_text(row.get("comment")),
            )
        )
    return records
