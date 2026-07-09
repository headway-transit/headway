"""Routing of BlockingIssues into dq.issues. Matches handoff 0001.

When a calculation refuses to emit a value over an unresolved gap, the
evidence of that refusal must land somewhere actionable: one dq.issues row per
BlockingIssue, severity 'blocking', status 'open', so the DQ resolution
workflow (owner assignment, resolution) can pick it up. Takes any DB-API 2.0
connection (%s placeholders — psycopg-compatible); unit-testable with a fake
connection. Stdlib only.

Fail loudly: this module NEVER swallows an insert failure — any exception from
the database propagates unchanged. A blocking issue that cannot be recorded is
itself a loud failure, never a silent one. Does NOT commit — transaction
control belongs to the caller (see headway_calc.runner for the
fail-loudly-first two-transaction design).
"""

from __future__ import annotations

from datetime import date

from headway_calc.types import BlockingIssue

#: Column names exactly per handoff 0001 (dq.issues). issue_id, created_at,
#: owner, resolved_at, resolution take their schema defaults.
_INSERT_ISSUE_SQL = (
    "INSERT INTO dq.issues "
    "(issue_type, severity, status, title, description, source_record_ids) "
    "VALUES (%s, %s, %s, %s, %s, %s) "
    "RETURNING issue_id"
)

_SEVERITY = "blocking"
_STATUS = "open"


def route_blocking_issues(
    conn,
    issues: list[BlockingIssue],
    calc_name: str,
    calc_version: str,
    period_start: date,
    period_end: date,
) -> list[str]:
    """Insert one dq.issues row per BlockingIssue; return the new issue ids.

    Each row carries: the issue's own issue_type and title, severity
    'blocking', status 'open', the issue's source_record_ids (the raw records
    bounding/causing the gap), and a description that appends WHICH calculation
    (calc_name + calc_version) refused over WHICH period — so a data steward
    reading the issue knows exactly what figure is blocked.

    Returns the inserted issue_ids (as text) in input order. Raises on any
    insert failure — never swallows. Does not commit.
    """
    cur = conn.cursor()
    issue_ids: list[str] = []
    for issue in issues:
        description = (
            f"{issue.description}\n\n"
            f"Raised by calculation {calc_name} version {calc_version} for "
            f"period [{period_start.isoformat()}, {period_end.isoformat()}) "
            f"(half-open, UTC). The calculation refused to emit a value over "
            f"this unresolved gap; no computed.metric_values row was written."
        )
        cur.execute(
            _INSERT_ISSUE_SQL,
            (
                issue.issue_type,
                _SEVERITY,
                _STATUS,
                issue.title,
                description,
                list(issue.source_record_ids),
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                f"dq.issues INSERT for issue_type={issue.issue_type!r} "
                f"({calc_name} {calc_version}) returned no issue_id — refusing "
                f"to continue with unrecorded blocking evidence."
            )
        issue_ids.append(str(row[0]))
    return issue_ids
