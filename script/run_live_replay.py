from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

import json

from live.replay import replay_run


def main() -> int:
    """Replay a captured raw Crossref response through the pipeline."""
    if len(sys.argv) < 2:
        print("Usage: python run_live_replay.py <run_id>")
        print("Example: python run_live_replay.py live_20260926_100000_123456")
        return 1
    
    run_id = sys.argv[1]
    
    result = replay_run(run_id)
    
    print(json.dumps(result, indent=2))
    
    if not result.get("success", True) and "error" in result:
        return 1
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
