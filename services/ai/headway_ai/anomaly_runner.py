"""Anomaly scan runner: history in, flags out — never a number.

``run_anomaly_scan(conn)`` loads the ``computed.metric_values`` history in
deterministic order through the injected DB-API connection (``%s``
placeholders, psycopg-compatible; tests inject fakes — this module never
opens a connection itself), runs the deterministic detectors
(:mod:`headway_ai.anomaly`), grounding-checks each finding's explanation
(:mod:`headway_ai.anomaly_explain` — an explanation failing the gate is
dropped loudly; the finding is inserted WITHOUT it), inserts one
``dq.issues`` row per finding, commits, and returns a frozen
:class:`AnomalyRunReport`.

The dq rows follow the handoff-0001 schema: severity ``info``/``warning``
only (an anomaly flag NEVER blocks — humans decide), status ``open``,
``source_record_ids`` EMPTY (the compared rows are computed values, not
raw source records; their metric_value_ids are cited in the description,
and lineage from each metric value to its raw records already exists via
``lineage.edges``). This runner writes ONLY dq.issues rows — it never
touches ``computed.metric_values``: flags, not figures.

CLI process boundary (mirroring headway_calc._cli): ``python -m
headway_ai.anomaly_runner`` connects via the standard libpq ``PG*``
environment variables (PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD/…),
with the psycopg import guarded so every other path in this module stays
stdlib-only and driver-free. Everything below :func:`main` is
deterministic: no clock, no randomness, no environment reads.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping

from headway_ai.anomaly import (
    COVERAGE_DROP_THRESHOLD,
    SWING_THRESHOLD,
    AnomalyFinding,
    HistoryRow,
    detect_all,
    normalize_history,
)
from headway_ai.anomaly_explain import ExplanationBatch, explain_findings
from headway_ai.provider import Provider, StubProvider

__all__ = [
    "InsertedIssue",
    "AnomalyRunReport",
    "load_metric_history",
    "run_anomaly_scan",
    "main",
]

#: Columns rendered to text in SQL so every driver returns strings — the
#: NUMERIC value never becomes a float anywhere in this layer.
_SELECT_HISTORY_SQL = (
    "SELECT metric_value_id::text, metric, value::text, period_start::text, "
    "period_end::text, calc_version, detail::text "
    "FROM computed.metric_values "
    "ORDER BY metric, period_start, period_end, metric_value_id"
)

#: Column names exactly per handoff 0001 (dq.issues); issue_id, created_at,
#: owner, resolved_at, resolution take their schema defaults.
_INSERT_ISSUE_SQL = (
    "INSERT INTO dq.issues "
    "(issue_type, severity, status, title, description, source_record_ids) "
    "VALUES (%s, %s, %s, %s, %s, %s) "
    "RETURNING issue_id"
)

_STATUS = "open"


def load_metric_history(conn: Any) -> tuple[HistoryRow, ...]:
    """Read the full computed-metric history, ordered, via the injected conn.

    Read-only; ``detail`` comes back as JSON text and is parsed here (the
    column is NOT NULL DEFAULT '{}', but a NULL from a fake is tolerated as
    ``{}``). Returns normalized :class:`HistoryRow` tuples.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(_SELECT_HISTORY_SQL)
        rows = cursor.fetchall()
    finally:
        cursor.close()
    history: list[dict[str, Any]] = []
    for metric_value_id, metric, value, period_start, period_end, calc_version, detail in rows:
        history.append(
            {
                "metric_value_id": metric_value_id,
                "metric": metric,
                "value": value,
                "period_start": period_start,
                "period_end": period_end,
                "calc_version": calc_version,
                "detail": json.loads(detail) if detail else {},
            }
        )
    return normalize_history(history)


@dataclass(frozen=True)
class InsertedIssue:
    """One dq.issues row this scan inserted (flag only, never a fix)."""

    issue_id: str
    issue_type: str
    severity: str
    metric: str
    title: str
    cited_metric_value_ids: tuple[str, ...]
    explanation_grounded: bool  # False = explanation dropped by the gate

    def to_dict(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "metric": self.metric,
            "title": self.title,
            "cited_metric_value_ids": list(self.cited_metric_value_ids),
            "explanation_grounded": self.explanation_grounded,
        }


@dataclass(frozen=True)
class AnomalyRunReport:
    """Immutable report of one anomaly scan (JSON-safe, Decimal-as-text)."""

    swing_threshold: Decimal
    coverage_drop_threshold: Decimal
    provider_name: str
    provider_version: str
    history_rows_loaded: int
    findings_detected: int
    issues_inserted: tuple[InsertedIssue, ...]
    explanations_grounded: int
    explanations_rejected: int
    rejected_issue_types: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "swing_threshold": str(self.swing_threshold),
            "coverage_drop_threshold": str(self.coverage_drop_threshold),
            "threshold_provenance": (
                "engineering defaults, explicit Decimal inputs — not FTA "
                "numbers, not model judgment (services/ai/DETECTOR_THRESHOLDS.md)"
            ),
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "history_rows_loaded": self.history_rows_loaded,
            "findings_detected": self.findings_detected,
            "issues_inserted_count": len(self.issues_inserted),
            "explanations_grounded": self.explanations_grounded,
            "explanations_rejected": self.explanations_rejected,
            "rejected_issue_types": list(self.rejected_issue_types),
            "issues": [issue.to_dict() for issue in self.issues_inserted],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def _description_with_explanation(
    finding: AnomalyFinding, explained_by_ids: Mapping[tuple[str, ...], str]
) -> tuple[str, bool]:
    """Append the grounded, labeled explanation — or nothing at all.

    A finding whose explanation was rejected by the grounding gate is
    written EXACTLY as the detector phrased it: the flag never depends on
    prose, and an ungrounded sentence never reaches the dq queue.
    """
    key = (finding.issue_type,) + finding.cited_metric_value_ids
    explanation = explained_by_ids.get(key)
    if explanation is None:
        return finding.description, False
    return (
        finding.description
        + "\n\nAI-generated explanation (grounding-checked; requires human "
        + "review; never a source of figures):\n"
        + explanation,
        True,
    )


