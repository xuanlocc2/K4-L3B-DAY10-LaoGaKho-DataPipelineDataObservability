"""Dataset diff and fingerprinting for corruption detection.

Provides deterministic fingerprinting and structured diff reporting
for clean dataset state comparisons.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from core.utils import normalize_whitespace


# Fields that are considered critical (blanking them is high severity)
CRITICAL_FIELDS = {"title", "summary", "authors", "published"}


def _canonical_json(obj: Any) -> str:
    """Return a canonical JSON string for hashing."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=True)


def _normalize_value(value: Any) -> str:
    """Normalize a value for comparison: strip whitespace, treat empty/null as equivalent.

    Handles:
    - None / empty → ""
    - list / dict → stable JSON string
    - JSON string → parse then serialize
    - Python-literal string (e.g., CSV `"['A', 'B']"`) → parse via literal_eval then serialize
    - string / number / bool → stripped text
    """
    import ast
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        text = json.dumps(value, sort_keys=True, ensure_ascii=False)
        return normalize_whitespace(text)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ""
        # Try standard JSON first (handles JSON strings including double-quoted arrays)
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (list, dict)):
                text = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
                return normalize_whitespace(text)
        except (json.JSONDecodeError, TypeError):
            pass
        # Try Python literal (handles CSV strings like "['A', 'B']" with single quotes)
        try:
            parsed = ast.literal_eval(stripped)
            if isinstance(parsed, (list, dict)):
                text = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
                return normalize_whitespace(text)
        except (ValueError, SyntaxError, TypeError):
            pass
        return normalize_whitespace(stripped)
    text = str(value)
    return normalize_whitespace(text)


def truncate_for_display(value: str, max_len: int = 200) -> str:
    """Truncate a string for dashboard display."""
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


def _compute_file_sha256(path: Path) -> str:
    """Compute SHA256 of a file's contents."""
    if not path.exists():
        return "FILE_NOT_FOUND"
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def dataset_fingerprint(records: list[dict]) -> dict[str, Any]:
    """Compute a deterministic fingerprint of a dataset.

    Returns:
        dict with keys: row_count, row_ids (sorted list), row_hash (paper_id -> sha256),
        file_sha256 ("memory" since we operate on in-memory records).
    """
    row_ids = sorted(set(r.get("paper_id", "") for r in records if r.get("paper_id")))
    row_hash: dict[str, str] = {}

    for record in records:
        pid = record.get("paper_id", "")
        if not pid:
            continue
        canonical = _canonical_json(record)
        row_hash[pid] = hashlib.sha256(canonical.encode()).hexdigest()

    # Compute a pseudo file hash from the canonical sorted JSON of all records
    all_sorted = json.dumps(sorted(records, key=lambda r: r.get("paper_id", "")), sort_keys=True, ensure_ascii=True)
    file_sha256 = hashlib.sha256(all_sorted.encode()).hexdigest()

    return {
        "row_count": len(records),
        "row_ids": row_ids,
        "row_hash": row_hash,
        "file_sha256": file_sha256,
    }


def diff_datasets(before: list[dict], after: list[dict]) -> list[dict]:
    """Compare two datasets and return structured list of changes.

    Each change entry:
        {
          "paper_id": str,
          "change_type": "added" | "removed" | "modified" | "duplicate",
          "fields": [{"field": str, "before": Any, "after": Any}],
          "severity": "low" | "medium" | "high"
        }

    Normalization:
      - Strip and collapse whitespace before comparison
      - Empty string and null are treated as equivalent

    Severity rules:
      - removed row => high
      - duplicate => high
      - critical field blanked (non-empty -> empty) => high
      - other modified => medium
      - added row => low
    """
    changes: list[dict] = []

    # Build lookup maps
    before_map: dict[str, dict] = {}
    for record in before:
        pid = record.get("paper_id", "")
        if pid:
            before_map[pid] = record

    after_map: dict[str, dict] = {}
    for record in after:
        pid = record.get("paper_id", "")
        if pid:
            after_map[pid] = record

    before_ids = set(before_map.keys())
    after_ids = set(after_map.keys())

    # 1. Removed (in before but not in after)
    for pid in sorted(before_ids - after_ids):
        changes.append({
            "paper_id": pid,
            "change_type": "removed",
            "fields": [],
            "severity": "high",
        })

    # 2. Added (in after but not in before)
    for pid in sorted(after_ids - before_ids):
        changes.append({
            "paper_id": pid,
            "change_type": "added",
            "fields": [],
            "severity": "low",
        })

    # 3. Duplicates in after
    after_pid_counts: dict[str, int] = {}
    for record in after:
        pid = record.get("paper_id", "")
        if pid:
            after_pid_counts[pid] = after_pid_counts.get(pid, 0) + 1

    for pid, count in sorted(after_pid_counts.items()):
        if count > 1 and pid in before_ids:
            changes.append({
                "paper_id": pid,
                "change_type": "duplicate",
                "fields": [],
                "severity": "high",
            })

    # 4. Modified (same paper_id, field values differ)
    # Only compare fields that exist in the source (before) record.
    # Ignore CSV-only computed fields like authors_joined, text_for_embedding, etc.
    for pid in sorted(before_ids & after_ids):
        before_rec = before_map[pid]
        after_rec = after_map[pid]

        # Only compare fields present in the source record
        all_fields = sorted(set(list(before_rec.keys())))

        field_diffs = []
        has_modification = False

        for field in all_fields:
            before_val = before_rec.get(field)
            after_val = after_rec.get(field)

            norm_before = _normalize_value(before_val)
            norm_after = _normalize_value(after_val)

            if norm_before != norm_after:
                has_modification = True
                field_diffs.append({
                    "field": field,
                    "before": before_val,
                    "after": after_val,
                })

        if has_modification:
            # Determine severity
            severity = "medium"
            for diff in field_diffs:
                before_str = _normalize_value(diff["before"])
                after_str = _normalize_value(diff["after"])
                field_name = diff["field"].lower()
                # Critical field blanked: non-empty -> empty
                if field_name in CRITICAL_FIELDS and before_str and not after_str:
                    severity = "high"
                    break

            changes.append({
                "paper_id": pid,
                "change_type": "modified",
                "fields": field_diffs,
                "severity": severity,
            })

    return changes


