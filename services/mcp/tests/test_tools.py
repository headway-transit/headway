"""Toolset invariants: no bare numbers, refusal passthrough, verify_claim
tri-state, empty periods explain themselves (handoff 0034, design points 2–3)."""

from __future__ import annotations

import pytest

from headway_mcp.tools import (
    NO_FIGURES_MESSAGE,
    REQUIRED_FIGURE_FIELDS,
    BareNumberError,
    HeadwayTools,
    _figure_payload,
)

from conftest import (
    CERTIFIED_ROW,
    FIGURE_ROW,
    LINEAGE_404_DETAIL,
    SCOPE_DENIAL_DETAIL,
    VERIFY_RESULT,
)

MVID = FIGURE_ROW["metric_value_id"]


# -- no bare numbers ---------------------------------------------------------


def test_metric_values_rows_carry_the_full_receipt(tools):
    result = tools.metric_values(metric="vrm")
    (figure,) = result["figures"]
    for field in REQUIRED_FIGURE_FIELDS:
        assert field in figure, f"figure payload missing {field}"
    # Verbatim: the exact value string and the calc library's detail JSON,
    # simulated flag included, untouched.
    assert figure["value"] == "9524.63"
    assert figure["detail"] == FIGURE_ROW["detail"]
    assert figure["detail"]["simulated_source_data"] is True
    # And the receipt pointer names the lineage walk.
    assert figure["receipt"]["metric_value_id"] == MVID
    assert "explain_figure" in figure["receipt"]["provenance"]


def test_a_row_missing_receipt_fields_is_refused_not_served():
    stripped = {"metric_value_id": "x", "value": "1.00"}
    with pytest.raises(BareNumberError) as excinfo:
        _figure_payload(stripped)
    assert "certification_status" in str(excinfo.value)


def test_certified_figures_keep_certification_reference_and_receipt(tools):
    result = tools.certified_figures()
    (figure,) = result["figures"]
    assert figure["certification_status"] == "certified"
    assert figure["certification"] == CERTIFIED_ROW["certification"]
    for field in REQUIRED_FIGURE_FIELDS:
        assert field in figure


# -- empty periods explain themselves ---------------------------------------


def test_empty_period_returns_refusal_text_never_bare_list(tools, fake_api):
    fake_api.metrics_rows = []
    result = tools.metric_values(metric="vrm", period_start="2031-01-01")
    assert result["figures"] == []
    assert result["no_figures"]["message"] == NO_FIGURES_MESSAGE
    assert "REFUSED" in result["no_figures"]["message"]
    assert "Do not treat this absence as zero" in result["no_figures"]["message"]
    assert result["no_figures"]["filters"]["period_start"] == "2031-01-01"


# -- refusal passthrough ------------------------------------------------------


def test_api_refusals_pass_through_verbatim(tools):
    result = tools.explain_figure("00000000-0000-0000-0000-000000000000")
    assert result["refusal"]["http_status"] == 404
    assert result["refusal"]["message"] == LINEAGE_404_DETAIL


def test_scope_denial_passes_through_verbatim(tools, fake_api):
    fake_api.deny_scope = True
    result = tools.metric_values()
    assert result["refusal"]["http_status"] == 403
    assert result["refusal"]["message"] == SCOPE_DENIAL_DETAIL


# -- verify_claim tri-state ---------------------------------------------------


def test_verify_claim_match_is_byte_exact(tools):
    result = tools.verify_claim(MVID, "9524.63")
    assert result["result"] == "match"
    # A match still ships the figure with its receipt — a matching number
    # can be uncertified or simulated, and the payload must show that.
    assert result["figure"]["certification_status"] == "uncertified"
    assert result["figure"]["detail"]["simulated_source_data"] is True


def test_verify_claim_mismatch_names_the_disagreement(tools):
    result = tools.verify_claim(MVID, "9524.6")
    assert result["result"] == "mismatch"
    (mismatch,) = result["mismatches"]
    assert mismatch == {"field": "value", "claimed": "9524.6", "stored": "9524.63"}
    assert result["figure"]["value"] == "9524.63"


def test_verify_claim_rounded_value_is_a_mismatch_not_close_enough(tools):
    # Byte comparison is the point: numerically-equal-after-rounding is
    # still a mismatch, because Headway never vouches for a number it did
    # not produce.
    result = tools.verify_claim(MVID, "9525")
    assert result["result"] == "mismatch"


def test_verify_claim_checks_claimed_period_too(tools):
    result = tools.verify_claim(
        MVID, "9524.63", claimed_period_start="2026-06-01"
    )
    assert result["result"] == "mismatch"
    (mismatch,) = result["mismatches"]
    assert mismatch["field"] == "period_start"
    assert mismatch["stored"] == "2026-07-01"


def test_verify_claim_unknown_id_is_no_such_figure(tools):
    result = tools.verify_claim("99999999-9999-9999-9999-999999999999", "1.00")
    assert result["result"] == "no_such_figure"
    assert "unresolved" in result["message"]


# -- nothing computed here ----------------------------------------------------


def test_explain_figure_serves_the_tree_verbatim(tools):
    result = tools.explain_figure(MVID)
    assert result["lineage"]["kind"] == "metric_value"
    assert result["lineage"]["inputs"][0]["kind"] == "raw_record"


def test_verify_certification_serves_the_verdict_verbatim(tools):
    result = tools.verify_certification(VERIFY_RESULT["certification_id"])
    assert result["verification"] == VERIFY_RESULT


def test_client_holds_no_database_credentials(client):
    # API-client-only architecture, asserted structurally: the whole service
    # imports no database driver and the client object only knows an HTTP
    # base URL + bearer key.
    import sys

    assert "psycopg" not in sys.modules
    assert not [a for a in vars(client) if "db" in a.lower() or "pg" in a.lower()]
