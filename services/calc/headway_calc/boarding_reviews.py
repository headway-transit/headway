"""The two ends of the human-in-the-loop revenue review (handoff 0040).

The calculation cannot decide every no-run boarding. A boarding fired inside
the day's revenue-service window with nobody logged into a run is either
non-revenue prep or an extra bus running real riders, and no rule in the NTD
manual separates those — only a person who knows the day's dispatch decisions
can. So the calculation refuses to guess, holds the boarding OUT of the
figure, and hands it over. This module is the hand-over:

- :func:`persist_review_items` writes what the calculation could not decide
  into ``dq.boarding_revenue_reviews`` — the queue an analyst works.
- :func:`load_boarding_reviews` reads back what analysts have decided, so the
  next run can count (or exclude) those boardings and carry the reasons.

Two properties are load-bearing and both are enforced here rather than hoped
for:

**A human decision is never overwritten by a machine.** Re-running the
calculation refreshes the CONTEXT of an undecided row and stops dead at any
row somebody has already answered. The UPSERT's own WHERE clause says so, in
SQL, so it holds even if a future caller forgets.

**A missing table is not a silent behaviour change.** On a database that
predates migration 0040 the loader returns an empty map and says so loudly in
the log: with no queue there can be no decisions, so every ambiguous boarding
stays held — exactly upt_v0 0.3.0's answer, which is the conservative one.

Takes any DB-API 2.0 connection (%s placeholders — psycopg-compatible);
unit-testable with a fake connection. Does NOT commit: transaction control
belongs to the caller, exactly as headway_calc.dq does.
"""

from __future__ import annotations

import logging
from datetime import date

from headway_calc.types import BoardingReviewItem, HumanBoardingVerdict

_logger = logging.getLogger(__name__)

#: The queue write. ON CONFLICT refreshes only what a NEW RUN legitimately
#: knows better — the reason it is still pending, which calculation version
#: said so, and when it was last seen — and the WHERE clause makes the whole
#: statement a no-op on a row a human has already answered. A decision, once
#: recorded, is immune to every subsequent run.
_UPSERT_REVIEW_SQL = (
    "INSERT INTO dq.boarding_revenue_reviews "
    "(passenger_event_id, source_record_id, service_date, event_timestamp, "
    "vehicle_id, event_count, suggested_verdict, suggested_reason, "
    "calc_name, calc_version, period_start, period_end) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (passenger_event_id) DO UPDATE SET "
    "suggested_reason = EXCLUDED.suggested_reason, "
    "calc_name = EXCLUDED.calc_name, "
    "calc_version = EXCLUDED.calc_version, "
    "period_start = EXCLUDED.period_start, "
    "period_end = EXCLUDED.period_end, "
    "last_seen_at = now() "
    "WHERE dq.boarding_revenue_reviews.verdict IS NULL"
)

#: Migration 0040 is additive and the agency updater applies migrations BEFORE
#: rebuilding services (handoff 0025), so in a supported deployment the table
#: is always there. A developer database that has not been migrated yet is the
#: one case that is not — and it must not take a whole calculation run down
#: with it. Probed ONCE per call, and only when a run actually has boardings
#: to hand over, so every pre-0040 call site issues no extra query at all.
#: Probing rather than catching, deliberately: a failed INSERT would have to
#: be rolled back, and the rollback would discard the data-quality findings
#: this same transaction has already committed to.
_TABLE_EXISTS_SQL = (
    "SELECT 1 FROM information_schema.tables "
    "WHERE table_schema = 'dq' AND table_name = 'boarding_revenue_reviews'"
)

#: The decisions this run must honour: every boarding a human has classified
#: whose service date falls in the run's half-open period. Ordered so a
#: recompute reads them identically every time.
_SELECT_REVIEWS_SQL = (
    "SELECT passenger_event_id, verdict, justification, classified_by, "
    "classified_at FROM dq.boarding_revenue_reviews "
    "WHERE verdict IS NOT NULL "
    "AND service_date >= %s AND service_date < %s "
    "ORDER BY service_date, passenger_event_id"
)


def persist_review_items(
    conn,
    items: list[BoardingReviewItem],
    *,
    calc_name: str,
    calc_version: str,
    period_start: date,
    period_end: date,
) -> int:
    """Write the boardings this run could not decide into the review queue.

    Returns how many rows were inserted or refreshed — which is NOT
    ``len(items)`` when some of those boardings have already been answered,
    and that difference is the point: those rows are left exactly as the human
    left them.

    On a database predating migration 0040 the queue does not exist yet;
    nothing is written, a WARNING says so by name, and the run continues. That
    is not a silent drop: every one of these boardings is ALSO cited by its
    own 'boarding_pending_revenue_review' data-quality finding in the same
    transaction, so the evidence lands either way — what is missing is only
    the place to answer it.

    Every other database error propagates. A boarding held out of a figure
    that nobody can release is the dead end this wave exists to close, so a
    real failure to hand one over is loud, not logged and forgotten.
    """
    if not items:
        return 0
    cur = conn.cursor()
    cur.execute(_TABLE_EXISTS_SQL)
    if cur.fetchone() is None:
        _logger.warning(
            "dq.boarding_revenue_reviews does not exist (pre-migration-0040 "
            "database): %d boarding(s) this run could not classify were not "
            "handed to the review queue and cannot be answered by an analyst "
            "yet. They are still held OUT of the figure and still cited by "
            "their own data-quality findings. Apply migration 0040 to open "
            "the review queue.",
            len(items),
        )
        return 0
    written = 0
    for item in items:
        cur.execute(
            _UPSERT_REVIEW_SQL,
            (
                item.passenger_event_id,
                item.source_record_id,
                item.service_date,
                item.event_timestamp,
                item.vehicle_id,
                item.event_count,
                item.suggested_verdict,
                item.suggested_reason,
                calc_name,
                calc_version,
                period_start,
                period_end,
            ),
        )
        written += max(cur.rowcount or 0, 0)
    return written


def load_boarding_reviews(
    conn,
    period_start: date,
    period_end: date,
) -> dict[str, HumanBoardingVerdict]:
    """Load the human decisions covering one run period, keyed by
    ``passenger_event_id``.

    A database predating migration 0040 (relation does not exist, SQLSTATE
    42P01 — the load_attestations precedent) returns an empty map after
    rolling back the failed statement and logging a WARNING: with no queue
    there can be no decisions, so every ambiguous no-run boarding stays held
    pending exactly as upt_v0 0.3.0 held it. Any other database error
    propagates unchanged.
    """
    from headway_calc.settings import _is_undefined_table

    cur = conn.cursor()
    try:
        cur.execute(_SELECT_REVIEWS_SQL, (period_start, period_end))
    except Exception as exc:  # noqa: BLE001 — re-raised unless 42P01
        if not _is_undefined_table(exc):
            raise
        conn.rollback()
        _logger.warning(
            "dq.boarding_revenue_reviews does not exist (pre-migration-0040 "
            "database): no human revenue classifications are loadable, so "
            "every ambiguous no-run boarding stays held out of the figure "
            "pending review, exactly as upt_v0 0.3.0 held it. Apply "
            "migration 0040 to open the review queue."
        )
        return {}
    return {
        str(row[0]): HumanBoardingVerdict(
            passenger_event_id=str(row[0]),
            verdict=row[1],
            justification=row[2],
            classified_by=row[3],
            classified_at=row[4],
        )
        for row in cur.fetchall()
    }


__all__ = ["load_boarding_reviews", "persist_review_items"]
