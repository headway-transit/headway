"""Deterministic, explainable anomaly detectors over computed metric history.

DETECTORS FLAG; THEY NEVER CORRECT. Nothing in this module computes,
adjusts, backfills, interpolates, or re-derives a reported figure. Each
detector reads already-computed ``computed.metric_values`` rows (written
only by the calc library) and, when a deterministic rule fires, emits an
:class:`AnomalyFinding` — a candidate ``dq.issues`` row with severity
``info`` or ``warning`` ONLY. An anomaly flag NEVER blocks anything: a
human reads the flag and decides. The Decimal comparisons below exist
solely to decide *whether to raise a flag*; their results are never
persisted, never surfaced as figures, and never appear in finding prose.

Inputs are injected metric-history rows (mappings with keys
``metric_value_id``, ``metric``, ``value`` (string), ``period_start``,
``period_end``, ``calc_version``, ``detail``). All functions are pure:
no clock, no randomness, no network, no database — identical input yields
identical findings. All arithmetic is ``Decimal`` over the value STRINGS;
no float ever enters a comparison. Threshold comparisons avoid division
entirely (``|Δ| > threshold × |previous|``) so exactly-at-threshold is
exact, not a rounding accident.

Detectors (consecutive same-metric periods, ordered by period):

1. :func:`detect_metric_swings` — |current − previous| strictly greater
   than ``swing_threshold × |previous|`` → one ``warning`` finding.
2. :func:`detect_coverage_drops` — ``detail.coverage`` decreasing by
   strictly more than ``coverage_drop_threshold`` → one ``warning``
   finding. Rows without a coverage ratio (e.g. upt_v0's UptDetail) are
   skipped for this detector only — absence of coverage is not an anomaly
   here; completeness evidence for those metrics lives in their own
   detail fields.
3. :func:`detect_calc_version_changes` — ``calc_version`` differing
   between consecutive periods → one ``info`` finding citing BOTH rows:
   figures computed by different calculation versions are not directly
   comparable.

THRESHOLD PROVENANCE: ``SWING_THRESHOLD`` (0.25) and
``COVERAGE_DROP_THRESHOLD`` (0.05) are ENGINEERING DEFAULTS, not FTA
numbers and not statistical baselines — explicit Decimal inputs traced to
deterministic configuration, never model judgment (see
services/ai/DETECTOR_THRESHOLDS.md). Statistical baselines (robust
z-scores / MAD per the role file) are the next increment once >30 days of
metric history exist; per-agency configuration is planned.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Iterator, Mapping

__all__ = [
    "SWING_THRESHOLD",
    "COVERAGE_DROP_THRESHOLD",
    "ISSUE_TYPE_SWING",
    "ISSUE_TYPE_COVERAGE_DROP",
    "ISSUE_TYPE_CALC_VERSION_CHANGE",
    "AnomalyFinding",
    "HistoryRow",
    "normalize_history",
    "detect_metric_swings",
    "detect_coverage_drops",
    "detect_calc_version_changes",
    "detect_all",
]

#: ENGINEERING DEFAULT (not an FTA number, not a statistical baseline):
#: period-over-period change greater than 25% of the previous value flags.
SWING_THRESHOLD = Decimal("0.25")

#: ENGINEERING DEFAULT: coverage falling by more than 0.05 between
#: consecutive periods flags.
COVERAGE_DROP_THRESHOLD = Decimal("0.05")

ISSUE_TYPE_SWING = "anomaly_metric_swing"
ISSUE_TYPE_COVERAGE_DROP = "anomaly_coverage_drop"
ISSUE_TYPE_CALC_VERSION_CHANGE = "anomaly_calc_version_change"

#: An anomaly flag NEVER blocks. 'blocking' is structurally unrepresentable
#: in an AnomalyFinding — humans decide what a flag means.
_ALLOWED_SEVERITIES = frozenset({"info", "warning"})

#: Appended to every finding description so a reader always knows the flag's
#: standing: automated, assistive, non-authoritative, human-decided.
_FLAG_FOOTER = (
    "This flag was raised automatically by Headway's deterministic anomaly "
    "detector (an AI-layer feature; the rule and threshold are fixed "
    "configuration, not model judgment). It is informational for a human "
    "reviewer: it does not block any calculation or submission, and no "
    "reported figure was changed, corrected, or adjusted."
)


@dataclass(frozen=True)
class HistoryRow:
    """One normalized ``computed.metric_values`` history row (all read-only).

    ``value`` stays a STRING (the row's NUMERIC rendered as text);
    ``detail`` is the persisted detail JSONB as a mapping (``{}`` when
    empty). Periods are ISO-8601 date strings.
    """

    metric_value_id: str
    metric: str
    value: str
    period_start: str
    period_end: str
    calc_version: str
    detail: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in ("metric_value_id", "metric", "value", "period_start", "period_end", "calc_version"):
            if not getattr(self, name):
                raise ValueError(f"HistoryRow.{name} must be non-empty")
        try:
            Decimal(self.value)
        except InvalidOperation as exc:
            raise ValueError(
                f"HistoryRow.value {self.value!r} (metric_value_id "
                f"{self.metric_value_id}) is not a valid Decimal string"
            ) from exc

    @property
    def coverage(self) -> str | None:
        """The detail's coverage ratio string, or None (e.g. UptDetail)."""
        coverage = self.detail.get("coverage")
        return coverage if isinstance(coverage, str) and coverage else None


def normalize_history(rows: Iterable[Mapping[str, Any]]) -> tuple[HistoryRow, ...]:
    """Validate injected rows and return them deterministically ordered.

    Order: (metric, period_start, period_end, metric_value_id) — the same
    input set always yields the same tuple regardless of input order.
    Missing keys or an unparseable value string fail loudly (never skipped:
    a malformed history row is itself a data problem a human must see).
    """
    normalized: list[HistoryRow] = []
    for row in rows:
        if isinstance(row, HistoryRow):  # idempotent over already-normalized rows
            normalized.append(row)
            continue
        missing = [
            key
            for key in ("metric_value_id", "metric", "value", "period_start", "period_end", "calc_version")
            if key not in row
        ]
        if missing:
            raise ValueError(f"history row missing required key(s) {missing}: {dict(row)!r}")
        detail = row.get("detail") or {}
        if not isinstance(detail, Mapping):
            raise ValueError(
                f"history row detail must be a mapping, got {type(detail).__name__} "
                f"(metric_value_id {row['metric_value_id']!r})"
            )
        normalized.append(
            HistoryRow(
                metric_value_id=str(row["metric_value_id"]),
                metric=str(row["metric"]),
                value=str(row["value"]),
                period_start=str(row["period_start"]),
                period_end=str(row["period_end"]),
                calc_version=str(row["calc_version"]),
                detail=detail,
            )
        )
    normalized.sort(key=lambda r: (r.metric, r.period_start, r.period_end, r.metric_value_id))
    return tuple(normalized)


@dataclass(frozen=True)
class AnomalyFinding:
    """A candidate ``dq.issues`` row: a flag for a human, never a fix.

    Severity is ``info`` or ``warning`` ONLY — an anomaly finding can never
    block (enforced at construction). ``cited_metric_value_ids`` names the
    ``computed.metric_values`` rows compared, in (previous, current) order;
    the plain-language description restates them so the citation survives
    into the dq.issues text.
    """

    issue_type: str
    severity: str
    metric: str
    title: str
    description: str
    cited_metric_value_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.severity not in _ALLOWED_SEVERITIES:
            raise ValueError(
                f"AnomalyFinding severity must be one of {sorted(_ALLOWED_SEVERITIES)}, "
                f"got {self.severity!r} — an anomaly flag never blocks; humans decide"
            )
        if not self.cited_metric_value_ids:
            raise ValueError("AnomalyFinding must cite at least one metric_value_id")
        object.__setattr__(self, "cited_metric_value_ids", tuple(self.cited_metric_value_ids))
        for cited_id in self.cited_metric_value_ids:
            if cited_id not in self.description:
                raise ValueError(
                    f"AnomalyFinding description must cite metric_value_id {cited_id!r} "
                    "in plain language — an uncited flag is not explainable"
                )
        if not self.title.strip() or not self.description.strip():
            raise ValueError("AnomalyFinding requires non-empty title and description")


def _row_phrase(row: HistoryRow) -> str:
    """Plain-language reference to one cited row, restating its raw value."""
    return (
        f"{row.value} for the period {row.period_start} to {row.period_end} "
        f"(metric_value_id {row.metric_value_id}, calculation version {row.calc_version})"
    )


def _consecutive_pairs(rows: Iterable[Mapping[str, Any]]) -> Iterator[tuple[HistoryRow, HistoryRow]]:
    """Yield (previous, current) pairs of consecutive same-metric periods."""
    history = rows if isinstance(rows, tuple) and all(isinstance(r, HistoryRow) for r in rows) else normalize_history(rows)
    for previous, current in zip(history, history[1:]):
        if previous.metric == current.metric:
            yield previous, current


def _require_positive(name: str, threshold: Decimal) -> Decimal:
    if not isinstance(threshold, Decimal):
        raise TypeError(f"{name} must be an explicit Decimal, got {type(threshold).__name__}")
    if threshold <= 0:
        raise ValueError(f"{name} must be positive, got {threshold}")
    return threshold


def detect_metric_swings(
    rows: Iterable[Mapping[str, Any]],
    *,
    swing_threshold: Decimal = SWING_THRESHOLD,
) -> tuple[AnomalyFinding, ...]:
    """Flag period-over-period swings; never correct or re-derive a value.

    Fires when ``|current − previous|`` is STRICTLY greater than
    ``swing_threshold × |previous|`` for consecutive same-metric periods
    (a change of exactly the threshold does not flag). Stated without
    division so the comparison is exact Decimal arithmetic; a previous
    value of 0 therefore flags on any nonzero change. The finding restates
    both raw value strings and cites both metric_value_ids; no derived
    percentage or ratio ever appears in the prose — the detector flags,
    a human interprets.
    """
    threshold = _require_positive("swing_threshold", swing_threshold)
    findings: list[AnomalyFinding] = []
    for previous, current in _consecutive_pairs(rows):
        delta = abs(Decimal(current.value) - Decimal(previous.value))
        if delta > threshold * abs(Decimal(previous.value)):
            findings.append(
                AnomalyFinding(
                    issue_type=ISSUE_TYPE_SWING,
                    severity="warning",
                    metric=current.metric,
                    title=f"Sharp period-over-period change in computed {current.metric}",
                    description=(
                        f"The computed {current.metric} value changed from "
                        f"{_row_phrase(previous)} to {_row_phrase(current)}. "
                        f"The size of this change exceeds the configured "
                        f"period-over-period swing threshold of {threshold} "
                        f"(an engineering default, not an FTA number; see "
                        f"services/ai/DETECTOR_THRESHOLDS.md). A swing this "
                        f"large can be real (service change, seasonal shift) "
                        f"or a data problem — please review the two cited "
                        f"metric values and their lineage. {_FLAG_FOOTER}"
                    ),
                    cited_metric_value_ids=(previous.metric_value_id, current.metric_value_id),
                )
            )
    return tuple(findings)


def detect_coverage_drops(
    rows: Iterable[Mapping[str, Any]],
    *,
    coverage_drop_threshold: Decimal = COVERAGE_DROP_THRESHOLD,
) -> tuple[AnomalyFinding, ...]:
    """Flag falling input coverage; never correct or re-derive a value.

    Fires when the detail's coverage ratio decreases by STRICTLY more than
    ``coverage_drop_threshold`` between consecutive same-metric periods (a
    drop of exactly the threshold does not flag). Pairs where either row
    carries no coverage ratio are skipped by THIS detector (upt_v0's
    detail has no coverage field). A present-but-unparseable coverage
    string fails loudly. The finding restates both coverage strings and
    cites both metric_value_ids; the detector flags, a human interprets.
    """
    threshold = _require_positive("coverage_drop_threshold", coverage_drop_threshold)
    findings: list[AnomalyFinding] = []
    for previous, current in _consecutive_pairs(rows):
        if previous.coverage is None or current.coverage is None:
            continue
        try:
            drop = Decimal(previous.coverage) - Decimal(current.coverage)
        except InvalidOperation as exc:
            raise ValueError(
                f"unparseable coverage string comparing metric_value_ids "
                f"{previous.metric_value_id} ({previous.coverage!r}) and "
                f"{current.metric_value_id} ({current.coverage!r})"
            ) from exc
        if drop > threshold:
            findings.append(
                AnomalyFinding(
                    issue_type=ISSUE_TYPE_COVERAGE_DROP,
                    severity="warning",
                    metric=current.metric,
                    title=f"Input coverage for computed {current.metric} dropped between periods",
                    description=(
                        f"The share of clean input data behind the computed "
                        f"{current.metric} value fell from coverage "
                        f"{previous.coverage} for the period {previous.period_start} "
                        f"to {previous.period_end} (metric_value_id "
                        f"{previous.metric_value_id}) to coverage {current.coverage} "
                        f"for the period {current.period_start} to {current.period_end} "
                        f"(metric_value_id {current.metric_value_id}). The decrease "
                        f"exceeds the configured coverage-drop threshold of "
                        f"{threshold} (an engineering default, not an FTA number; "
                        f"see services/ai/DETECTOR_THRESHOLDS.md). Falling coverage "
                        f"means more input data was excluded as unusable, so the "
                        f"newer figure rests on a smaller share of the fleet's "
                        f"telemetry — please review the cited metric values and "
                        f"their exclusion findings. {_FLAG_FOOTER}"
                    ),
                    cited_metric_value_ids=(previous.metric_value_id, current.metric_value_id),
                )
            )
    return tuple(findings)


def detect_calc_version_changes(rows: Iterable[Mapping[str, Any]]) -> tuple[AnomalyFinding, ...]:
    """Flag calc-version changes between periods; never correct anything.

    Fires (severity ``info``) whenever consecutive same-metric periods were
    computed by different calculation versions, citing BOTH rows: figures
    computed by different calculation versions are not directly comparable,
    so any period-over-period reading across the boundary needs that
    context. Informational only — a version change is expected engineering
    activity, not suspected bad data.
    """
    findings: list[AnomalyFinding] = []
    for previous, current in _consecutive_pairs(rows):
        if previous.calc_version != current.calc_version:
            findings.append(
                AnomalyFinding(
                    issue_type=ISSUE_TYPE_CALC_VERSION_CHANGE,
                    severity="info",
                    metric=current.metric,
                    title=f"Calculation version for {current.metric} changed between periods",
                    description=(
                        f"The {current.metric} value for the period "
                        f"{previous.period_start} to {previous.period_end} "
                        f"(metric_value_id {previous.metric_value_id}) was computed "
                        f"by calculation version {previous.calc_version}, while the "
                        f"value for the period {current.period_start} to "
                        f"{current.period_end} (metric_value_id "
                        f"{current.metric_value_id}) was computed by calculation "
                        f"version {current.calc_version}. Figures computed by "
                        f"different calculation versions are not directly "
                        f"comparable: part of any difference between them may come "
                        f"from the calculation change rather than from service or "
                        f"data changes. Please read period-over-period comparisons "
                        f"across this boundary with that in mind. {_FLAG_FOOTER}"
                    ),
                    cited_metric_value_ids=(previous.metric_value_id, current.metric_value_id),
                )
            )
    return tuple(findings)


def detect_all(
    rows: Iterable[Mapping[str, Any]],
    *,
    swing_threshold: Decimal = SWING_THRESHOLD,
    coverage_drop_threshold: Decimal = COVERAGE_DROP_THRESHOLD,
) -> tuple[AnomalyFinding, ...]:
    """Run all three detectors over one normalized pass of the history.

    Deterministic concatenation (swings, then coverage drops, then version
    changes), each detector already in (metric, period) order. Detectors
    are independent: a value swing across a version boundary yields BOTH a
    swing warning and a version-change info — the info finding is exactly
    the caveat a reviewer needs when reading the warning.
    """
    history = normalize_history(rows)
    return (
        detect_metric_swings(history, swing_threshold=swing_threshold)
        + detect_coverage_drops(history, coverage_drop_threshold=coverage_drop_threshold)
        + detect_calc_version_changes(history)
    )
