"""HeadwayClient against the contract-shaped fake transport (no live API)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from headway_client import HeadwayApiError, HeadwayClient, login
from conftest import (
    MACHINE_KEY,
    RATE_LIMITED_KEY,
    SESSION_TOKEN,
    VRM_ID,
)


def machine_client(transport) -> HeadwayClient:
    return HeadwayClient("http://fake", token=MACHINE_KEY, transport=transport)


def session_client(transport) -> HeadwayClient:
    return HeadwayClient("http://fake", token=SESSION_TOKEN, transport=transport)


# -- credential dispatch -----------------------------------------------------


def test_machine_key_reads_machine_metrics(transport):
    with machine_client(transport) as hw:
        assert hw.uses_machine_key
        values = hw.metric_values()
    assert {v.metric for v in values} == {"vrm", "upt", "otp"}


def test_session_token_reads_human_metrics_values(transport):
    with session_client(transport) as hw:
        assert not hw.uses_machine_key
        values = hw.metric_values(metric="vrm")
    assert len(values) == 1
    assert values[0].metric_value_id == VRM_ID


def test_no_credential_fails_loudly_with_help(transport):
    with HeadwayClient("http://fake", transport=transport) as hw:
        with pytest.raises(HeadwayApiError) as excinfo:
            hw.metric_values()
    assert excinfo.value.status_code == 401
    assert "public_certified()" in excinfo.value.detail


def test_machine_and_session_metric_reads_agree(transport):
    """The dispatch changes the door, never the data (the API's own
    same-query guarantee, asserted here from the client's side)."""
    with machine_client(transport) as hw:
        via_machine = hw.metric_values(metric="upt")
    with session_client(transport) as hw:
        via_session = hw.metric_values(metric="upt")
    assert via_machine == via_session


# -- filters -----------------------------------------------------------------


def test_category_filter_reaches_the_wire(transport):
    with machine_client(transport) as hw:
        ops_only = hw.metric_values(category="ops")
    assert [v.metric for v in ops_only] == ["otp"]
    assert all(v.category == "ops" for v in ops_only)


def test_period_filters_serialized_as_iso_dates(transport):
    with machine_client(transport) as hw:
        values = hw.metric_values(
            period_start=dt.date(2026, 7, 9), period_end=dt.date(2026, 7, 11)
        )
    assert len(values) == 3


# -- figures stay exact --------------------------------------------------------


def test_value_is_verbatim_string_and_exact_decimal(transport):
    with machine_client(transport) as hw:
        (vrm,) = hw.metric_values(metric="vrm")
    assert vrm.value == "12794.92"  # verbatim, as served
    assert vrm.value_decimal == Decimal("12794.92")
    assert isinstance(vrm.value_decimal, Decimal)


def test_detail_served_verbatim(transport):
    with machine_client(transport) as hw:
        (vrm,) = hw.metric_values(metric="vrm")
    assert vrm.detail["coverage"] == "0.9263"  # ratio stays a string


# -- simulated-data rule -------------------------------------------------------


def test_simulated_flag_matches_house_rule(transport):
    with machine_client(transport) as hw:
        values = {v.metric: v for v in hw.metric_values()}
    assert values["upt"].simulated is True  # tides_simulated in source_mix
    assert values["otp"].simulated is False  # gtfsrt only
    assert values["vrm"].simulated is False  # no source_mix in detail
    assert values["vrm"].source_mix is None  # basis stays inspectable


# -- public certified ----------------------------------------------------------


def test_public_certified_needs_no_credential(transport):
    with HeadwayClient("http://fake", transport=transport) as hw:
        rows = hw.public_certified()
    assert [r.metric for r in rows] == ["vrm"]
    assert all(r.certification_status == "certified" for r in rows)
    assert all(r.category == "ntd" for r in rows)


# -- compare -------------------------------------------------------------------


def test_compare_parses_full_response_with_missing_cells(transport):
    with session_client(transport) as hw:
        cmp = hw.compare(
            "vrh",
            ["2026-07-01..2026-08-01", "2026-06-01..2026-07-01"],
            scopes=["agency", "mode:bus"],
        )
    assert cmp.metric == "vrh"
    assert cmp.comparands[0].baseline is True
    agency = cmp.rows[0]
    assert agency.cells[1].delta_vs_baseline == "-70.75"  # verbatim string
    assert agency.cells[1].delta_vs_baseline_decimal == Decimal("-70.75")
    bus = cmp.rows[1]
    assert bus.cells[0].value is None
    assert "never invented" in bus.cells[0].missing_reason
    assert cmp.mixed_certification is True


def test_compare_with_machine_key_relays_server_401(transport):
    with machine_client(transport) as hw:
        with pytest.raises(HeadwayApiError) as excinfo:
            hw.compare("vrh", ["2026-07-01..2026-08-01", "2026-06-01..2026-07-01"])
    assert excinfo.value.status_code == 401


# -- dq ------------------------------------------------------------------------


def test_dq_issues_and_counts_with_session(transport):
    with session_client(transport) as hw:
        issues = hw.dq_issues()
        open_issues = hw.dq_issues(status="open")
        counts = hw.dq_issue_counts()
    assert len(issues) == 2
    assert [i.status for i in open_issues] == ["open"]
    assert issues[0].resolution_minutes is None  # unmeasured stays None
    assert issues[1].resolution_minutes == 12
    assert counts.total == 2
    assert counts.by_severity["blocking"] == 1
    assert counts.by_status["resolved"] == 1


def test_dq_unknown_status_relays_plain_language_422(transport):
    with session_client(transport) as hw:
        with pytest.raises(HeadwayApiError) as excinfo:
            hw.dq_issues(status="bogus")
    assert excinfo.value.status_code == 422
    assert "not a data-quality status Headway knows" in excinfo.value.detail


# -- errors fail loudly ----------------------------------------------------------


def test_rate_limit_surfaces_retry_after(transport):
    with HeadwayClient(
        "http://fake", token=RATE_LIMITED_KEY, transport=transport
    ) as hw:
        with pytest.raises(HeadwayApiError) as excinfo:
            hw.machine_metrics()
    assert excinfo.value.status_code == 429
    assert excinfo.value.retry_after_seconds == 7


def test_unknown_figure_404_carries_server_detail(transport):
    with machine_client(transport) as hw:
        with pytest.raises(HeadwayApiError) as excinfo:
            hw.lineage("not-a-real-id")
    assert excinfo.value.status_code == 404
    assert "No reported figure with that id exists." == excinfo.value.detail


# -- login ------------------------------------------------------------------------


def test_login_returns_session_token(transport):
    token = login("http://fake", "vera", "viewer-pass-1", transport=transport)
    assert token == SESSION_TOKEN


def test_login_failure_relays_server_message(transport):
    with pytest.raises(HeadwayApiError) as excinfo:
        login("http://fake", "vera", "wrong", transport=transport)
    assert excinfo.value.status_code == 401
    assert "was not recognized" in excinfo.value.detail
