"""The Headway MCP toolset — read-only, receipts structural, refusals pass through.

Binding invariants (handoff 0034, design point 2):

- **No tool returns a bare number.** Every figure payload carries, verbatim
  from the API, its ``value`` (a string — NUMERIC precision, never float),
  ``certification_status``, ``calc_name`` + ``calc_version``, its ``detail``
  JSON exactly as the calculation library persisted it (including any
  simulated-source flags), and a ``receipt`` pointer naming the
  ``metric_value_id`` and the tool that walks its provenance. A row missing
  any of those fields is refused loudly, never served stripped.
- **Refusals and empty periods return refusal text, never ``[]``** where the
  truth is "there is no figure, and here is why". API errors are carried
  verbatim (:class:`headway_mcp.client.ApiRefusal`).
- **Nothing is computed here.** These tools serve exactly what the API
  serves. No summing, rounding, filling, estimating, or reconciling —
  a figure originates only in the deterministic calculation library.
"""

from __future__ import annotations

from typing import Any

from .client import ApiRefusal, HeadwayClient

#: Fields every figure payload must carry (the no-bare-number invariant).
#: ``detail`` is where the calc library's verbatim per-figure evidence —
#: including simulated-source flags — lives.
REQUIRED_FIGURE_FIELDS = (
    "metric_value_id",
    "metric",
    "unit",
    "period_start",
    "period_end",
    "value",
    "calc_name",
    "calc_version",
    "certification_status",
    "detail",
)

#: Refusal-shaped explanation for an empty result set — the truthful answer
#: to "why is there no figure here", in plain language, including where the
#: refusal reasons live and the honest note that those surfaces are not yet
#: machine-readable (handoff 0034 Response, open question 1).
NO_FIGURES_MESSAGE = (
    "No computed figure matches this request. In Headway that means one of "
    "two things: the calculation has not been run for this period, or it "
    "ran and REFUSED to emit a figure — for example over an unresolved "
    "data-quality gap — because Headway never fills, interpolates, or "
    "invents a number. A refusal is recorded on the calculation run with "
    "its reasons; that calc-run surface (and the data-quality queue behind "
    "it) is not yet readable with a machine key, so ask a signed-in "
    "Headway user to check Calc Runs and the Data Quality queue for the "
    "specific refusal reason. Do not treat this absence as zero."
)


class BareNumberError(Exception):
    """The API served a figure row missing a receipt field. This should be
    impossible against a real Headway API; if it happens (schema drift, a
    proxy mangling responses), the tool refuses rather than serving a
    number without its provenance."""


def _refusal_payload(refusal: ApiRefusal) -> dict[str, Any]:
    """The API's refusal, passed through verbatim for the assistant."""
    return {
        "refusal": {
            "from": "headway-api",
            "http_status": refusal.http_status,
            "message": refusal.message,
        }
    }


