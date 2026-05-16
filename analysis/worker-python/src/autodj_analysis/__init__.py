"""AutoDJ offline analysis worker stub."""

__version__ = "0.1.0"

from .analyze import analyze_stub, build_analyzed_track_stub
from .genre import classify_stub

__all__ = [
    "__version__",
    "analyze_stub",
    "build_analyzed_track_stub",
    "classify_stub",
]
