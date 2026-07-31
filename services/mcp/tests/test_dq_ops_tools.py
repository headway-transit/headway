"""The DQ + ops tools (handoff 0039): agency vocabulary, refusal-over-empty,
no bare issue-UUID headlines, verbatim staleness framing, deliberate absences.

The tools consume the machine read:dq / read:ops endpoints (mirrors of the
human queue and live-map surfaces). A data-quality finding is NOT a figure —
it carries no value/receipt and does not go through the no-bare-number gate;
its invariant is different: it leads with what it is ABOUT (title,
description, subject_context) in the agency's own words, never a bare UUID.
"""

from __future__ import annotations

from headway_mcp.tools import _issue_headline

from conftest import (
    DQ_COUNTS,
    DQ_ISSUE_DETAIL,
    DQ_ISSUE_ID,
    DQ_SUMMARY_ROW,
    OPS_SNAPSHOT,
    SCOPE_DENIAL_DETAIL,
)


# -- dq_summary: agency vocabulary, counts over the whole queue --------------


def test_dq_summary_leads_with_agency_vocabulary_not_a_bare_uuid(tools):
    result = tools.dq_summary()
    (headline,) = result["top_issues"]
    # The finding leads with WHAT IT IS ABOUT — title, description, and the
    # calc runner's frozen block/route context — not a bare issue UUID.
    assert headline["title"] == DQ_SUMMARY_ROW["title"]
    assert headline["description"] == DQ_SUMMARY_ROW["description"]
    assert headline["subject_context"] == DQ_SUMMARY_ROW["subject_context"]
    assert headline["severity"] == "blocking"
    # The id is carried (so dq_issue can be called) but rides behind the
    # human-readable fields — it is not the headline.
    assert headline["issue_id"] == DQ_ISSUE_ID
    keys = list(headline.keys())
    assert keys.index("title") < keys.index("issue_id")


def test_dq_summary_counts_are_over_the_whole_queue(tools):
    result = tools.dq_summary()
    assert result["counts"]["total"] == DQ_COUNTS["total"]
    assert result["counts"]["by_severity"] == DQ_COUNTS["by_severity"]
    assert result["counts"]["by_status"] == DQ_COUNTS["by_status"]
    # The page block states what was NOT loaded — never a "of what's loaded" lie.
    assert result["page"]["total_matching"] == 1
    assert result["page"]["has_more"] is False


def test_dq_summary_passes_status_filter_through(tools, fake_api):
    tools.dq_summary(status="open")
    paths = [str(r.url) for r in fake_api.requests]
    assert any("status=open" in p and "/machine/dq/issues" in p for p in paths)


def test_dq_summary_scope_denial_passes_through_verbatim(tools, fake_api):
    fake_api.deny_scope = True
    result = tools.dq_summary()
    assert result["refusal"]["http_status"] == 403
    assert result["refusal"]["message"] == SCOPE_DENIAL_DETAIL


# -- dq_issue: full description + provenance ---------------------------------


def test_dq_issue_serves_full_description_and_provenance(tools):
    result = tools.dq_issue(DQ_ISSUE_ID)
    issue = result["issue"]
    assert issue["description"] == DQ_ISSUE_DETAIL["description"]
    assert issue["subject_context"] == DQ_ISSUE_DETAIL["subject_context"]
    # The complete, untruncated provenance array — the evidence, one by one.
    assert issue["source_record_ids"] == ["rec-aaa", "rec-bbb", "rec-ccc"]


def test_dq_issue_reading_guide_states_read_only_no_resolve(tools):
    result = tools.dq_issue(DQ_ISSUE_ID)
    guide = result["reading_guide"]
    assert "reads only" in guide or "read" in guide.lower()
    assert "resolv" in guide.lower()


def test_dq_issue_unknown_id_passes_refusal_through_verbatim(tools):
    result = tools.dq_issue("99999999-9999-9999-9999-999999999999")
    assert result["refusal"]["http_status"] == 404
    assert result["refusal"]["message"] == "No data-quality issue with that id exists."


# -- dq_blocking_for_period: the calc-runs refusal story ---------------------


def test_dq_blocking_for_period_lists_open_blocking_findings(tools):
    result = tools.dq_blocking_for_period()
    assert result["count"] == 1
    (headline,) = result["blocking_issues"]
    assert headline["severity"] == "blocking"
    assert headline["title"] == DQ_SUMMARY_ROW["title"]


def test_dq_blocking_for_period_filters_open_and_blocking(tools, fake_api):
    tools.dq_blocking_for_period()
    (path,) = [str(r.url) for r in fake_api.requests]
    assert "status=open" in path
    assert "severity=blocking" in path


def test_dq_blocking_empty_is_refusal_text_not_bare_list(tools, fake_api):
    fake_api.dq_page = {
        "issues": [],
        "total": 0,
        "limit": 50,
        "next_cursor": None,
        "has_more": False,
    }
    result = tools.dq_blocking_for_period()
    assert result["blocking_issues"] == []
    assert result["count"] == 0
    # An empty blocking queue is explicitly NOT a certification green light.
    assert "not a green light" in result["message"]
    assert "certifiable" in result["message"]


def test_dq_blocking_scope_denial_passes_through_verbatim(tools, fake_api):
    fake_api.deny_scope = True
    result = tools.dq_blocking_for_period()
    assert result["refusal"]["http_status"] == 403


# -- ops_snapshot: staleness framing, verbatim, truncated preserved ----------


def test_ops_snapshot_serves_the_snapshot_verbatim(tools):
    result = tools.ops_snapshot()
    snap = result["snapshot"]
    assert snap == OPS_SNAPSHOT
    # The load-bearing count-honesty and ops-boundary fields survive intact.
    assert snap["truncated"] is False
    assert snap["category"] == "ops"
    assert "ops_note" in snap


def test_ops_snapshot_reading_guide_forbids_interpolation(tools):
    result = tools.ops_snapshot()
    guide = result["reading_guide"]
    assert "interpolate" in guide.lower()
    assert "empty fleet" in guide.lower()


def test_ops_snapshot_passes_max_age_through(tools, fake_api):
    tools.ops_snapshot(max_age_seconds=60)
    (path,) = [str(r.url) for r in fake_api.requests]
    assert "max_age_seconds=60" in path


def test_ops_snapshot_stale_note_is_carried_verbatim(tools, fake_api):
    stale = {
        **OPS_SNAPSHOT,
        "vehicles": [],
        "vehicle_count": 0,
        "total_in_window": 0,
        "note": (
            "No vehicle has reported a position in the last 60 seconds. The "
            "newest position on record is 7200 seconds old — the feed is "
            "stale or service is not running, not an empty fleet."
        ),
    }
    fake_api.ops_snapshot = stale
    result = tools.ops_snapshot(max_age_seconds=60)
    assert result["snapshot"]["vehicles"] == []
    assert "stale" in result["snapshot"]["note"]


def test_ops_snapshot_scope_denial_passes_through_verbatim(tools, fake_api):
    fake_api.deny_scope = True
    result = tools.ops_snapshot()
    assert result["refusal"]["http_status"] == 403


# -- the headline helper: no bare UUID as the lead ---------------------------


def test_issue_headline_leads_with_human_readable_fields():
    headline = _issue_headline(DQ_SUMMARY_ROW)
    keys = list(headline.keys())
    assert keys[0] == "title"
    assert "description" in keys
    assert "subject_context" in keys
    # A queue list row carries no source_record_ids (that is on the detail
    # endpoint only) — the headline must not invent one.
    assert "source_record_ids" not in headline
