"""
Understanding package.

- term_extraction.py    existing single-word candidate extraction used
                         by core.py for knowledge lookups (unchanged).
- engine.py              new: UnderstandingEngine, the foundation layer
                         described in this stage's task - normalizes,
                         detects language, tokenizes, classifies
                         sentence type, and extracts candidate
                         entities/relations from natural-language input.
- result.py              new: UnderstandingResult, the structured
                         output of UnderstandingEngine.understand().

Re-exported here for convenient `from understanding import ...` access;
existing `from understanding.term_extraction import extract_candidate_terms`
imports (used by core.py) keep working unchanged.
"""

from .engine import UnderstandingEngine
from .result import UnderstandingResult

__all__ = ["UnderstandingEngine", "UnderstandingResult"]
