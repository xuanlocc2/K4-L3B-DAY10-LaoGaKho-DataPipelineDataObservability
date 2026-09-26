from __future__ import annotations

from dataclasses import asdict, dataclass
from html import unescape
import json
from pathlib import Path
import re
import time
from typing import Any

import requests

from core.config import Settings
from core.utils import ensure_parent, write_json


CROSSREF_WORKS_URL = "https://api.crossref.org/works"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")


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


def _clean_text(value: Any) -> str:
    """Remove JATS/HTML tags, decode entities, and collapse whitespace."""
    if not isinstance(value, str):
        return ""
    without_tags = _TAG_PATTERN.sub(" ", value)
    return _WHITESPACE_PATTERN.sub(" ", unescape(without_tags)).strip()


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        return _clean_text(value[0]) if value else ""
    return _clean_text(value)


def _crossref_date(value: Any) -> str:
    """Convert a Crossref date object to YYYY-MM-DD."""
    if not isinstance(value, dict):
        return ""
    date_time = value.get("date-time")
    if isinstance(date_time, str) and len(date_time) >= 10:
        return date_time[:10]

    date_parts = value.get("date-parts")
    if not isinstance(date_parts, list) or not date_parts or not isinstance(date_parts[0], list):
        return ""
    parts = date_parts[0]
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
    except (IndexError, TypeError, ValueError):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _first_date(item: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = _crossref_date(item.get(field))
        if value:
            return value
    return ""


def _author_name(author: Any) -> str:
    if not isinstance(author, dict):
        return ""
    parts = [
        _clean_text(author.get("given")),
        _clean_text(author.get("family")),
    ]
    full_name = " ".join(part for part in parts if part)
    return full_name or _clean_text(author.get("name"))


def _pdf_url(item: dict[str, Any], fallback: str) -> str:
    links = item.get("link")
    if not isinstance(links, list):
        return fallback
    for link in links:
        if not isinstance(link, dict):
            continue
        content_type = str(link.get("content-type", "")).lower()
        url = _clean_text(link.get("URL"))
        if url and "pdf" in content_type:
            return url
    return fallback


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Parse a Crossref REST payload into normalized ``PaperRecord`` objects.

    Records without a DOI or title are skipped because those fields form the
    stable identity and minimum searchable content used downstream.
    """
    if not isinstance(payload, dict):
        return []
    message = payload.get("message")
    items = message.get("items") if isinstance(message, dict) else None
    if not isinstance(items, list):
        return []

    records: list[PaperRecord] = []
    seen_dois: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        paper_id = _clean_text(item.get("DOI"))
        title = _first_text(item.get("title"))
        doi_key = paper_id.lower()
        if not paper_id or not title or doi_key in seen_dois:
            continue

        authors = [
            name
            for author in item.get("author", [])
            if (name := _author_name(author))
        ] if isinstance(item.get("author"), list) else []
        categories = [
            category
            for subject in item.get("subject", [])
            if (category := _clean_text(subject))
        ] if isinstance(item.get("subject"), list) else []
        published = _first_date(
            item,
            ("published-print", "published-online", "published", "issued", "created"),
        )
        updated = _first_date(item, ("updated", "indexed", "created")) or published
        abs_url = _clean_text(item.get("URL")) or f"https://doi.org/{paper_id}"

        records.append(
            PaperRecord(
                paper_id=paper_id,
                title=title,
                summary=_clean_text(item.get("abstract")),
                authors=authors,
                categories=categories,
                primary_category=categories[0] if categories else "Uncategorized",
                published=published,
                updated=updated,
                abs_url=abs_url,
                pdf_url=_pdf_url(item, abs_url),
                comment=f"Crossref record {paper_id}",
            )
        )
        seen_dois.add(doi_key)
    return records


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """Fetch Crossref data and fall back to the preserved local snapshot.

    On a successful request the exact response bytes are stored before any
    normalization. Network errors, malformed responses, and retryable HTTP
    failures use the existing raw response file as an offline snapshot.
    """
    params = {
        "query": settings.source_query,
        "filter": settings.source_filter,
        "rows": settings.max_results,
    }
    payload: dict[str, Any] | None = None
    raw_response: bytes | None = None
    last_error: Exception | None = None

    for attempt in range(3):
        try:
            response = requests.get(
                CROSSREF_WORKS_URL,
                params=params,
                headers={"User-Agent": "day10-data-observability-lab/1.0"},
                timeout=20,
            )
            if response.status_code in RETRYABLE_STATUS_CODES:
                raise requests.HTTPError(
                    f"Crossref returned retryable HTTP {response.status_code}",
                    response=response,
                )
            response.raise_for_status()
            candidate = response.json()
            if not isinstance(candidate, dict):
                raise ValueError("Crossref response must be a JSON object.")
            parsed = parse_crossref_payload(candidate)
            if not parsed:
                raise ValueError("Crossref response contains no valid records.")
            payload = candidate
            raw_response = response.content
            break
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)

    if payload is None:
        try:
            raw_response = settings.paths.raw_api_response.read_bytes()
            snapshot = json.loads(raw_response.decode("utf-8"))
            if not isinstance(snapshot, dict):
                raise ValueError("Offline Crossref snapshot must be a JSON object.")
            payload = snapshot
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            reason = last_error or error
            raise RuntimeError(
                "Crossref request failed and no valid offline snapshot is available."
            ) from reason
        print(f"Crossref unavailable; using offline snapshot: {settings.paths.raw_api_response}")
    else:
        ensure_parent(settings.paths.raw_api_response)
        settings.paths.raw_api_response.write_bytes(raw_response or b"")

    records = parse_crossref_payload(payload)
    if not records:
        raise RuntimeError("Crossref payload contains no valid paper records.")
    write_json(settings.paths.raw_records_json, [asdict(record) for record in records])
    return records


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Load the normalized raw-record artifact for reproducible reruns."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cannot read raw records from {path}.") from error
    if not isinstance(payload, list):
        raise ValueError(f"Expected a list of PaperRecord objects in {path}.")

    field_names = tuple(PaperRecord.__dataclass_fields__)
    records: list[PaperRecord] = []
    for position, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Raw record {position} is not a JSON object.")
        missing = [field for field in field_names if field not in item]
        if missing:
            raise ValueError(
                f"Raw record {position} is missing fields: {', '.join(missing)}."
            )
        records.append(PaperRecord(**{field: item[field] for field in field_names}))
    return records
