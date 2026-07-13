"""Thin, injectable persistence for CalcResults. Matches handoff 0001 schema
plus the migration-0010 detail column (handoff 0002).

Writes one computed.metric_values row (including the result's coverage detail
as JSONB — '{}' for detail-less 0.1.0 results, matching the column default)
plus one lineage.edges row per consumed input_record_id (ADR-0007: every
reported value is traceable to its raw records; for calc 0.2.0 the consumed
ids cover INCLUDED groups only — excluded groups' records are cited by their
warning findings in dq.issues, never by lineage). Takes any DB-API 2.0
connection (paramstyle 'format'/'pyformat', i.e. %s placeholders —
psycopg-compatible); unit-testable with a fake connection, no live database
required. psycopg is an OPTIONAL extra (``headway-calc[persist]``) — this
module itself is stdlib-only.

Fail loudly: a result with value=None or any blocking issue is REFUSED —
persisting a guessed or gap-crossing number is never possible through this
path. Warning findings do NOT block persistence (they are routed to dq.issues
by the runner with their own severity).
"""

from __future__ import annotations

import json
from datetime import date

from headway_calc.types import CalcResult

#: Metric name (computed.metric_values.metric) per calc_name, per handoff 0001
#: (v0 metrics: 'vrm', 'vrh') plus 'upt' (handoff 0005), 'voms'
#: (handoff 0009) and 'pmt' (handoff 0011). The DR calcs (handoff 0013) feed
#: the SAME metrics — DR is a mode, so its figures land in the existing
#: metric surfaces under DR mode/TOS scopes ('mode:DR', 'mode:DR:tos:<tos>');
#: dr_pmt_v0 deliberately feeds the existing 'pmt' persistence (the
#: handoff's "feeds pmt_v0's persistence/mode scoping").
_METRIC_BY_CALC_NAME = {
    "vrm_v0": "vrm",
    "vrh_v0": "vrh",
    "upt_v0": "upt",
    "voms_v0": "voms",
    "pmt_v0": "pmt",
    "dr_vrm_v0": "vrm",
    "dr_vrh_v0": "vrh",
    "dr_upt_v0": "upt",
    "dr_voms_v0": "voms",
    "dr_pmt_v0": "pmt",
    # OPERATIONS metrics (handoff 0014) — category 'ops' below.
    "otp_v0": "otp",
    "headway_adherence_v0": "headway_adherence",
}

#: computed.metric_values.category per calc (migration 0024 — the
#: OPERATIONS/NTD honesty boundary). Derived HERE from the calc registry,
#: never taken from a caller argument, so an ops calc cannot be persisted
#: mislabeled as an NTD figure (and vice versa). The database enforces the
#: consequence: a category='ops' row can never be certified
#: (metric_values_ops_never_certified CHECK).
_OPS_CALC_NAMES = frozenset({"otp_v0", "headway_adherence_v0"})

CATEGORY_NTD = "ntd"
CATEGORY_OPS = "ops"


def category_for_calc(calc_name: str) -> str:
    """The computed.metric_values.category a calc's figures persist under."""
    return CATEGORY_OPS if calc_name in _OPS_CALC_NAMES else CATEGORY_NTD

#: detail is bound as text and cast to JSONB in SQL (%s::jsonb) so the write
#: works identically across DB-API drivers without a JSON adapter.
_INSERT_METRIC_VALUE_SQL = (
    "INSERT INTO computed.metric_values "
    "(metric, unit, period_start, period_end, scope, value, calc_name, calc_version, detail, category) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s) "
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

    ``scope`` is the computed.metric_values.scope value — 'agency' (the
    default, fleet-wide) or a mode scope 'mode:<mode>' (handoff 0009; the
    handoff-0001 scope column, no migration).

    Refuses (raises ValueError) if the result carries blocking issues or has
    no value — blocking issues belong in dq.issues, never in
    computed.metric_values. Warning findings never refuse: the figure stands,
    the exclusions live in dq.issues. Refuses unknown calc_names (no metric
    mapping). The result's detail (coverage etc., calc 0.2.0) is written as
    JSONB; a detail-less (0.1.0) result writes '{}', the column default.

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

    detail_json = (
        "{}" if result.detail is None else json.dumps(result.detail.to_dict(), sort_keys=True)
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
            detail_json,
            category_for_calc(result.calc_name),
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
