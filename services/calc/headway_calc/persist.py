"""Thin, injectable persistence for CalcResults. Matches handoff 0001 schema.

Writes one computed.metric_values row plus one lineage.edges row per consumed
input_record_id (ADR-0007: every reported value is traceable to its raw
records). Takes any DB-API 2.0 connection (paramstyle 'format'/'pyformat',
i.e. %s placeholders — psycopg-compatible); unit-testable with a fake
connection, no live database required. psycopg is an OPTIONAL extra
(``headway-calc[persist]``) — this module itself is stdlib-only.

Fail loudly: a result with value=None or any blocking issue is REFUSED —
persisting a guessed or gap-crossing number is never possible through this
path.
"""

from __future__ import annotations

from datetime import date

from headway_calc.types import CalcResult

#: Metric name (computed.metric_values.metric) per calc_name, per handoff 0001
#: (v0 metrics: 'vrm', 'vrh').
_METRIC_BY_CALC_NAME = {
    "vrm_v0": "vrm",
    "vrh_v0": "vrh",
}

_INSERT_METRIC_VALUE_SQL = (
    "INSERT INTO computed.metric_values "
    "(metric, unit, period_start, period_end, scope, value, calc_name, calc_version) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
    "RETURNING metric_value_id"
)

_INSERT_LINEAGE_EDGE_SQL = (
    "INSERT INTO lineage.edges "
    "(output_kind, output_id, transform_name, transform_version, input_kind, input_id) "
    "VALUES (%s, %s, %s, %s, %s, %s)"
)


def persist_result(
    conn,
    result: CalcResult,
    period_start: date,
    period_end: date,
    scope: str = "agency",
) -> str:
    """Persist a CalcResult: one computed.metric_values row + lineage edges.

    Refuses (raises ValueError) if the result carries blocking issues or has
    no value — blocking issues belong in dq.issues, never in
    computed.metric_values. Refuses unknown calc_names (no metric mapping).

    Emits one lineage.edges row per input_record_id:
    output_kind='computed.metric_values', output_id=<metric_value_id>,
    transform_name=calc_name, transform_version=calc_version,
    input_kind='raw.records', input_id=<record_id>.

    Returns the new metric_value_id (as text). Does NOT commit — transaction
    control belongs to the caller.
    """
    if result.blocking_issues:
        raise ValueError(
            f"Refusing to persist {result.calc_name} result: "
            f"{len(result.blocking_issues)} blocking issue(s) present "
            f"(first: {result.blocking_issues[0].issue_type}). Blocking issues "
            f"must be routed to dq.issues; a metric value is never written "
            f"over an unresolved gap."
        )
    if result.value is None:
        raise ValueError(
            f"Refusing to persist {result.calc_name} result: value is None."
        )
    metric = _METRIC_BY_CALC_NAME.get(result.calc_name)
    if metric is None:
        raise ValueError(
            f"Unknown calc_name {result.calc_name!r}: no computed.metric_values "
            f"metric mapping registered."
        )

    cur = conn.cursor()
    cur.execute(
        _INSERT_METRIC_VALUE_SQL,
        (
            metric,
            result.unit,
            period_start,
            period_end,
            scope,
            result.value,
            result.calc_name,
            result.calc_version,
        ),
    )
    metric_value_id = str(cur.fetchone()[0])

    for record_id in result.input_record_ids:
        cur.execute(
            _INSERT_LINEAGE_EDGE_SQL,
            (
                "computed.metric_values",
                metric_value_id,
                result.calc_name,
                result.calc_version,
                "raw.records",
                record_id,
            ),
        )
    return metric_value_id