# ---------------------------------------------------------------------------
# Canonical schema helpers (dashboard-safe)
# ---------------------------------------------------------------------------

def safe_get(d: Any, *keys, default=None) -> Any:
    """Safely navigate a nested dict. Returns default if any key is missing or wrong type."""
    current = d
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
        if current is default:
            return default
    return current


def normalize_field_diff(d: Any) -> dict[str, Any]:
    """Normalize a field-diff record to canonical dict schema.

    Canonical schema:
        {"field": str, "before": Any, "after": Any, "action": str}

    Action values: RESTORED | KEPT | UNCHANGED | N/A
    """
    if not isinstance(d, dict):
        # String or other: treat as field name
        if isinstance(d, str):
            return {"field": d, "before": "", "after": "", "action": "N/A"}
        return {"field": "?", "before": "", "after": "", "action": "N/A"}

    field = d.get("field", d.get("name", "?"))
    before = d.get("before", d.get("old", ""))
    after = d.get("after", d.get("new", ""))
    action = d.get("action", "N/A")

    # Infer action from before/after if not explicitly set
    if action == "N/A" or not action:
        norm_before = str(before).strip() if before is not None else ""
        norm_after = str(after).strip() if after is not None else ""
        if norm_before and not norm_after:
            action = "RESTORED"
        elif norm_after and not norm_before:
            action = "KEPT"
        elif norm_before != norm_after:
            action = "RESTORED"
        else:
            action = "UNCHANGED"

    return {
        "field": str(field) if field else "?",
        "before": before,
        "after": after,
        "action": str(action),
    }


def normalize_issue(issue: Any) -> dict[str, Any]:
    """Normalize an issue record to canonical schema.

    Canonical issue schema:
        {
          "paper_id": str,
          "issue_type": str,
          "severity": str,
          "change_type": str,
          "fields": list[dict]  <- each dict is canonical FieldDiff
        }
    """
    if not isinstance(issue, dict):
        return {
            "paper_id": str(issue) if issue else "?",
            "issue_type": "unknown",
            "severity": "low",
            "change_type": "unknown",
            "fields": [],
        }

    paper_id = issue.get("paper_id", "?")
    issue_type = issue.get("issue_type", issue.get("type", "unknown"))
    severity = issue.get("severity", "low")
    change_type = issue.get("change_type", "")

    # Normalize fields
    raw_fields = issue.get("fields", [])
    if isinstance(raw_fields, str):
        raw_fields = [raw_fields]
    elif not isinstance(raw_fields, list):
        raw_fields = []

    canonical_fields = []
    for f in raw_fields:
        canonical_fields.append(normalize_field_diff(f))

    return {
        "paper_id": str(paper_id) if paper_id else "?",
        "issue_type": str(issue_type),
        "severity": str(severity),
        "change_type": str(change_type),
        "fields": canonical_fields,
    }


def load_latest_recovery(project_dir: Path) -> dict[str, Any]:
    """Load the most recent recovery report, fully normalized.

    Returns {} on any error (missing file, parse error, etc.).
    All issues and field diffs are normalized to canonical schema.
    Never raises.
    """
    recovery_dir = project_dir / "data" / "live" / "recovery"
    if not recovery_dir.exists():
        return {}

    try:
        candidates = sorted(recovery_dir.glob("recovery_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not candidates:
            return {}

        report = candidates[0]
        import json
        data = json.loads(report.read_text(encoding="utf-8"))
    except Exception:
        return {}

    # Normalize all issues
    raw_issues = data.get("issues", [])
    if isinstance(raw_issues, list):
        data["issues"] = [normalize_issue(i) for i in raw_issues]
    else:
        data["issues"] = []

    # Ensure detection block
    if "detection" not in data:
        data["detection"] = {}

    # Ensure validation block
    if "validation" not in data:
        data["validation"] = {}

    return data
