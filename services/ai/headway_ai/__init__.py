"""headway_ai — the Headway AI layer's foundation increment.

Ships exactly two things, in the order the AI Systems Engineer role
mandates:

1. A pluggable text-generation provider abstraction whose every output is
   structurally labeled AI-generated (`provider.py`).
2. The grounding evaluation harness (`claims.py`, `grounding.py`,
   `regression.py`) — built BEFORE any feature that emits output, so that
   citation resolution and zero-fabrication are provable from the first
   flag onward.

HARD BOUNDARY (see .claude/roles/AI_SYSTEMS_ENGINEER.md): nothing in this
package computes, estimates, or adjusts a reported number. The harness
only *verifies* that AI text cites real records and contains no numeric
token absent from the calculation library's computed results.
"""

from headway_ai.claims import Claim, GroundedDraft
from headway_ai.grounding import (
    CitationResult,
    EvalReport,
    FabricationResult,
    check_citations,
    check_fabrication,
    evaluate,
    extract_numeric_tokens,
    normalize_number,
)
from headway_ai.provider import LabeledOutput, OllamaProvider, Provider, StubProvider

__all__ = [
    "Claim",
    "CitationResult",
    "EvalReport",
    "FabricationResult",
    "GroundedDraft",
    "LabeledOutput",
    "OllamaProvider",
    "Provider",
    "StubProvider",
    "check_citations",
    "check_fabrication",
    "evaluate",
    "extract_numeric_tokens",
    "normalize_number",
]