def _figure_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Attach the receipt pointer to a verbatim API row — additive only.

    The row itself is not modified, reformatted, or rounded: ``value`` stays
    the exact string the API served, ``detail`` stays the calc library's
    verbatim evidence (simulated flags included)."""
    missing = [f for f in REQUIRED_FIGURE_FIELDS if f not in row]
    if missing:
        raise BareNumberError(
            "Refusing to serve a figure without its receipt: the API row is "
            f"missing {missing}. Every Headway figure carries its value (as "
            "an exact string), certification status, calculation "
            "name+version, verbatim detail, and metric_value_id."
        )
    return {
        **row,
        "receipt": {
            "metric_value_id": row["metric_value_id"],
            "provenance": (
                "Call explain_figure with this metric_value_id to walk this "
                "figure's lineage down to the raw source records."
            ),
            "verification": (
                "Call verify_claim with this metric_value_id and a claimed "
                "value to byte-check any restatement of this figure."
            ),
        },
    }


def _issue_headline(row: dict[str, Any]) -> dict[str, Any]:
    """A data-quality finding as a queue headline — VERBATIM from the API,
    led by what it is ABOUT in the agency's own words (title/description and
    the calc runner's frozen subject_context), never a bare issue UUID as the
    headline (handoff 0039, design point 4).

    The issue_id is carried so the assistant can call dq_issue for the full
    finding, but it rides BEHIND the human-readable fields, not as the lead.
    Everything is the API row untouched; nothing is summarised or invented."""
    return {
        "title": row.get("title"),
        "description": row.get("description"),
        "severity": row.get("severity"),
        "status": row.get("status"),
        "owner": row.get("owner"),
        # Verbatim agency-vocabulary context when the calc runner froze one;
        # null is the normal case (the finding predates it) — never invented.
        "subject_context": row.get("subject_context"),
        "created_at": row.get("created_at"),
        "issue_id": row.get("issue_id"),
    }


class HeadwayTools:
    """Tool implementations over :class:`HeadwayClient`. Kept separate from
    MCP registration so tests exercise them directly."""

    def __init__(self, client: HeadwayClient):
        self._client = client

    # -- computed values -----------------------------------------------------

    def metric_values(
        self,
        metric: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        try:
            rows = self._client.machine_metrics(
                metric, period_start, period_end, category
            )
        except ApiRefusal as refusal:
            return _refusal_payload(refusal)
        if not rows:
            return {
                "figures": [],
                "no_figures": {
                    "message": NO_FIGURES_MESSAGE,
                    "filters": {
                        "metric": metric,
                        "period_start": period_start,
                        "period_end": period_end,
                        "category": category,
                    },
                },
            }
        return {"figures": [_figure_payload(row) for row in rows]}

    # -- the lineage walk ----------------------------------------------------

    def explain_figure(self, metric_value_id: str) -> dict[str, Any]:
        try:
            tree = self._client.lineage(metric_value_id)
        except ApiRefusal as refusal:
            return _refusal_payload(refusal)
        return {
            "metric_value_id": metric_value_id,
            "lineage": tree,
            "reading_guide": (
                "This tree is Headway's 'explain this number' walk, served "
                "verbatim: each node names the transform (and version) that "
                "produced it from its inputs; leaves are content-addressed "
                "raw records exactly as received from the source."
            ),
        }

    # -- verify_claim: the tool that makes AI summaries checkable ------------

    def verify_claim(
        self,
        metric_value_id: str,
        claimed_value: str,
        claimed_period_start: str | None = None,
        claimed_period_end: str | None = None,
    ) -> dict[str, Any]:
        try:
            rows = self._client.machine_metrics()
        except ApiRefusal as refusal:
            return _refusal_payload(refusal)
        row = next(
            (r for r in rows if r.get("metric_value_id") == metric_value_id), None
        )
        if row is None:
            return {
                "result": "no_such_figure",
                "metric_value_id": metric_value_id,
                "message": (
                    "No figure with this metric_value_id exists in Headway's "
                    "store. A claim citing it cannot be verified — treat the "
                    "citation as unresolved, not as approximately right."
                ),
            }
        mismatches: list[dict[str, str]] = []
        stored_value = row["value"]
        if claimed_value.strip() != stored_value:
            mismatches.append(
                {
                    "field": "value",
                    "claimed": claimed_value,
                    "stored": stored_value,
                }
            )
        for field, claimed in (
            ("period_start", claimed_period_start),
            ("period_end", claimed_period_end),
        ):
            if claimed is not None and claimed.strip() != str(row[field]):
                mismatches.append(
                    {"field": field, "claimed": claimed, "stored": str(row[field])}
                )
        if mismatches:
            return {
                "result": "mismatch",
                "metric_value_id": metric_value_id,
                "mismatches": mismatches,
                "figure": _figure_payload(row),
                "message": (
                    "The claim does not match Headway's store (byte "
                    "comparison — Headway values are exact strings, so "
                    "'9524.6' is not '9524.63'). The stored figure, with "
                    "its receipt, is included."
                ),
            }
        return {
            "result": "match",
            "metric_value_id": metric_value_id,
            "figure": _figure_payload(row),
            "message": (
                "The claimed value matches Headway's store byte-for-byte. "
                "Note the figure's certification_status and any simulated "
                "flags in detail — a matching number can still be "
                "uncertified or simulated."
            ),
        }

    # -- public certified surface --------------------------------------------

    def certified_figures(self) -> dict[str, Any]:
        try:
            rows = self._client.public_certified()
        except ApiRefusal as refusal:
            return _refusal_payload(refusal)
        if not rows:
            return {
                "figures": [],
                "no_figures": {
                    "message": (
                        "No certified figures exist yet. Certification is a "
                        "deliberate human act by the certifying official; "
                        "until it happens, figures stay off this public "
                        "surface — absence here is not an error."
                    )
                },
            }
        return {"figures": [_figure_payload(row) for row in rows]}

    def verify_certification(self, certification_id: str) -> dict[str, Any]:
        try:
            verdict = self._client.public_verify_certification(certification_id)
        except ApiRefusal as refusal:
            return _refusal_payload(refusal)
        return {
            "certification_id": certification_id,
            "verification": verdict,
            "reading_guide": (
                "Served verbatim from Headway's tamper-evidence check: the "
                "stored certificate bytes re-verified against the stored "
                "Ed25519 signature, server-side. 'verified' means the "
                "record is exactly what was signed; anything else means it "
                "is not, and that is a finding."
            ),
        }

    # -- data-quality queue (scope read:dq, handoff 0039) --------------------

    def dq_summary(self, status: str | None = None) -> dict[str, Any]:
        """The queue in agency vocabulary: how many findings, by severity and
        by workflow state, and a page of them each described in plain
        language (route/vehicle/block, never a bare UUID as the headline)."""
        try:
            counts = self._client.dq_counts(status)
            page = self._client.dq_issues(status=status)
        except ApiRefusal as refusal:
            return _refusal_payload(refusal)
        return {
            "counts": {
                "total": counts["total"],
                "by_severity": counts["by_severity"],
                "by_status": counts["by_status"],
                "resolution_minutes_total": counts["resolution_minutes_total"],
            },
            "top_issues": [_issue_headline(row) for row in page["issues"]],
            "page": {
                "returned": len(page["issues"]),
                "total_matching": page["total"],
                "has_more": page["has_more"],
                "next_cursor": page["next_cursor"],
            },
            "reading_guide": (
                "Counts are over the WHOLE queue under this filter (not just "
                "the page): a card total never disagrees with the list below "
                "it. Each finding leads with what it is ABOUT in the agency's "
                "own words — its title/description and, when the calc runner "
                "resolved one, its subject_context (affected trips grouped by "
                "block, each with its route(s) and span). Call dq_issue with "
                "an issue_id for that finding's full description and the raw "
                "records it was raised over. 'blocking' findings are what "
                "stand between a period and a certifiable figure — see "
                "dq_blocking_for_period."
            ),
        }

    def dq_issue(self, issue_id: str) -> dict[str, Any]:
        """One finding, in full: its own plain-language description, its
        agency-vocabulary subject_context (verbatim, when the calc runner
        resolved one), and the complete list of raw source records it was
        raised over — the provenance that makes it checkable."""
        try:
            row = self._client.dq_issue(issue_id)
        except ApiRefusal as refusal:
            return _refusal_payload(refusal)
        return {
            "issue": row,
            "reading_guide": (
                "Served verbatim from Headway's data-quality queue. "
                "'description' is the finding's own plain-language account; "
                "'subject_context' (when present, not null) names the "
                "affected trips grouped by block with their route(s) and "
                "span, exactly as the calculation runner froze it — Headway "
                "never re-derives or invents a label. 'source_record_ids' is "
                "the complete, untruncated set of raw records this finding "
                "was raised over: the evidence, addressable one by one. This "
                "tool reads only; acknowledging or resolving a finding "
                "carries human accountability and is deliberately not a tool "
                "here."
            ),
        }

    def dq_blocking_for_period(self) -> dict[str, Any]:
        """What stands between the queue and certifiable figures right now:
        the OPEN, BLOCKING findings — the ones a calc run refuses over. This
        is the machine-readable half of the calc-runs refusal story."""
        try:
            page = self._client.dq_issues(status="open", severity="blocking")
        except ApiRefusal as refusal:
            return _refusal_payload(refusal)
        if not page["issues"]:
            return {
                "blocking_issues": [],
                "count": 0,
                "message": (
                    "No open, blocking data-quality findings match. That is "
                    "the ONLY thing this answers: it does not mean any period "
                    "is certifiable — a calculation still has to run and not "
                    "refuse for other reasons, and certification remains a "
                    "deliberate human act. It means the blocking-finding "
                    "queue is clear right now. Absence here is not a "
                    "green light; it is one cleared gate."
                ),
            }
        return {
            "blocking_issues": [_issue_headline(row) for row in page["issues"]],
            "count": len(page["issues"]),
            "total_matching": page["total"],
            "has_more": page["has_more"],
            "next_cursor": page["next_cursor"],
            "reading_guide": (
                "These are the OPEN findings at 'blocking' severity — the "
                "ones a calculation run refuses to emit a certifiable figure "
                "over (Headway never fills or interpolates across an "
                "unresolved gap). Each leads with what it is about in agency "
                "vocabulary; call dq_issue with its issue_id for the full "
                "description and the raw records behind it. Resolving them is "
                "a signed-in human's job — deliberately not a tool here."
            ),
        }

    # -- operations snapshot (scope read:ops, handoff 0039) ------------------

    def ops_snapshot(self, max_age_seconds: int | None = None) -> dict[str, Any]:
        """The live vehicle picture with staleness framing: last-seen ages
        from the database clock, count honesty (truncation stated), and — when
        the feed is quiet — WHY it is quiet, never a silent empty fleet."""
        try:
            snapshot = self._client.ops_vehicles(max_age_seconds)
        except ApiRefusal as refusal:
            return _refusal_payload(refusal)
        return {
            "snapshot": snapshot,
            "reading_guide": (
                "Operations data, served verbatim — never certifiable, never "
                "an NTD reported figure (the 'category':'ops' / 'ops_note' "
                "boundary is on the payload). 'as_of' is the database clock; "
                "each vehicle's 'age_seconds' is how stale ITS last position "
                "is against that clock — Headway shows last-seen, it never "
                "interpolates a position between reports. If 'truncated' is "
                "true the fleet is larger than one page (see 'note' and "
                "'total_in_window'); if 'vehicles' is empty the 'note' says "
                "whether the feed is stale or nothing was ever ingested — an "
                "empty list is a data-availability state, not an empty fleet."
            ),
        }