def run_anomaly_scan(
    conn: Any,
    *,
    provider: Provider | None = None,
    swing_threshold: Decimal = SWING_THRESHOLD,
    coverage_drop_threshold: Decimal = COVERAGE_DROP_THRESHOLD,
) -> AnomalyRunReport:
    """One full scan: load → detect → ground-check explanations → insert flags.

    Inserts one ``dq.issues`` row per finding (severity info/warning only;
    ``source_record_ids`` empty; the compared metric_value_ids cited in the
    description) and commits once, after all inserts, so a partial scan
    never leaves half the flags. Returns a frozen report. Never writes
    anything except dq.issues rows.
    """
    active_provider: Provider = provider if provider is not None else StubProvider()
    history = load_metric_history(conn)
    findings = detect_all(
        history,
        swing_threshold=swing_threshold,
        coverage_drop_threshold=coverage_drop_threshold,
    )

    batch: ExplanationBatch = explain_findings(
        conn, findings, history, provider=active_provider
    )
    explained_by_ids = {
        (e.finding.issue_type,) + e.finding.cited_metric_value_ids: e.output.text
        for e in batch.explained
    }

    inserted: list[InsertedIssue] = []
    cursor = conn.cursor()
    try:
        for finding in findings:
            description, grounded = _description_with_explanation(finding, explained_by_ids)
            cursor.execute(
                _INSERT_ISSUE_SQL,
                (
                    finding.issue_type,
                    finding.severity,
                    _STATUS,
                    finding.title,
                    description,
                    [],  # source_record_ids EMPTY: computed rows are cited in the description
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError(
                    f"dq.issues insert for {finding.issue_type} returned no issue_id"
                )
            inserted.append(
                InsertedIssue(
                    issue_id=str(row[0]),
                    issue_type=finding.issue_type,
                    severity=finding.severity,
                    metric=finding.metric,
                    title=finding.title,
                    cited_metric_value_ids=finding.cited_metric_value_ids,
                    explanation_grounded=grounded,
                )
            )
    finally:
        cursor.close()
    conn.commit()

    return AnomalyRunReport(
        swing_threshold=swing_threshold,
        coverage_drop_threshold=coverage_drop_threshold,
        provider_name=active_provider.name,
        provider_version=active_provider.version,
        history_rows_loaded=len(history),
        findings_detected=len(findings),
        issues_inserted=tuple(inserted),
        explanations_grounded=len(batch.explained),
        explanations_rejected=len(batch.rejected),
        rejected_issue_types=tuple(r.finding.issue_type for r in batch.rejected),
    )


# ---------------------------------------------------------------------------
# CLI process boundary — the ONLY code here that touches env or a driver
# (mirrors the headway_calc._cli precedent; psycopg import guarded).
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m headway_ai.anomaly_runner",
        description=(
            "Scan computed.metric_values history with the deterministic "
            "anomaly detectors, insert info/warning dq.issues flags (with "
            "grounding-checked AI explanations where they pass the gate), "
            "and print the AnomalyRunReport as JSON. Connects via the "
            "standard libpq PG* environment variables. Flags only: this "
            "never computes, changes, or blocks a reported figure."
        ),
    )
    parser.add_argument(
        "--swing-threshold",
        type=Decimal,
        default=None,
        help=(
            "Override the period-over-period swing threshold (default: the "
            "library default, 0.25 — an ENGINEERING DEFAULT, not an FTA "
            "number; see services/ai/DETECTOR_THRESHOLDS.md). The value "
            "used is recorded in the report."
        ),
    )
    parser.add_argument(
        "--coverage-drop-threshold",
        type=Decimal,
        default=None,
        help=(
            "Override the consecutive-period coverage-drop threshold "
            "(default: the library default, 0.05 — an ENGINEERING DEFAULT; "
            "see services/ai/DETECTOR_THRESHOLDS.md). The value used is "
            "recorded in the report."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not any(os.environ.get(var) for var in ("PGHOST", "PGDATABASE", "PGSERVICE")):
        raise SystemExit(
            "No libpq connection environment found (PGHOST / PGDATABASE / "
            "PGSERVICE). Refusing to guess a connection — set the standard "
            "PG* variables and re-run."
        )

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover — driver-less environments
        raise SystemExit(
            "The psycopg driver is required for a live run but is not "
            "installed. Install it with: pip install 'headway-ai[persist]'"
        ) from exc

    with psycopg.connect() as conn:  # connection params from PG* env (libpq)
        report = run_anomaly_scan(
            conn,
            swing_threshold=(
                SWING_THRESHOLD if args.swing_threshold is None else args.swing_threshold
            ),
            coverage_drop_threshold=(
                COVERAGE_DROP_THRESHOLD
                if args.coverage_drop_threshold is None
                else args.coverage_drop_threshold
            ),
        )

    print(report.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
