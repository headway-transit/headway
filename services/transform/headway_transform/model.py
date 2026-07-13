"""Shared output types: lineage edges and data-quality findings.

A DQFinding is the in-memory form of a dq.issues row (handoff 0001). A
LineageEdge is the in-memory form of a lineage.edges row. Normalizers return
these alongside canonical rows; the writer persists them. Nothing here may
ever be optional to emit: a normalizer that detects a problem MUST return a
DQFinding — swallowing it is a guardrail violation (fail loudly).
"""

from __future__ import annotations

import hashlib
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

    def transform_dedupe_key(self) -> str | None:
        """Stable replay-dedupe key for TRANSFORM-emitted findings.

        At-least-once Kafka delivery replays messages; normalization is
        deterministic, so a replay re-emits byte-identical findings. This
        key (dq.issues.dedupe_key, migration 0023: UNIQUE WHERE NOT NULL +
        ON CONFLICT DO NOTHING) makes those replays write nothing new.

        Scope is deliberately narrow — the "transform:" prefix plus the
        hash of the finding's full identity (type, severity, title,
        description, sorted source records). Human- and AI-created
        dq.issues rows never pass through this writer and keep dedupe_key
        NULL, so they are NEVER deduplicated against anything. A finding
        with no source-record anchor returns None (no stable subject
        identity — not deduped, duplicates preferred over losing one).
        """
        if not self.source_record_ids:
            return None
        preimage = "\x1f".join(
            [
                self.issue_type,
                self.severity,
                self.title,
                self.description,
                *sorted(self.source_record_ids),
            ]
        )
        digest = hashlib.sha256(preimage.encode("utf-8")).hexdigest()
        return f"transform:{digest}"
