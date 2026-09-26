"""Tests for recovery, diff, and monitoring modules.

These tests do NOT make live API calls (no network). All file operations use
tmp_path fixtures.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# Helper: build a minimal Paths object with all required fields
# ---------------------------------------------------------------------------

def _make_paths(project_root: Path) -> "Paths":
    """Create a minimal Paths object with all required fields for testing."""
    from core.config import Paths
    data = project_root / "data"
    raw = data / "raw"
    clean = data / "clean"
    return Paths(
        project_dir=project_root,
        workspace_dir=project_root.parent,
        raw_api_response=raw / "crossref_response.json",
        raw_records_json=raw / "crossref_records.json",
        clean_csv=clean / "papers_clean.csv",
        clean_json=clean / "papers_clean.json",
        chroma_dir=data / "chroma",
        embeddings_json=data / "embeddings" / "papers_embeddings.json",
        corrupted_clean_csv=clean / "papers_clean_corrupted.csv",
        corrupted_clean_json=clean / "papers_clean_corrupted.json",
        corrupted_embeddings_json=data / "embeddings" / "papers_embeddings_corrupted.json",
        repaired_clean_csv=clean / "papers_clean_repaired.csv",
        repaired_clean_json=clean / "papers_clean_repaired.json",
        repaired_embeddings_json=data / "embeddings" / "papers_embeddings_repaired.json",
        eval_testset=data / "eval" / "test_set.json",
        baseline_metrics=data / "results" / "baseline_metrics.json",
        baseline_answers=data / "results" / "baseline_answers.json",
        demo_answers=data / "results" / "demo_answers.json",
        quality_dir=data / "quality",
        gx_dir=data / "quality" / "gx",
        baseline_quality_report=data / "quality" / "baseline_quality_report.json",
        corrupted_quality_report=data / "quality" / "corrupted_quality_report.json",
        freshness_report=data / "quality" / "freshness_report.json",
        baseline_report=project_root / "data" / "reports" / "phase1_report.md",
        corruption_log=data / "results" / "corruption_log.json",
        corrupted_metrics=data / "results" / "corrupted_metrics.json",
        corrupted_answers=data / "results" / "corrupted_answers.json",
        repaired_metrics=data / "results" / "repaired_metrics.json",
        repaired_answers=data / "results" / "repaired_answers.json",
        comparison_report=project_root / "data" / "reports" / "corruption_report.md",
        live_recovery_dir=data / "live" / "recovery",
        live_known_good_fingerprint=data / "live" / "known_good_fingerprint.json",
        live_dataset_csv=clean / "papers_clean.csv",
        live_dataset_json=clean / "papers_clean.json",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_records():
    """24 sample paper records."""
    records = []
    for i in range(24):
        records.append({
            "paper_id": f"10.1234/test.{i:02d}",
            "title": f"Paper Title {i}",
            "summary": f"This is the summary for paper {i}.",
            "authors": [f"Author {j}" for j in range(i % 3 + 1)],
            "categories": ["AI", "ML"],
            "primary_category": "AI",
            "published": "2024-01-15",
            "updated": "2024-01-15",
            "abs_url": f"https://doi.org/10.1234/test.{i:02d}",
            "pdf_url": "",
            "comment": "",
        })
    return records


@pytest.fixture
def project_root(tmp_path):
    """A minimal project directory with required subdirectories."""
    data = tmp_path / "data"
    raw = data / "raw"
    clean = data / "clean"
    live = data / "live"
    events = live / "events"
    quarantine = live / "quarantine"
    recovery = live / "recovery"
    for d in [raw, clean, live, events, quarantine, recovery,
              data / "quality", data / "embeddings", data / "chroma"]:
        d.mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---------------------------------------------------------------------------
# diff.py tests
# ---------------------------------------------------------------------------


class TestDatasetFingerprint:
    def test_fingerprint_stable(self, sample_records):
        """Same records produce identical fingerprint."""
        from observability.diff import dataset_fingerprint

        fp1 = dataset_fingerprint(sample_records)
        fp2 = dataset_fingerprint(copy.deepcopy(sample_records))

        assert fp1["row_count"] == fp2["row_count"]
        assert fp1["file_sha256"] == fp2["file_sha256"]
        assert fp1["row_ids"] == fp2["row_ids"]

    def test_fingerprint_changes_on_modification(self, sample_records):
        """Modified record changes the fingerprint."""
        from observability.diff import dataset_fingerprint

        fp1 = dataset_fingerprint(sample_records)
        modified = copy.deepcopy(sample_records)
        modified[0]["title"] = "Modified Title"
        fp2 = dataset_fingerprint(modified)

        assert fp1["file_sha256"] != fp2["file_sha256"]
        assert fp1["row_hash"][modified[0]["paper_id"]] != fp2["row_hash"][modified[0]["paper_id"]]

    def test_fingerprint_counts(self, sample_records):
        from observability.diff import dataset_fingerprint

        fp = dataset_fingerprint(sample_records)
        assert fp["row_count"] == 24
        assert len(fp["row_ids"]) == 24
        assert len(fp["row_hash"]) == 24


class TestDiffDatasets:
    def test_diff_added(self, sample_records):
        from observability.diff import diff_datasets

        before = sample_records[:20]
        after = sample_records[:20] + sample_records[20:]

        changes = diff_datasets(before, after)
        added = [c for c in changes if c["change_type"] == "added"]
        removed = [c for c in changes if c["change_type"] == "removed"]

        assert len(added) == 4
        assert len(removed) == 0

    def test_diff_removed(self, sample_records):
        from observability.diff import diff_datasets

        before = copy.deepcopy(sample_records)
        after = sample_records[:20]

        changes = diff_datasets(before, after)
        removed = [c for c in changes if c["change_type"] == "removed"]
        added = [c for c in changes if c["change_type"] == "added"]

        assert len(removed) == 4
        assert len(added) == 0
        for c in removed:
            assert c["severity"] == "high"

    def test_diff_modified(self, sample_records):
        from observability.diff import diff_datasets

        before = copy.deepcopy(sample_records)
        after = copy.deepcopy(sample_records)
        after[5]["title"] = "Completely Different Title"

        changes = diff_datasets(before, after)
        modified = [c for c in changes if c["change_type"] == "modified"]

        assert len(modified) == 1
        assert modified[0]["paper_id"] == after[5]["paper_id"]
        assert len(modified[0]["fields"]) == 1
        assert modified[0]["fields"][0]["field"] == "title"
        assert modified[0]["severity"] == "medium"

    def test_diff_duplicate(self, sample_records):
        from observability.diff import diff_datasets

        before = copy.deepcopy(sample_records[:20])
        after = copy.deepcopy(sample_records[:20]) + [copy.deepcopy(sample_records[5])]

        changes = diff_datasets(before, after)
        duplicates = [c for c in changes if c["change_type"] == "duplicate"]

        assert len(duplicates) == 1
        assert duplicates[0]["paper_id"] == sample_records[5]["paper_id"]
        assert duplicates[0]["severity"] == "high"

    def test_diff_normalizes_whitespace(self, sample_records):
        from observability.diff import diff_datasets

        before = copy.deepcopy(sample_records)
        after = copy.deepcopy(sample_records)
        after[3]["title"] = "  Paper   Title   3  "  # Extra spaces

        changes = diff_datasets(before, after)
        # Normalized whitespace should NOT appear as a modification
        modified = [c for c in changes if c["paper_id"] == after[3]["paper_id"] and c["change_type"] == "modified"]
        assert len(modified) == 0

    def test_diff_critical_field_blanked(self, sample_records):
        from observability.diff import diff_datasets

        before = copy.deepcopy(sample_records)
        after = copy.deepcopy(sample_records)
        after[7]["summary"] = ""  # Critical field blanked

        changes = diff_datasets(before, after)
        modified = [c for c in changes if c["paper_id"] == after[7]["paper_id"] and c["change_type"] == "modified"]

        assert len(modified) == 1
        assert modified[0]["severity"] == "high"

    def test_diff_empty_before(self, sample_records):
        from observability.diff import diff_datasets

        changes = diff_datasets([], sample_records[:5])
        added = [c for c in changes if c["change_type"] == "added"]

        assert len(added) == 5
        for c in added:
            assert c["severity"] == "low"

    def test_diff_empty_after(self, sample_records):
        from observability.diff import diff_datasets

        changes = diff_datasets(sample_records[:5], [])
        removed = [c for c in changes if c["change_type"] == "removed"]

        assert len(removed) == 5
        for c in removed:
            assert c["severity"] == "high"


class TestTruncateForDisplay:
    def test_truncate_short(self):
        from observability.diff import truncate_for_display

        assert truncate_for_display("short") == "short"
        assert truncate_for_display("short", max_len=10) == "short"

    def test_truncate_long(self):
        from observability.diff import truncate_for_display

        long_str = "a" * 300
        result = truncate_for_display(long_str, max_len=50)
        assert len(result) == 50
        assert result.endswith("...")


# ---------------------------------------------------------------------------
# recovery.py tests
# ---------------------------------------------------------------------------


class TestQuarantineAndRecovery:
    def test_quarantine_and_recovery_artifact_paths(self, sample_records, project_root):
        """Smoke test: detect_and_recover runs against temp fixture and writes recovery JSON."""
        from observability.diff import dataset_fingerprint, diff_datasets

        # Write source records
        raw_dir = project_root / "data" / "raw"
        source_path = raw_dir / "crossref_records.json"
        source_path.write_text(json.dumps(sample_records, indent=2), encoding="utf-8")

        # Write a (slightly corrupted) target file
        target_dir = project_root / "data" / "clean"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "papers_clean.json"
        corrupted = sample_records[:23]  # missing last record
        target_path.write_text(json.dumps(corrupted, indent=2), encoding="utf-8")

        # Write quality dir
        (project_root / "data" / "quality").mkdir(parents=True, exist_ok=True)

        # Create a mock settings
        from core.config import Settings
        paths = _make_paths(project_root)

        settings = Settings(
            llm_provider="mock",
            model_name="mock",
            google_api_key=None,
            openai_api_key=None,
            anthropic_api_key=None,
            openrouter_api_key=None,
            openrouter_base_url="",
            ollama_base_url="",
            custom_llm_api_key=None,
            custom_llm_base_url=None,
            groq_api_key=None,
            groq_base_url="",
            groq_model="mock",
            groq_temperature=0.1,
            groq_max_tokens=100,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            baseline_collection_name="papers-baseline",
            corrupted_collection_name="papers-corrupted",
            repaired_collection_name="papers-repaired",
            source_api="Crossref",
            source_query="test",
            source_filter="",
            max_results=24,
            top_k=4,
            freshness_threshold_days=180,
            refresh_source=False,
            refresh_test_set=False,
            paths=paths,
            live_recovery_target_file=None,
        )

        from live.config import LiveConfig
        from live.incremental import generate_run_id
        from live.recovery import detect_and_recover

        live_config = LiveConfig(auto_repair=False, auto_recover=False)
        run_id = generate_run_id()

        report = detect_and_recover(settings, live_config, run_id, target_path=target_path)

        # Verify report structure
        assert "run_id" in report
        assert "status" in report
        assert "detection" in report
        assert "issues" in report
        assert "repair" in report
        assert "embedding" in report
        assert "index" in report
        assert "validation" in report

        # Verify report was written
        recovery_dir = project_root / "data" / "live" / "recovery"
        assert recovery_dir.exists()
        report_files = list(recovery_dir.glob("recovery_*.json"))
        assert len(report_files) == 1

        # Verify quarantine file was created
        quarantine_dir = project_root / "data" / "live" / "quarantine"
        assert quarantine_dir.exists()
        quarantine_files = list(quarantine_dir.glob("*.json"))
        assert len(quarantine_files) >= 1

        # Detection: records_before=source (24), records_after=current (23, missing 1)
        det = report["detection"]
        assert det["records_before"] == 24, f"expected source 24 records, got {det['records_before']}"
        assert det["records_after"] == 23, f"expected current 23 records, got {det['records_after']}"
        assert det["issues_detected"] >= 1

        # Recovery should have restored the missing record
        repair = report["repair"]
        assert repair["records_restored"] >= 1

        # Target file should now have 24 records
        restored = json.loads(target_path.read_text(encoding="utf-8"))
        assert len(restored) == 24

    def test_no_change_detection(self, sample_records, project_root):
        """When target matches source, status should reflect no high-severity issues."""
        from core.config import Settings
        from live.config import LiveConfig
        from live.incremental import generate_run_id
        from live.recovery import detect_and_recover

        raw_dir = project_root / "data" / "raw"
        source_path = raw_dir / "crossref_records.json"
        source_path.write_text(json.dumps(sample_records, indent=2), encoding="utf-8")

        target_dir = project_root / "data" / "clean"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "papers_clean.json"
        target_path.write_text(json.dumps(copy.deepcopy(sample_records), indent=2), encoding="utf-8")

        (project_root / "data" / "quality").mkdir(parents=True, exist_ok=True)

        paths = _make_paths(project_root)

        settings = Settings(
            llm_provider="mock", model_name="mock",
            google_api_key=None, openai_api_key=None, anthropic_api_key=None,
            openrouter_api_key=None, openrouter_base_url="", ollama_base_url="",
            custom_llm_api_key=None, custom_llm_base_url=None,
            groq_api_key=None, groq_base_url="", groq_model="mock",
            groq_temperature=0.1, groq_max_tokens=100,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            baseline_collection_name="p-base", corrupted_collection_name="p-corrupt",
            repaired_collection_name="p-repair",
            source_api="Crossref", source_query="test", source_filter="",
            max_results=24, top_k=4, freshness_threshold_days=180,
            refresh_source=False, refresh_test_set=False,
            paths=paths, live_recovery_target_file=None,
        )

        live_config = LiveConfig(auto_repair=False, auto_recover=False)
        run_id = generate_run_id()
        report = detect_and_recover(settings, live_config, run_id, target_path=target_path)

        # No high-severity issues → status success, no restoration needed
        assert report["status"] == "success"
        assert report["repair"]["records_restored"] == 0


# ---------------------------------------------------------------------------
# monitor.py tests
# ---------------------------------------------------------------------------


class TestMonitor:
    def test_check_target_for_change_baseline(self, sample_records, project_root):
        """First run establishes baseline; subsequent identical run shows no change."""
        from core.config import Settings
        from live.monitor import check_target_for_change

        target_dir = project_root / "data" / "clean"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "papers_clean.json"
        target_path.write_text(json.dumps(sample_records, indent=2), encoding="utf-8")

        paths = _make_paths(project_root)

        settings = Settings(
            llm_provider="mock", model_name="mock",
            google_api_key=None, openai_api_key=None, anthropic_api_key=None,
            openrouter_api_key=None, openrouter_base_url="", ollama_base_url="",
            custom_llm_api_key=None, custom_llm_base_url=None,
            groq_api_key=None, groq_base_url="", groq_model="mock",
            groq_temperature=0.1, groq_max_tokens=100,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            baseline_collection_name="p-base", corrupted_collection_name="p-corrupt",
            repaired_collection_name="p-repair",
            source_api="Crossref", source_query="test", source_filter="",
            max_results=24, top_k=4, freshness_threshold_days=180,
            refresh_source=False, refresh_test_set=False,
            paths=paths, live_recovery_target_file=None,
        )

        # First call: establishes baseline
        changed1, diff1 = check_target_for_change(settings, target_path)
        assert changed1 is False
        assert diff1["event"] == "baseline_established"

        # Second call with identical data: no change
        changed2, diff2 = check_target_for_change(settings, target_path)
        assert changed2 is False
        assert diff2["event"] == "no_change"

    def test_check_target_for_change_detects_modification(self, sample_records, project_root):
        """Changing the file is detected as a change."""
        from core.config import Settings
        from live.monitor import check_target_for_change

        target_dir = project_root / "data" / "clean"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "papers_clean.json"
        target_path.write_text(json.dumps(sample_records, indent=2), encoding="utf-8")

        paths = _make_paths(project_root)

        settings = Settings(
            llm_provider="mock", model_name="mock",
            google_api_key=None, openai_api_key=None, anthropic_api_key=None,
            openrouter_api_key=None, openrouter_base_url="", ollama_base_url="",
            custom_llm_api_key=None, custom_llm_base_url=None,
            groq_api_key=None, groq_base_url="", groq_model="mock",
            groq_temperature=0.1, groq_max_tokens=100,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            baseline_collection_name="p-base", corrupted_collection_name="p-corrupt",
            repaired_collection_name="p-repair",
            source_api="Crossref", source_query="test", source_filter="",
            max_results=24, top_k=4, freshness_threshold_days=180,
            refresh_source=False, refresh_test_set=False,
            paths=paths, live_recovery_target_file=None,
        )

        # Establish baseline
        check_target_for_change(settings, target_path)

        # Modify file: drop one record
        modified = copy.deepcopy(sample_records[:23])
        target_path.write_text(json.dumps(modified, indent=2), encoding="utf-8")

        changed, diff = check_target_for_change(settings, target_path)
        assert changed is True
        assert diff["event"] == "change_detected"
        assert diff["file_sha256_changed"] is True


# ---------------------------------------------------------------------------
# Phase 6: Canonical schema, normalization, and pipeline tests
# ---------------------------------------------------------------------------

class TestCanonicalFieldDiff:
    def test_field_diff_canonical_schema(self, sample_records):
        """Issues produced by detect_and_recover have canonical field schema."""
        from observability.diff import normalize_field_diff

        # String input
        result = normalize_field_diff("title")
        assert isinstance(result, dict)
        assert result["field"] == "title"
        assert "action" in result

        # Dict with all keys
        result = normalize_field_diff({"field": "summary", "before": "old", "after": "new"})
        assert result["field"] == "summary"
        assert result["before"] == "old"
        assert result["after"] == "new"
        assert result["action"] in ("RESTORED", "UNCHANGED")

        # Dict with missing keys fills defaults
        result = normalize_field_diff({"field": "authors"})
        assert result["field"] == "authors"
        assert result["before"] == ""
        assert result["after"] == ""

        # Non-dict, non-string returns ?
        result = normalize_field_diff(None)
        assert result["field"] == "?"

    def test_normalize_field_diff_handles_strings_and_dicts(self):
        """normalize_field_diff correctly handles both string and dict inputs."""
        from observability.diff import normalize_field_diff

        # String → dict with N/A action
        result = normalize_field_diff("title")
        assert isinstance(result, dict)
        assert result["field"] == "title"
        assert result["action"] == "N/A"

        # Dict with before/after
        result = normalize_field_diff({"field": "summary", "before": "old abstract", "after": ""})
        assert result["field"] == "summary"
        assert result["action"] == "RESTORED"

        # Dict missing standard keys → falls back to 'name' if present
        result = normalize_field_diff({"name": "authors"})  # 'name' is a recognized fallback for 'field'
        assert result["field"] == "authors"

    def test_normalize_issue_canonical(self):
        """normalize_issue always returns canonical schema with list of dict fields."""
        from observability.diff import normalize_issue

        # String fields → canonical
        issue = {
            "paper_id": "10.1234/test.00",
            "issue_type": "missing_record",
            "severity": "high",
            "fields": ["title", "summary"],
        }
        result = normalize_issue(issue)
        assert isinstance(result, dict)
        assert result["paper_id"] == "10.1234/test.00"
        assert isinstance(result["fields"], list)
        for f in result["fields"]:
            assert isinstance(f, dict)
            assert "field" in f
            assert "before" in f
            assert "after" in f
            assert "action" in f

        # Already canonical dict fields → preserved
        issue2 = {
            "paper_id": "10.1234/test.01",
            "issue_type": "modified_field",
            "severity": "high",
            "fields": [{"field": "title", "before": "A", "after": "B", "action": "RESTORED"}],
        }
        result2 = normalize_issue(issue2)
        assert result2["fields"][0]["field"] == "title"

    def test_load_latest_recovery_normalizes_malformed(self, project_root):
        """load_latest_recovery returns safe {} on missing/malformed files."""
        from observability.diff import load_latest_recovery

        # No recovery dir → {}
        result = load_latest_recovery(project_root)
        assert result == {}

        # Malformed JSON
        rec_dir = project_root / "data" / "live" / "recovery"
        rec_dir.mkdir(parents=True, exist_ok=True)
        (rec_dir / "recovery_bad.json").write_text("not json{{{", encoding="utf-8")

        result = load_latest_recovery(project_root)
        assert result == {}

    def test_load_latest_recovery_normalizes_fields(self, project_root):
        """load_latest_recovery normalizes malformed issues to canonical schema."""
        from observability.diff import load_latest_recovery

        rec_dir = project_root / "data" / "live" / "recovery"
        rec_dir.mkdir(parents=True, exist_ok=True)

        # Write a recovery report with malformed fields (string instead of dict)
        bad_report = {
            "run_id": "test_run",
            "status": "success",
            "detection": {},
            "issues": [
                {
                    "paper_id": "10.1234/test.00",
                    "issue_type": "missing_record",
                    "severity": "high",
                    "fields": ["title", "summary"],  # strings, not dicts
                },
                {
                    "paper_id": "10.1234/test.01",
                    "issue_type": "modified_field",
                    "severity": "high",
                    "fields": [{"field": "title", "before": "X", "after": ""}],
                },
            ],
            "validation": {},
        }
        import json
        (rec_dir / "recovery_test.json").write_text(json.dumps(bad_report), encoding="utf-8")

        result = load_latest_recovery(project_root)

        # String fields should be normalized to dicts
        issue0 = result["issues"][0]
        assert isinstance(issue0["fields"][0], dict)
        assert issue0["fields"][0]["field"] == "title"
        assert issue0["fields"][0]["action"] == "N/A"

        # Already-canonical fields should be preserved
        issue1 = result["issues"][1]
        assert issue1["fields"][0]["field"] == "title"
        assert issue1["fields"][0]["action"] in ("RESTORED", "UNCHANGED")


class TestLiveDatasetConfig:
    def test_canonical_live_dataset_path_constant(self):
        """LIVE_DATASET_PATH_KEY is data/clean/papers_clean.csv."""
        from live.config import LIVE_DATASET_PATH_KEY
        assert LIVE_DATASET_PATH_KEY == "data/clean/papers_clean.csv"

    def test_live_config_resolves_to_csv(self):
        """LiveConfig.monitor_target resolves to papers_clean.csv path."""
        from live.config import LiveConfig
        cfg = LiveConfig()
        assert cfg.monitor_target.name == "papers_clean.csv"


class TestFingerprint:
    def test_fingerprint_detects_content_change(self, project_root, sample_records):
        """SHA256 fingerprint changes when content changes."""
        from observability.diff import dataset_fingerprint

        fp1 = dataset_fingerprint(sample_records)
        modified = copy.deepcopy(sample_records)
        modified[0]["title"] = "Hacked Title"
        fp2 = dataset_fingerprint(modified)

        assert fp1["file_sha256"] != fp2["file_sha256"]
        assert fp1["row_count"] == fp2["row_count"]

    def test_fingerprint_ignores_mtime_alone(self, project_root):
        """Same content written twice → same SHA256 (mtime differs)."""
        import time
        from observability.diff import dataset_fingerprint

        records = [{"paper_id": "10.1234/test.00", "title": "Test"}]
        path = project_root / "test.json"

        import json
        path.write_text(json.dumps(records), encoding="utf-8")
        fp1 = dataset_fingerprint(records)

        time.sleep(0.1)
        path.write_text(json.dumps(records), encoding="utf-8")
        fp2 = dataset_fingerprint(records)

        # Same content → same SHA256
        assert fp1["file_sha256"] == fp2["file_sha256"]


class TestDetectionScenarios:
    def test_missing_record_detection(self, project_root, sample_records):
        """Removing a record from dataset → issue includes missing paper_id."""
        from observability.diff import diff_datasets

        before = sample_records
        after = sample_records[:23]  # missing last record
        missing_pid = sample_records[23]["paper_id"]

        changes = diff_datasets(before, after)
        removed = [c for c in changes if c["change_type"] == "removed"]
        assert len(removed) == 1
        assert removed[0]["paper_id"] == missing_pid
        assert removed[0]["severity"] == "high"

    def test_modified_record_detection(self, project_root, sample_records):
        """Blanking a critical field → modified change with high severity."""
        from observability.diff import diff_datasets

        before = copy.deepcopy(sample_records)
        after = copy.deepcopy(sample_records)
        after[0]["summary"] = ""  # critical field blanked

        changes = diff_datasets(before, after)
        modified = [c for c in changes if c["change_type"] == "modified"]
        assert len(modified) == 1
        assert modified[0]["paper_id"] == sample_records[0]["paper_id"]
        assert modified[0]["severity"] == "high"
        assert any(f["field"] == "summary" for f in modified[0]["fields"])

    def test_duplicate_detection(self, project_root, sample_records):
        """Duplicate paper_id in dataset → duplicate change with high severity."""
        from observability.diff import diff_datasets

        before = sample_records[:20]
        after = sample_records[:20] + [copy.deepcopy(sample_records[5])]

        changes = diff_datasets(before, after)
        duplicates = [c for c in changes if c["change_type"] == "duplicate"]
        assert len(duplicates) == 1
        assert duplicates[0]["paper_id"] == sample_records[5]["paper_id"]
        assert duplicates[0]["severity"] == "high"

    def test_recovery_writes_quarantine_and_does_not_overwrite_source(self, project_root, sample_records):
        """Recovery creates quarantine, does NOT overwrite source raw data."""
        from core.config import Settings
        from live.config import LiveConfig
        from live.incremental import generate_run_id
        from live.recovery import detect_and_recover

        # Source: raw records
        raw_dir = project_root / "data" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        source_path = raw_dir / "crossref_records.json"
        import json
        source_path.write_text(json.dumps(sample_records, indent=2), encoding="utf-8")
        source_sha_before = source_path.read_bytes()

        # Target: corrupted (missing one record)
        target_dir = project_root / "data" / "clean"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "papers_clean.json"
        target_path.write_text(json.dumps(sample_records[:23], indent=2), encoding="utf-8")

        (project_root / "data" / "quality").mkdir(parents=True, exist_ok=True)

        paths = _make_paths(project_root)
        settings = Settings(
            llm_provider="mock", model_name="mock",
            google_api_key=None, openai_api_key=None, anthropic_api_key=None,
            openrouter_api_key=None, openrouter_base_url="", ollama_base_url="",
            custom_llm_api_key=None, custom_llm_base_url=None,
            groq_api_key=None, groq_base_url="", groq_model="mock",
            groq_temperature=0.1, groq_max_tokens=100,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            baseline_collection_name="p-base", corrupted_collection_name="p-corrupt",
            repaired_collection_name="p-repair",
            source_api="Crossref", source_query="test", source_filter="",
            max_results=24, top_k=4, freshness_threshold_days=180,
            refresh_source=False, refresh_test_set=False,
            paths=paths, live_recovery_target_file=None,
        )
        live_config = LiveConfig(auto_repair=False, auto_recover=False)
        run_id = generate_run_id()
        report = detect_and_recover(settings, live_config, run_id, target_path=target_path)

        # Quarantine must exist
        quarantine_dir = project_root / "data" / "live" / "quarantine"
        assert quarantine_dir.exists()
        assert len(list(quarantine_dir.glob("*.json"))) >= 1

        # Source raw data must NOT have been modified
        source_sha_after = source_path.read_bytes()
        assert source_sha_before == source_sha_after

        # Target must be restored to original count
        restored_data = json.loads(target_path.read_text(encoding="utf-8"))
        assert len(restored_data) == 24

    def test_recovery_report_schema_valid(self, project_root, sample_records):
        """Recovery report has all required top-level keys."""
        from core.config import Settings
        from live.config import LiveConfig
        from live.incremental import generate_run_id
        from live.recovery import detect_and_recover

        raw_dir = project_root / "data" / "raw"
        source_path = raw_dir / "crossref_records.json"
        import json
        source_path.write_text(json.dumps(sample_records, indent=2), encoding="utf-8")

        target_dir = project_root / "data" / "clean"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "papers_clean.json"
        target_path.write_text(json.dumps(sample_records[:23], indent=2), encoding="utf-8")

        (project_root / "data" / "quality").mkdir(parents=True, exist_ok=True)

        paths = _make_paths(project_root)
        settings = Settings(
            llm_provider="mock", model_name="mock",
            google_api_key=None, openai_api_key=None, anthropic_api_key=None,
            openrouter_api_key=None, openrouter_base_url="", ollama_base_url="",
            custom_llm_api_key=None, custom_llm_base_url=None,
            groq_api_key=None, groq_base_url="", groq_model="mock",
            groq_temperature=0.1, groq_max_tokens=100,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            baseline_collection_name="p-base", corrupted_collection_name="p-corrupt",
            repaired_collection_name="p-repair",
            source_api="Crossref", source_query="test", source_filter="",
            max_results=24, top_k=4, freshness_threshold_days=180,
            refresh_source=False, refresh_test_set=False,
            paths=paths, live_recovery_target_file=None,
        )
        live_config = LiveConfig(auto_repair=False, auto_recover=False)
        run_id = generate_run_id()
        report = detect_and_recover(settings, live_config, run_id, target_path=target_path)

        # All required top-level keys
        assert "run_id" in report
        assert "status" in report
        assert "detection" in report
        assert "issues" in report
        assert "recovery_source" in report
        assert "repair" in report
        assert "embedding" in report
        assert "index" in report
        assert "validation" in report
        assert "events" in report


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
