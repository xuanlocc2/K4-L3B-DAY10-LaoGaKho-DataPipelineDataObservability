from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from pipelines.phase1 import main


if __name__ == "__main__":
    raise SystemExit(main())
