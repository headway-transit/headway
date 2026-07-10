"""THE GROUNDING EVALUATION HARNESS — three deterministic checks.

Given a :class:`~headway_ai.claims.GroundedDraft`, an injected DB-API
connection (psycopg-style ``%s`` placeholders; tests and the regression
gate inject fakes — this module NEVER opens or writes a connection), and
a caller-supplied allowed-numbers set:

1. :func:`check_citations` — every ``(cited_record_kind, cited_record_id)``
   must exist per the handoff-0001 schema contract. One parameterized
   SELECT per kind; an unknown kind is a failure, never a skip.
2. :func:`check_fabrication` — every numeric token in claim text (and
   every declared ``Claim.numeric_values`` entry) must appear in the
   allowed-numbers set (strings from ``computed.metric_values.value`` and
   detail fields, supplied by the caller) or in an explicitly passed
   record-count whitelist. Any unexplained number is a fabrication.
   Comparison is by normalized ``Decimal`` string — never floats.
3. :func:`evaluate` — aggregates both into a frozen :class:`EvalReport`;
   pass requires citation resolution == 1.0 AND zero fabrications.

Numeric-token policy (deliberate, tested):
- Thousands separators normalize away: ``12,794.92`` == ``12794.92``.
- Dotted triples (``0.4.0``) are VERSION tokens, not numeric claims —
  calc/transform versions appear legitimately in grounded prose and are
  covered by the citation check, not the number check.
- Digits attached to a word or hyphen (``abc123``, ``route-66``, hex
  record ids) are identifier fragments, not numeric claims.
- A digit run that survives extraction but does not parse as a Decimal is
  treated as fabricated (fail loudly, never skip silently).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from headway_ai.claims import GroundedDraft

__all__ = [
    "CitationResult",
    "FabricationResult",
    "EvalReport",
    "check_citations",
    "check_fabrication",
    "evaluate",
    "extract_numeric_tokens",
    "normalize_number",
]

# ---------------------------------------------------------------------------
# Citation resolution — handoff-0001 schema contract
# ---------------------------------------------------------------------------

# kind -> (table, id-column expression). The table/column pair is a static
# allowlist; the record id itself is ALWAYS a bound parameter.
_DIRECT_KIND_COLUMNS: dict[str, tuple[str, str]] = {
    "raw.records": ("raw.records", "record_id"),
    "canonical.routes": ("canonical.routes", "route_id"),
    "canonical.trips": ("canonical.trips", "trip_id"),
    "computed.metric_values": ("computed.metric_values", "metric_value_id::text"),
    "lineage.edges": ("lineage.edges", "edge_id::text"),
}

# canonical.vehicle_positions has a composite natural key; its citation ids
# are the lineage graph's text rendering of that key (handoff-0001:
# lineage.edges.output_id), so resolution goes through the lineage graph —
# consistent with the role file: "every cited id resolves to a real
# node/edge in the explicit lineage graph" (ADR-0007).
_LINEAGE_RESOLVED_KINDS = frozenset({"canonical.vehicle_positions"})

_LINEAGE_NODE_SQL = (
    "SELECT 1 FROM lineage.edges WHERE output_kind = %s AND output_id = %s LIMIT 1"
)


@dataclass(frozen=True)
class CitationResult:
    claim_index: int
    cited_record_kind: str
    cited_record_id: str
    resolved: bool
    reason: str


def _record_exists(conn: Any, sql: str, params: tuple[str, ...]) -> bool:
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def check_citations(conn: Any, draft: GroundedDraft) -> tuple[CitationResult, ...]:
    """Resolve every claim's citation against the injected connection.

    Read-only: issues one parameterized SELECT per claim. Unknown record
    kinds are failures (an invented kind must not pass by omission).
    """
    results: list[CitationResult] = []
    for index, claim in enumerate(draft.claims):
        kind, record_id = claim.cited_record_kind, claim.cited_record_id
        if kind in _DIRECT_KIND_COLUMNS:
            table, id_column = _DIRECT_KIND_COLUMNS[kind]
            sql = f"SELECT 1 FROM {table} WHERE {id_column} = %s LIMIT 1"  # noqa: S608 — table/column from static allowlist above; id is bound
            resolved = _record_exists(conn, sql, (record_id,))
            reason = "resolved" if resolved else f"no {kind} row with id {record_id!r}"
        elif kind in _LINEAGE_RESOLVED_KINDS:
            resolved = _record_exists(conn, _LINEAGE_NODE_SQL, (kind, record_id))
            reason = (
                "resolved via lineage graph"
                if resolved
                else f"no lineage node ({kind}, {record_id!r})"
            )
        else:
            resolved = False
            reason = f"unknown record kind {kind!r}"
        results.append(
            CitationResult(
                claim_index=index,
                cited_record_kind=kind,
                cited_record_id=record_id,
                resolved=resolved,
                reason=reason,
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# Fabrication detection — normalized-Decimal comparison, never floats
# ---------------------------------------------------------------------------

# A numeric token starts a digit run not glued to a word character, dot, or
# hyphen (identifier fragments like abc123, route-66, v1, hex ids are not
# numeric claims), then greedily takes digits, commas, and dots. Trailing
# sentence punctuation is stripped afterwards.
_NUMERIC_TOKEN_RE = re.compile(r"(?<![\w.\-])\d[\d,.]*")


def extract_numeric_tokens(text: str) -> tuple[str, ...]:
    """Extract candidate numeric tokens from prose.

    Returns raw tokens as they appear (commas kept), with trailing ``.``/
    ``,`` sentence punctuation stripped. Dotted triples (``0.4.0`` and
    longer) are version tokens and are excluded — see module docstring.
    """
    tokens: list[str] = []
    for match in _NUMERIC_TOKEN_RE.finditer(text):
        token = match.group().rstrip(".,")
        if not token:
            continue
        if token.count(".") >= 2:  # version token (e.g. calc_version 0.4.0)
            continue
        tokens.append(token)
    return tuple(tokens)


def normalize_number(token: str) -> str | None:
    """Canonical Decimal string for a numeric token, or None if unparseable.

    ``12,794.92`` and ``12794.92`` normalize identically; ``13000.00`` and
    ``13,000`` normalize identically. No float ever enters the comparison.
    """
    try:
        value = Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return str(normalized)


def _normalize_allowed(values: Iterable[str]) -> frozenset[str]:
    normalized: set[str] = set()
    for value in values:
        canonical = normalize_number(value)
        if canonical is None:
            raise ValueError(f"allowed/whitelisted number {value!r} is not a valid Decimal")
        normalized.add(canonical)
    return frozenset(normalized)


@dataclass(frozen=True)
class FabricationResult:
    claim_index: int
    fabricated_tokens: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.fabricated_tokens


def check_fabrication(
    draft: GroundedDraft,
    allowed_numbers: Iterable[str],
    *,
    record_count_whitelist: Iterable[str] = (),
) -> tuple[FabricationResult, ...]:
    """Every number in every claim must be explainable, or it is fabricated.

    ``allowed_numbers``: strings from ``computed.metric_values.value`` and
    detail fields (period dates, etc.), supplied by the caller — the AI
    layer never computes them. ``record_count_whitelist``: counts of cited
    records the caller explicitly vouches for (e.g. "3 source records").
    Both extracted text tokens and the claim's declared ``numeric_values``
    are checked.
    """
    allowed = _normalize_allowed(allowed_numbers) | _normalize_allowed(record_count_whitelist)
    results: list[FabricationResult] = []
    for index, claim in enumerate(draft.claims):
        fabricated: list[str] = []
        candidates = list(extract_numeric_tokens(claim.text)) + list(claim.numeric_values)
        seen: set[str] = set()
        for token in candidates:
            canonical = normalize_number(token)
            key = canonical if canonical is not None else f"unparseable:{token}"
            if key in seen:
                continue
            seen.add(key)
            if canonical is None or canonical not in allowed:
                fabricated.append(token)
        results.append(
            FabricationResult(claim_index=index, fabricated_tokens=tuple(fabricated))
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# Aggregate evaluation
# ---------------------------------------------------------------------------

_RATE_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class EvalReport:
    """Frozen verdict over one GroundedDraft.

    ``citation_resolution_rate`` is a Decimal string quantized to 4 places
    (display/reporting only); ``passed`` is computed from exact integer
    counts, never from the quantized rate.
    """

    citation_results: tuple[CitationResult, ...]
    fabrication_results: tuple[FabricationResult, ...]
    citation_resolution_rate: str
    fabricated_number_count: int
    passed: bool


def evaluate(
    conn: Any,
    draft: GroundedDraft,
    allowed_numbers: Iterable[str],
    *,
    record_count_whitelist: Iterable[str] = (),
) -> EvalReport:
    """Run both checks; pass requires 1.0 resolution AND 0 fabrications."""
    citation_results = check_citations(conn, draft)
    fabrication_results = check_fabrication(
        draft, allowed_numbers, record_count_whitelist=record_count_whitelist
    )
    resolved_count = sum(1 for result in citation_results if result.resolved)
    total = len(citation_results)  # GroundedDraft guarantees >= 1 claim
    rate = (Decimal(resolved_count) / Decimal(total)).quantize(_RATE_QUANTUM)
    fabricated_count = sum(
        len(result.fabricated_tokens) for result in fabrication_results
    )
    return EvalReport(
        citation_results=citation_results,
        fabrication_results=fabrication_results,
        citation_resolution_rate=str(rate),
        fabricated_number_count=fabricated_count,
        passed=(resolved_count == total and fabricated_count == 0),
    )
