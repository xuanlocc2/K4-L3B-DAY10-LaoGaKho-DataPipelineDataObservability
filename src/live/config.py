from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


LIVE_COLLECTION_NAME = "papers-live"
LIVE_DATASET_PATH_KEY = "data/clean/papers_clean.csv"


@dataclass
class LiveConfig:
    """Configuration for live ingestion pipeline."""
    poll_interval_seconds: int = 30
    overlap_seconds: int = 20
    max_results: int = 50
    auto_repair: bool = True
    auto_recover: bool = False
    collection_name: str = LIVE_COLLECTION_NAME
    query: str = ""
    filter_str: str = ""
    monitor_target: Path = Path(LIVE_DATASET_PATH_KEY)
    monitor_target_override: str | None = None

    @property
    def monitor_target_str(self) -> str:
        return str(self.monitor_target)

    @classmethod
    def from_env(cls) -> "LiveConfig":
        """Load live configuration from environment variables."""
        raw_target = os.getenv("LIVE_MONITOR_TARGET", LIVE_DATASET_PATH_KEY)
        # Resolve relative to project root
        project_dir = Path(__file__).resolve().parents[2]
        monitor_target = project_dir / raw_target
        return cls(
            poll_interval_seconds=int(os.getenv("LIVE_POLL_INTERVAL_SECONDS", "30")),
            overlap_seconds=int(os.getenv("LIVE_INDEX_OVERLAP_SECONDS", "20")),
            max_results=int(os.getenv("LIVE_MAX_RESULTS", "50")),
            auto_repair=os.getenv("LIVE_AUTO_REPAIR", "true").lower() in {"1", "true", "yes"},
            auto_recover=os.getenv("LIVE_AUTO_RECOVER", "false").lower() in {"1", "true", "yes"},
            collection_name=os.getenv("LIVE_COLLECTION_NAME", LIVE_COLLECTION_NAME),
            query=os.getenv("LIVE_QUERY", ""),
            filter_str=os.getenv("LIVE_FILTER", ""),
            monitor_target=Path(monitor_target),
            monitor_target_override=os.getenv("LIVE_MONITOR_TARGET_OVERRIDE") or None,
        )
