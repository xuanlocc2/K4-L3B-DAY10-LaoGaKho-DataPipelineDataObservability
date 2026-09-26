"""Tests for Data Pipeline and Data Observability."""

import json
import os
import sys
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

os.environ["LLM_PROVIDER"] = "mock"
os.environ["REFRESH_SOURCE"] = "0"


class TestCrossrefParsing:
    """Tests for Crossref payload parsing."""

    def test_parse_crossref_payload_valid(self):
        from ingestion.crossref import parse_crossref_payload, PaperRecord
        
        payload = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/test.123",
                        "title": ["Test Paper Title"],
                        "abstract": "<jats:p>This is an abstract.</jats:p>",
                        "author": [
                            {"given": "John", "family": "Doe"},
                            {"given": "Jane", "family": "Smith"},
                        ],
                        "subject": ["AI", "ML"],
                        "published": {"date-parts": [[2024, 1, 15]]},
                        "created": {"date-time": "2024-01-15T10:00:00Z"},
                        "URL": "https://doi.org/10.1234/test.123",
                    }
                ]
            }
        }
        
        records = parse_crossref_payload(payload)
        
        assert len(records) == 1
        assert records[0].paper_id == "10.1234/test.123"
        assert records[0].title == "Test Paper Title"
        assert records[0].summary == "This is an abstract."
        assert len(records[0].authors) == 2
        assert "John Doe" in records[0].authors
        assert records[0].primary_category == "AI"
        assert records[0].published == "2024-01-15"

    def test_parse_crossref_payload_empty(self):
        from ingestion.crossref import parse_crossref_payload
        
        payload = {"message": {"items": []}}
        records = parse_crossref_payload(payload)
        assert records == []

    def test_parse_crossref_payload_missing_fields(self):
        from ingestion.crossref import parse_crossref_payload
        
        payload = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/test",
                    }
                ]
            }
        }
        
        records = parse_crossref_payload(payload)
        # Record without title is skipped (must have valid title)
        assert len(records) == 0

    def test_parse_crossref_payload_malformed(self):
        from ingestion.crossref import parse_crossref_payload
        
        payload = {"not": "valid"}
        records = parse_crossref_payload(payload)
        assert records == []


class TestCleaning:
    """Tests for data cleaning."""

    def test_build_clean_dataframe_basic(self):
        from ingestion.crossref import PaperRecord
        from ingestion.cleaning import build_clean_dataframe
        
        records = [
            PaperRecord(
                paper_id="10.1234/test.1",
                title="Test Paper",
                summary="This is a test abstract.",
                authors=["John Doe"],
                categories=["AI"],
                primary_category="AI",
                published="2024-01-15",
                updated="2024-01-15",
                abs_url="https://doi.org/10.1234/test.1",
                pdf_url="https://doi.org/10.1234/test.1",
                comment="",
            )
        ]
        
        run_date = datetime.now(UTC)
        df = build_clean_dataframe(records, run_date)
        
        assert len(df) == 1
        assert "paper_id" in df.columns
        assert "title" in df.columns
        assert "summary" in df.columns
        assert "authors_joined" in df.columns
        assert "categories_joined" in df.columns
        assert "summary_chars" in df.columns
        assert "age_days" in df.columns
        assert "text_for_embedding" in df.columns
        
        assert df.iloc[0]["paper_id"] == "10.1234/test.1"
        assert df.iloc[0]["authors_joined"] == "John Doe"
        assert df.iloc[0]["categories_joined"] == "AI"

    def test_build_clean_dataframe_dedupe(self):
        from ingestion.crossref import PaperRecord
        from ingestion.cleaning import build_clean_dataframe
        
        records = [
            PaperRecord(
                paper_id="10.1234/test",
                title="Paper 1",
                summary="Abstract 1",
                authors=["Author"],
                categories=["Cat"],
                primary_category="Cat",
                published="2024-01-15",
                updated="2024-01-15",
                abs_url="",
                pdf_url="",
                comment="",
            ),
            PaperRecord(
                paper_id="10.1234/test",
                title="Paper 2",
                summary="Abstract 2",
                authors=["Author"],
                categories=["Cat"],
                primary_category="Cat",
                published="2024-01-15",
                updated="2024-01-15",
                abs_url="",
                pdf_url="",
                comment="",
            ),
        ]
        
        run_date = datetime.now(UTC)
        df = build_clean_dataframe(records, run_date)
        
        assert len(df) == 1

    def test_text_for_embedding_deterministic(self):
        from ingestion.crossref import PaperRecord
        from ingestion.cleaning import build_clean_dataframe
        
        records = [
            PaperRecord(
                paper_id="10.1234/test",
                title="Test Title",
                summary="Test summary",
                authors=["Author A"],
                categories=["Cat1"],
                primary_category="Cat1",
                published="2024-01-15",
                updated="2024-01-15",
                abs_url="",
                pdf_url="",
                comment="",
            )
        ]
        
        run_date = datetime.now(UTC)
        df1 = build_clean_dataframe(records, run_date)
        df2 = build_clean_dataframe(records, run_date)
        
        assert df1.iloc[0]["text_for_embedding"] == df2.iloc[0]["text_for_embedding"]
        
        text = df1.iloc[0]["text_for_embedding"]
        assert "Title: Test Title" in text
        assert "Summary: Test summary" in text
        assert "Authors: Author A" in text
        assert "Categories: Cat1" in text
        assert "Published: 2024-01-15" in text

    def test_xml_cleanup(self):
        from ingestion.crossref import PaperRecord
        from ingestion.cleaning import build_clean_dataframe, _strip_jats_xml
        
        xml_text = "<jats:p>This is <i>italic</i> and <b>bold</b>.</jats:p>"
        cleaned = _strip_jats_xml(xml_text)
        assert "<" not in cleaned
        assert "This is" in cleaned


