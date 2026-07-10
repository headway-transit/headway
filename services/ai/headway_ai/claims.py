"""The structured output contract every Headway AI feature must emit.

AI features do not emit free prose. They emit a :class:`GroundedDraft`: a
non-empty sequence of :class:`Claim` objects, each carrying the citation
(record kind + record id) it rests on and the numeric strings it uses.
Free prose without claims is *not representable* in this contract — a
draft with zero claims raises at construction — and ``ai_generated`` is a
non-constructor, always-``True`` field, so an unlabeled draft cannot
exist either.

The grounding harness (:mod:`headway_ai.grounding`) evaluates these
objects; a claim whose citation does not resolve, or whose text contains
a numeric token outside the caller-supplied allowed set, fails the draft.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Claim", "GroundedDraft"]


@dataclass(frozen=True)
class Claim:
    """One cited statement inside an AI draft.

    - ``cited_record_kind`` / ``cited_record_id`` must resolve to a real
      row per the handoff-0001 schema contract (raw.records, canonical.*,
      computed.metric_values, lineage.edges).
    - ``numeric_values`` declares, as *strings* (never floats), every
      number the claim text uses; the fabrication check verifies both the
      declared values and the tokens actually extracted from ``text``
      against the allowed-numbers set.
    """

    text: str
    cited_record_kind: str
    cited_record_id: str
    numeric_values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Claim.text must be non-empty")
        if not self.cited_record_kind or not self.cited_record_id:
            raise ValueError("Claim requires cited_record_kind and cited_record_id")
        coerced = tuple(self.numeric_values)
        if any(not isinstance(value, str) for value in coerced):
            raise TypeError(
                "Claim.numeric_values must be strings (numbers are never handled as floats)"
            )
        object.__setattr__(self, "numeric_values", coerced)


@dataclass(frozen=True)
class GroundedDraft:
    """The only output shape an AI feature may surface.

    Invariants enforced at construction:
    - at least one :class:`Claim` (free, citation-less prose is not
      representable);
    - provider name/version metadata present (traceability);
    - ``ai_generated`` is ``init=False`` and always ``True`` on a frozen
      dataclass — structurally impossible to present unlabeled.
    """

    claims: tuple[Claim, ...]
    provider_name: str
    provider_version: str
    ai_generated: bool = field(init=False, default=True)

    def __post_init__(self) -> None:
        coerced = tuple(self.claims)
        if not coerced:
            raise ValueError(
                "GroundedDraft requires at least one Claim: free prose without "
                "citations is not representable"
            )
        if any(not isinstance(claim, Claim) for claim in coerced):
            raise TypeError("GroundedDraft.claims must contain only Claim objects")
        if not self.provider_name or not self.provider_version:
            raise ValueError("GroundedDraft requires provider_name and provider_version")
        object.__setattr__(self, "claims", coerced)
