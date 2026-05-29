"""Compatibility wrapper for the full-set POC planner.

The reusable implementation lives in ``autodj_analysis.full_set_planner`` so it
can be promoted into supported CLI commands and tested without importing from a
tools script path.
"""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKER_SRC = PROJECT_ROOT / "analysis" / "worker-python" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from autodj_analysis.full_set_planner import main


if __name__ == "__main__":
    raise SystemExit(main())
