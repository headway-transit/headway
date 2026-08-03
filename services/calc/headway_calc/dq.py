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

import json
from datetime import date

from headway_calc.subjects import resolve_contexts
from headway_calc.types import SEVERITY_BLOCKING, Finding

#: Column names exactly per handoff 0001 (dq.issues). issue_id, created_at,
#: owner, resolved_at, resolution take their schema defaults.
_INSERT_ISSUE_SQL = (
    "INSERT INTO dq.issues "
    "(issue_type, severity, status, title, description, source_record_ids, category) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
    "RETURNING issue_id"
)

#: The migration-0035 variant: the same row plus the resolved, frozen
#: subject context (handoff 0029). Bound as TEXT and cast in SQL
#: (``%s::jsonb``) — the persist.py precedent — so this module keeps its
#: stdlib-only, driver-free promise.
_INSERT_ISSUE_WITH_CONTEXT_SQL = (
    "INSERT INTO dq.issues "
    "(issue_type, severity, status, title, description, source_record_ids, "
    "category, subject_context) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb) "
    "RETURNING issue_id"
)

#: Migration 0035 is ADDITIVE, and the agency updater applies migrations
#: BEFORE rebuilding services (handoff 0025) — so in a supported deployment
#: the column is always there by the time this code runs. A developer
#: database that has not been migrated yet is the one case that is not, and
#: it must not lose DQ evidence over a display feature: this probe (issued
#: at most once per call, and only when a finding actually carries a
#: subject) selects the pre-0035 INSERT instead. Byte-identical to pre-0029
#: behaviour, which is exactly what "the migration is additive" has to mean
#: in both directions.
_SUBJECT_CONTEXT_COLUMN_SQL = (
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = 'dq' AND table_name = 'issues' "
    "AND column_name = 'subject_context'"
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


def _column_exists(conn) -> bool:
    """Does dq.issues.subject_context exist (migration 0035)?

    Asked at most once per route_findings call, and only when a finding
    actually carries a subject — so the pre-0029 path issues no extra query
    whatsoever. Not a swallow: nothing is hidden, the finding still lands
    with every field it had before the column existed.
    """
    cur = conn.cursor()
    cur.execute(_SUBJECT_CONTEXT_COLUMN_SQL)
    return cur.fetchone() is not None


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

    ``Finding.subject`` (handoff 0029 / migration 0035): a finding that
    names the canonical rows it is about has those ids resolved HERE, once,
    into the agency's own vocabulary — block, route, first and last
    scheduled departure — and the result is frozen on the row
    (``dq.issues.subject_context``). Frozen, because a finding must read the
    same in an audit years later even after the agency renames a route; the
    ids are stored alongside so any reader can re-derive. The whole batch
    resolves in ONE query (headway_calc.subjects), and a batch where no
    finding carries a subject issues no query at all.

    Returns the inserted issue_ids (as text) in input order. Raises on any
    insert failure — never swallows. Does not commit.
    """
    cur = conn.cursor()
    contexts = resolve_contexts(conn, list(findings))
    has_context_column = any(c is not None for c in contexts) and _column_exists(
        conn
    )
    issue_ids: list[str] = []
    for finding, context in zip(findings, contexts):
        scope_note = "" if scope is None else f" Metric-value scope: {scope!r}."
        description = (
            f"{finding.description}\n\n"
            f"Raised by calculation {calc_name} version {calc_version} for "
            f"period [{period_start.isoformat()}, {period_end.isoformat()}) "
            f"(half-open, UTC).{scope_note} "
            f"{_CONSEQUENCE_BY_SEVERITY[finding.severity]}"
        )
        base_params = (
            finding.issue_type,
            finding.severity,
            _STATUS,
            finding.title,
            description,
            list(finding.source_record_ids),
            category,
        )
        if has_context_column:
            cur.execute(
                _INSERT_ISSUE_WITH_CONTEXT_SQL,
                base_params
                + (
                    None
                    if context is None
                    else json.dumps(context, sort_keys=True),
                ),
            )
        else:
            cur.execute(_INSERT_ISSUE_SQL, base_params)
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
