"""Statistician attestation context for the p. 146 factor-up path
(handoff 0019, design point A).

Regulatory basis (2026 NTD Policy Manual, Full Reporting — quotes verified
against docs/reference/ 2026-07-15; see REGULATORY_TRACKER.md, "Verified —
statistician attestations"):

- **The p. 146 rule**: "However, if the vehicle trips with missing data
  exceed 2 percent of total trips, agencies must have a qualified
  statistician approve the factoring method used to account for the missing
  percentage." The approval is a HUMAN act. Headway records it as an
  append-only ``cert.attestations`` row (migration 0029, entered through the
  audited API), and the calculations consume it only as the immutable
  context defined here — the calc never decides whether a statistician
  approved anything; it only checks that a recorded, unrevoked, in-scope
  attestation exists.

HARD LIMITS (handoff 0019 A.3, pinned by tests) — an attestation can NEVER:

1. **unblock sampling undersampling** — the sampling manual's technique is
   binding: "However, agencies must not collect a smaller sample than the
   chosen sampling plan prescribes." (2026 NTD Policy Manual, Full
   Reporting, p. 149 — verified 2026-07-15). No statistician attestation
   cures a short sample; the sampling estimate path takes no attestation
   input at all (structural, not procedural).
2. **touch simulated-data flags** — the handoff-0005 rule stands: simulated
   sources stay flagged and non-certifiable whether or not the figure was
   factored under an attestation.
3. **apply outside its declared scope** — metric, scope pattern, and period
   range are matched exactly here (``applicable_attestations``); a
   mismatched attestation is as good as none.
4. **affect operations metrics** — otp_v0 / headway_adherence_v0 accept no
   attestation input (structural).

Pure and deterministic: stdlib only, no network, no clock reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from fnmatch import fnmatchcase
from typing import Iterable

#: The p. 146 sentence the attested factor-up implements, verbatim (2026 NTD
#: Policy Manual, Full Reporting, p. 146 — verified 2026-07-15; the same
#: sentence the refusal path has cited since upt_v0 0.1.0).
P146_ATTESTATION_BASIS = (
    "However, if the vehicle trips with missing data exceed 2 percent of "
    "total trips, agencies must have a qualified statistician approve the "
    "factoring method used to account for the missing percentage."
)

#: The sampling-manual hard limit, verbatim (2026 NTD Policy Manual, Full
#: Reporting, p. 149 — verified 2026-07-15). Cited by the hard-limit test:
#: no attestation ever cures undersampling.
P149_NO_SMALLER_SAMPLE = (
    "However, agencies must not collect a smaller sample than the chosen "
    "sampling plan prescribes."
)

#: The metrics the p. 146 rule applies to — the ONLY metrics an attestation
#: can ever affect (hard limits 1 and 4 above are the complement).
ATTESTABLE_METRICS = ("upt", "pmt")


@dataclass(frozen=True)
class AttestationContext:
    """One recorded statistician attestation (read contract:
    cert.attestations, migration 0029 — append-only, revocation never
    deletion).

    ``metric`` names the ONE metric the statistician's approval covers
    ('upt' or 'pmt'). ``scope_pattern`` matches computed.metric_values.scope
    values by ``fnmatch.fnmatchcase`` (case-sensitive, deterministic):
    'agency' matches exactly the fleet scope; 'mode:bus' exactly that mode;
    'mode:DR:tos:*' every DR TOS scope; '*' every scope. ``period_start`` /
    ``period_end`` bound the half-open [start, end) date range the approval
    covers — an attestation applies to a run only when it covers the WHOLE
    run period. ``document_reference`` is an external pointer to the
    statistician's approval document (v0 stores the reference, never the
    document). ``revoked_at`` non-None means the attestation is revoked and
    applies to nothing (the row itself is never deleted — honest history).
    """

    attestation_id: str
    statistician_name: str
    statistician_credentials: str
    method_description: str
    document_reference: str
    metric: str
    scope_pattern: str
    period_start: date
    period_end: date
    entered_by: str
    entered_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.metric not in ATTESTABLE_METRICS:
            raise ValueError(
                f"AttestationContext.metric must be one of "
                f"{ATTESTABLE_METRICS} (the p. 146 rule applies to the "
                f"100%-count UPT/PMT paths and nothing else); got "
                f"{self.metric!r} (attestation_id={self.attestation_id!r})"
            )
        if self.period_end <= self.period_start:
            raise ValueError(
                f"AttestationContext period must be a non-empty half-open "
                f"[start, end) range; got [{self.period_start}, "
                f"{self.period_end}) (attestation_id={self.attestation_id!r})"
            )

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    def covers_period(self, period_start: date, period_end: date) -> bool:
        """True iff this attestation's declared range covers the WHOLE
        half-open run period — partial cover is no cover (the statistician
        approved a method for a stated range, nothing more)."""
        return self.period_start <= period_start and period_end <= self.period_end

    def matches_scope(self, scope: str) -> bool:
        """Case-sensitive fnmatch of the run's metric-value scope against
        the declared pattern."""
        return fnmatchcase(scope, self.scope_pattern)

    def to_provenance_dict(self) -> dict:
        """The attestation provenance persisted verbatim into the metric
        value's detail JSONB (all values JSON-safe strings) — the figure
        carries WHO approved WHAT method for WHICH scope forever."""
        return {
            "attestation_id": self.attestation_id,
            "statistician_name": self.statistician_name,
            "statistician_credentials": self.statistician_credentials,
            "method_description": self.method_description,
            "document_reference": self.document_reference,
            "metric": self.metric,
            "scope_pattern": self.scope_pattern,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "entered_by": self.entered_by,
            "entered_at": self.entered_at.isoformat(),
            "basis": P146_ATTESTATION_BASIS,
        }


def governing_attestation(
    attestations: Iterable[AttestationContext],
    metric: str,
) -> AttestationContext | None:
    """The ONE attestation that governs a calc's factor-up, or None.

    The calc boundary's defense in depth: the caller (headway_calc.runner /
    headway_calc.mode) selects by scope and period via
    ``applicable_attestations``; the calc itself cannot know its scope or
    period, but it DOES know its metric — so an attestation for a different
    metric here is a caller bug and REFUSES loudly (ValueError, hard limit
    3), never a silently honored approval. Revoked attestations are skipped
    (revocation is never deletion — a revoked row may legitimately still be
    passed in). Returns the earliest-entered survivor
    ((entered_at, attestation_id) order) — the governing attestation — or
    None when nothing applies.
    """
    live: list[AttestationContext] = []
    for attestation in attestations:
        if attestation.metric != metric:
            raise ValueError(
                f"Attestation {attestation.attestation_id!r} declares metric "
                f"{attestation.metric!r} but was passed to the {metric!r} "
                f"calculation — an attestation never applies outside its "
                f"declared scope (handoff 0019 hard limit 3). Select with "
                f"headway_calc.attestation.applicable_attestations."
            )
        if not attestation.revoked:
            live.append(attestation)
    if not live:
        return None
    return min(live, key=lambda a: (a.entered_at, a.attestation_id))


def applicable_attestations(
    attestations: Iterable[AttestationContext],
    metric: str,
    scope: str,
    period_start: date,
    period_end: date,
) -> tuple[AttestationContext, ...]:
    """The attestations that apply to one (metric, scope, period) run —
    hard limit 3 lives here: unrevoked, metric equal, scope pattern
    matching, and the declared range covering the WHOLE run period. Sorted
    deterministically by (entered_at, attestation_id) — the earliest-entered
    applicable attestation governs a factor-up."""
    return tuple(
        sorted(
            (
                a
                for a in attestations
                if not a.revoked
                and a.metric == metric
                and a.matches_scope(scope)
                and a.covers_period(period_start, period_end)
            ),
            key=lambda a: (a.entered_at, a.attestation_id),
        )
    )
