"""Shared output types: lineage edges and data-quality findings.

A DQFinding is the in-memory form of a dq.issues row (handoff 0001). A
LineageEdge is the in-memory form of a lineage.edges row. Normalizers return
these alongside canonical rows; the writer persists them. Nothing here may
ever be optional to emit: a normalizer that detects a problem MUST return a
DQFinding — swallowing it is a guardrail violation (fail loudly).
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Severities allowed by dq.issues CHECK constraint (handoff 0001).
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_BLOCKING = "blocking"

_ALLOWED_SEVERITIES = (SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_BLOCKING)


@dataclass(frozen=True)
class LineageEdge:
    """One derivation edge in lineage.edges (ADR-0007)."""

    output_kind: str
    output_id: str
    transform_name: str
    transform_version: str
    input_kind: str
    input_id: str


@dataclass(frozen=True)
class DQFinding:
    """One data-quality issue destined for dq.issues.

    source_record_ids anchors the finding to the content-addressed raw
    record(s) it arose from, so "explain this issue" traverses to raw ingest.
    """

    issue_type: str
    severity: str
    title: str
    description: str
    source_record_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.severity not in _ALLOWED_SEVERITIES:
            raise ValueError(
                f"severity {self.severity!r} not in {_ALLOWED_SEVERITIES}"
            )