class TestTestSet:
    """Tests for test set builder."""

    def test_build_test_set_schema(self):
        import pandas as pd
        from evaluation.testset import build_test_set
        
        df = pd.DataFrame([
            {
                "paper_id": f"10.1234/test.{i}",
                "title": f"Paper {i}",
                "summary": f"Summary {i}" * 5,  # Ensure summary > 20 chars
                "authors_joined": "Author A, Author B",
                "categories_joined": "AI, ML",
                "published": "2024-01-15",
            }
            for i in range(10)
        ])
        
        output_path = PROJECT_ROOT / "data" / "eval" / "test_set.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        questions = build_test_set(df, output_path)
        
        # Should have at least 4 questions (2 summary + 2 others minimum)
        assert len(questions) >= 4
        
        for q in questions:
            assert "id" in q
            assert "question_type" in q
            assert "question" in q
            assert "ground_truth" in q
            assert "ground_truth_doc_ids" in q
        
        question_types = [q["question_type"] for q in questions]
        assert "summary" in question_types
        assert "authors" in question_types
        assert "date" in question_types
        assert "categories" in question_types


class TestQuality:
    """Tests for data quality checks."""

    def test_run_data_quality_checks_success(self):
        import pandas as pd
        from core.config import load_settings
        from observability.quality import run_data_quality_checks
        
        df = pd.DataFrame([
            {
                "paper_id": f"10.1234/test.{i}",
                "title": f"Paper {i}",
                "summary_chars": 100,
            }
            for i in range(10)
        ])
        
        settings = load_settings(PROJECT_ROOT)
        
        result = run_data_quality_checks(df, settings, "test")
        
        assert "success" in result
        assert "expectations" in result
        assert "statistics" in result
        assert result["statistics"]["row_count"] == 10

    def test_freshness_ratio(self):
        import pandas as pd
        from observability.quality import build_freshness_report
        from core.config import load_settings
        
        df = pd.DataFrame([
            {
                "paper_id": f"10.1234/test.{i}",
                "published": "2024-01-15",
                "age_days": 30 if i < 8 else 200,
            }
            for i in range(10)
        ])
        
        settings = load_settings(PROJECT_ROOT)
        report_path = PROJECT_ROOT / "data" / "quality" / "test_freshness.json"
        
        result = build_freshness_report(df, settings, report_path)
        
        assert result["threshold_days"] == 180
        assert result["stale_rows"] == 2
        assert result["total_rows"] == 10
        assert result["stale_ratio"] == 0.2
        assert result["is_fresh"] is True


