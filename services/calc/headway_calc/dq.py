"""Routing of calculation Findings into dq.issues. Matches handoff 0001/0002.

When a calculation refuses a value (blocking) or documents an exclusion
(warning, calc 0.2.0), the evidence must land somewhere actionable: one
dq.issues row per Finding, carrying the finding's OWN severity ('blocking'
stays blocking, 'warning' stays warning), status 'open', so the DQ resolution
workflow (owner assignment, resolution) can pick it up. Takes any DB-API 2.0
connection (%s placeholders — psycopg-compatible); unit-testable with a fake
connection. Stdlib only.

Fail loudly: this module NEVER swallows an insert failure — any exception from
the database propagates unchanged. A finding that cannot be recorded is
itself a loud failure, never a silent one. Does NOT commit — transaction
control belongs to the caller (see headway_calc.runner for the
fail-loudly-first two-transaction design).
"""

from __future__ import annotations

from datetime import date

from headway_calc.types import SEVERITY_BLOCKING, Finding

#: Column names exactly per handoff 0001 (dq.issues). issue_id, created_at,
#: owner, resolved_at, resolution take their schema defaults.
_INSERT_ISSUE_SQL = (
    "INSERT INTO dq.issues "
    "(issue_type, severity, status, title, description, source_record_ids, category) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
    "RETURNING issue_id"
)

#: dq.issues.category vocabulary (migration 0024). 'ntd' (the default —
#: every pre-0024 writer) gates certification; 'ops' findings are real,
#: owned findings that must NEVER freeze federal certification (the
#: honesty boundary in the other direction).
CATEGORY_NTD = "ntd"
CATEGORY_OPS = "ops"

_STATUS = "open"

#: Severity-specific consequence appended to every routed description, so a
#: data steward reading the issue knows what the finding did to the figure.
_CONSEQUENCE_BY_SEVERITY = {
    "blocking": (
        "The calculation refused to emit a value over this unresolved gap; "
        "no computed.metric_values row was written."
    ),
    "warning": (
        "Warning severity: the cited records were EXCLUDED from the summed "
        "figure; any value persisted for this run was computed WITHOUT them, "
        "with the exclusion reported in the metric value's coverage detail."
    ),
    "info": (
        "Info severity: documentation only — the figure stands and nothing "
        "was excluded on account of this finding; it records a documented "
        "limitation of the inputs (e.g. the calc 0.3.0 per-trip VRH fallback "
        "where block_id is unavailable)."
    ),
}


def route_findings(
    conn,
    findings: list[Finding],
    calc_name: str,
    calc_version: str,
    period_start: date,
    period_end: date,
    scope: str | None = None,
    category: str = CATEGORY_NTD,
) -> list[str]:
    """Insert one dq.issues row per Finding; return the new issue ids.

    Each row carries: the finding's own issue_type, title, and SEVERITY
    (warning stays warning, blocking stays blocking), status 'open', the
    finding's source_record_ids (the raw records bounding/causing it), and a
    description that appends WHICH calculation (calc_name + calc_version)
    raised it over WHICH period plus the severity-specific consequence — so a
    data steward reading the issue knows exactly what happened to the figure.

    ``scope`` (handoff 0009): when given (a mode-scoped run, e.g.
    'mode:bus'), the description additionally names the metric-value scope
    the finding belongs to, so a mode-scoped finding is distinguishable from
    the fleet-wide ('agency') run's finding over the same records. Default
    None keeps the routed description byte-identical to pre-0009 runs.

    ``category`` (handoff 0014 / migration 0024): 'ntd' (default — every
    NTD-pipeline finding, gates certification) or 'ops' (operations-metric
    findings, e.g. an otp_v0 cadence refusal — owned and workflowed like
    any finding, but structurally excluded from the certification
    blocking-issue gate: an ops shortfall must never freeze a federal
    attestation). The ops runner passes 'ops'; no NTD call site changes.

    Returns the inserted issue_ids (as text) in input order. Raises on any
    insert failure — never swallows. Does not commit.
    """
    cur = conn.cursor()
    issue_ids: list[str] = []
    for finding in findings:
        scope_note = "" if scope is None else f" Metric-value scope: {scope!r}."
        description = (
            f"{finding.description}\n\n"
            f"Raised by calculation {calc_name} version {calc_version} for "
            f"period [{period_start.isoformat()}, {period_end.isoformat()}) "
            f"(half-open, UTC).{scope_note} "
            f"{_CONSEQUENCE_BY_SEVERITY[finding.severity]}"
        )
        cur.execute(
            _INSERT_ISSUE_SQL,
            (
                finding.issue_type,
                finding.severity,
                _STATUS,
                finding.title,
                description,
                list(finding.source_record_ids),
                category,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                f"dq.issues INSERT for issue_type={finding.issue_type!r} "
                f"({calc_name} {calc_version}) returned no issue_id — refusing "
                f"to continue with unrecorded DQ evidence."
            )
        issue_ids.append(str(row[0]))
    return issue_ids


def route_blocking_issues(
    conn,
    issues: list[Finding],
    calc_name: str,
    calc_version: str,
    period_start: date,
    period_end: date,
) -> list[str]:
    """0.1.0-compatible entry point: route findings that MUST all be blocking.

    Kept so existing call sites and historical recomputes work unchanged.
    Refuses (ValueError) any non-blocking finding — a warning routed through
    this path would silently masquerade as blocking, the opposite of routing
    findings with their own severity (use route_findings for mixed sets).
    """
    for finding in issues:
        if finding.severity != SEVERITY_BLOCKING:
            raise ValueError(
                f"route_blocking_issues received a finding with severity "
                f"{finding.severity!r} (issue_type={finding.issue_type!r}); "
                f"only '{SEVERITY_BLOCKING}' is accepted here — route mixed-"
                f"severity findings via route_findings."
            )
    return route_findings(
        conn, issues, calc_name, calc_version, period_start, period_end
    )
