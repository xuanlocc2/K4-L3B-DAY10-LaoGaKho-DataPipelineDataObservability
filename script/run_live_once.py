from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

import json
import time

from core.config import load_settings
from core.utils import ensure_parent
from live.config import LiveConfig
from live.pipeline import run_once
from live.state import LiveState


def main() -> int:
    """Run live ingestion pipeline once and print summary."""
    settings = load_settings()
    live_config = LiveConfig.from_env()
    
    state = LiveState(settings.paths.project_dir / "data" / "live" / "state.json")
    
    result = run_once(settings, live_config, state)
    
    print(json.dumps(result, indent=2))
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