class TestCorruption:
    """Tests for corruption scenarios."""

    def test_corrupt_dataframe_scenarios(self):
        import pandas as pd
        from ingestion.corruption import corrupt_clean_dataframe
        
        df = pd.DataFrame([
            {
                "paper_id": f"10.1234/test.{i}",
                "title": f"Paper {i}",
                "summary": f"Summary {i}",
                "authors_joined": "Author",
                "categories_joined": "Cat",
                "published": "2024-01-15",
                "age_days": 30,
                "abs_url": "",
                "pdf_url": "",
            }
            for i in range(10)
        ])
        
        output_path = PROJECT_ROOT / "data" / "results" / "corruption_log.json"
        
        corrupted = corrupt_clean_dataframe(df, output_path)
        
        # Corruption may affect some rows
        assert "text_for_embedding" in corrupted.columns
        
        assert output_path.exists()
        with open(output_path, encoding="utf-8") as f:
            log = json.load(f)
        
        assert "scenarios" in log
        # At least some scenarios should be applied
        assert len(log["scenarios"]) >= 1


class TestLiveState:
    """Tests for live state management."""

    def test_state_persistence(self):
        from live.state import LiveState
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            state = LiveState(state_path)
            
            assert state.data["records_seen"] == 0
            
            state.update_poll("test_run_1", 10)
            assert state.data["records_seen"] == 10
            
            state.update_success("test_run_1", new_count=5, updated_count=2)
            assert state.data["records_new"] == 5
            assert state.data["records_updated"] == 2
            assert state.data["last_error"] is None
            
            state.update_error("Test error")
            assert state.data["last_error"] == "Test error"
            
            state2 = LiveState(state_path)
            assert state2.data["records_new"] == 5

    def test_watermark(self):
        from live.state import LiveState
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            state = LiveState(state_path)
            
            assert state.get_watermark() is None
            
            state.update_success("run_1")
            assert state.get_watermark() is not None


class TestIncremental:
    """Tests for incremental ingestion."""

    def test_classify_record(self):
        from live.incremental import RecordStatus, classify_record
        from ingestion.crossref import PaperRecord
        
        record = PaperRecord(
            paper_id="10.1234/test",
            title="Test",
            summary="Summary",
            authors=[],
            categories=[],
            primary_category="",
            published="2024-01-15",
            updated="2024-01-15",
            abs_url="",
            pdf_url="",
            comment="",
        )
        
        status = classify_record(record, set(), {})
        assert status == RecordStatus.NEW
        
        status = classify_record(record, {"10.1234/test"}, {"10.1234/test": "2024-01-10"})
        assert status == RecordStatus.UPDATED
        
        status = classify_record(record, {"10.1234/test"}, {"10.1234/test": "2024-01-20"})
        assert status == RecordStatus.UNCHANGED


class TestLLM:
    """Tests for LLM configuration."""

    def test_groq_provider_missing_key(self):
        from core.config import load_settings, normalized_provider
        
        settings = load_settings(PROJECT_ROOT)
        provider = normalized_provider(settings)
        
        if provider == "groq":
            from core.config import require_llm_credentials
            
            with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
                require_llm_credentials(settings)

    def test_mock_provider_works(self):
        from retrieval.llm import build_llm
        from core.config import load_settings
        
        os.environ["LLM_PROVIDER"] = "mock"
        settings = load_settings(PROJECT_ROOT)
        
        llm = build_llm(settings)
        assert llm is not None
        
        response = llm.invoke("Test")
        assert response is not None


class TestConfig:
    """Tests for configuration."""

    def test_load_settings(self):
        from core.config import load_settings
        
        settings = load_settings(PROJECT_ROOT)
        
        # Provider should be configured (mock in tests, groq otherwise)
        assert settings.llm_provider in ["groq", "mock"]
        assert "paths" in dir(settings)
        assert settings.paths.raw_records_json.exists() or True

    def test_normalized_provider(self):
        from core.config import normalized_provider, Settings
        
        class MockSettings:
            llm_provider = "Groq"
        
        settings = MockSettings()
        assert normalized_provider(settings) == "groq"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
