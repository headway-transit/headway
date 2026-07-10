"""Unit tests for the three harness checks against capturing fakes."""

from __future__ import annotations

import dataclasses

import pytest

from headway_ai.claims import Claim, GroundedDraft
from headway_ai.grounding import check_citations, check_fabrication, evaluate

METRIC_ID = "5f3c2a9e-1d4b-4c8e-9f0a-7b6d5e4c3b2a"
RAW_ID = "9c40aa1c9f0b3d5e7a2f4c6e8b0d1f3a5c7e9b2d4f6a8c0e1b3d5f7a9c2e4b6d"


def draft_of(*claims: Claim) -> GroundedDraft:
    return GroundedDraft(claims=claims, provider_name="stub", provider_version="0.1.0")


def claim(kind: str, record_id: str, text: str = "cited statement.", numbers=()) -> Claim:
    return Claim(
        text=text, cited_record_kind=kind, cited_record_id=record_id, numeric_values=numbers
    )


class TestCheckCitations:
    def test_resolving_citation_passes(self, capturing_connection):
        conn = capturing_connection({METRIC_ID})
        results = check_citations(conn, draft_of(claim("computed.metric_values", METRIC_ID)))
        assert len(results) == 1
        assert results[0].resolved is True
        assert results[0].reason == "resolved"

    def test_dangling_citation_fails(self, capturing_connection):
        conn = capturing_connection(set())
        results = check_citations(conn, draft_of(claim("computed.metric_values", METRIC_ID)))
        assert results[0].resolved is False
        assert METRIC_ID in results[0].reason

    def test_unknown_kind_fails_without_querying(self, capturing_connection):
        conn = capturing_connection({METRIC_ID})
        results = check_citations(conn, draft_of(claim("made.up_kind", METRIC_ID)))
        assert results[0].resolved is False
        assert "unknown record kind" in results[0].reason
        assert conn.executed == []  # an invented kind never reaches the database

    def test_queries_are_parameterized_per_handoff_0001_tables(self, capturing_connection):
        conn = capturing_connection({METRIC_ID, RAW_ID, "route-1", "trip-1", "17"})
        check_citations(
            conn,
            draft_of(
                claim("raw.records", RAW_ID),
                claim("canonical.routes", "route-1"),
                claim("canonical.trips", "trip-1"),
                claim("computed.metric_values", METRIC_ID),
                claim("lineage.edges", "17"),
            ),
        )
        assert [
            ("SELECT 1 FROM raw.records WHERE record_id = %s LIMIT 1", (RAW_ID,)),
            ("SELECT 1 FROM canonical.routes WHERE route_id = %s LIMIT 1", ("route-1",)),
            ("SELECT 1 FROM canonical.trips WHERE trip_id = %s LIMIT 1", ("trip-1",)),
            (
                "SELECT 1 FROM computed.metric_values WHERE metric_value_id::text = %s LIMIT 1",
                (METRIC_ID,),
            ),
            ("SELECT 1 FROM lineage.edges WHERE edge_id::text = %s LIMIT 1", ("17",)),
        ] == conn.executed
        # The record id is always a bound parameter, never interpolated.
        for sql, params in conn.executed:
            for value in params:
                assert value not in sql

    def test_vehicle_positions_resolve_via_lineage_graph(self, capturing_connection):
        node_id = "bus-42|2026-05-01T12:00:00Z|" + RAW_ID
        conn = capturing_connection({node_id})
        results = check_citations(
            conn, draft_of(claim("canonical.vehicle_positions", node_id))
        )
        assert results[0].resolved is True
        sql, params = conn.executed[0]
        assert "FROM lineage.edges" in sql
        assert params == ("canonical.vehicle_positions", node_id)

    def test_cursors_are_closed(self, capturing_connection):
        conn = capturing_connection({METRIC_ID})
        check_citations(conn, draft_of(claim("computed.metric_values", METRIC_ID)))
        assert all(cursor.closed for cursor in conn.cursors)


class TestCheckFabrication:
    def test_allowed_numbers_pass(self):
        draft = draft_of(
            claim(
                "computed.metric_values",
                METRIC_ID,
                text="VRM for May 2026 was 12,794.92 miles.",
                numbers=("12794.92",),
            )
        )
        results = check_fabrication(draft, {"12794.92", "2026"})
        assert results[0].ok
        assert results[0].fabricated_tokens == ()

    def test_unexplained_number_is_fabrication(self):
        draft = draft_of(
            claim(
                "computed.metric_values",
                METRIC_ID,
                text="VRM was 13,000.00 miles.",
            )
        )
        results = check_fabrication(draft, {"12794.92"})
        assert not results[0].ok
        assert results[0].fabricated_tokens == ("13,000.00",)

    def test_declared_numeric_values_are_also_checked(self):
        draft = draft_of(
            claim("computed.metric_values", METRIC_ID, text="no digits", numbers=("99",))
        )
        results = check_fabrication(draft, {"12794.92"})
        assert results[0].fabricated_tokens == ("99",)

    def test_record_count_whitelist(self):
        draft = draft_of(
            claim("computed.metric_values", METRIC_ID, text="Derived from 3 source records.")
        )
        assert not check_fabrication(draft, {"12794.92"})[0].ok
        assert check_fabrication(
            draft, {"12794.92"}, record_count_whitelist={"3"}
        )[0].ok

    def test_comparison_is_normalized_decimal_not_string(self):
        draft = draft_of(
            claim("computed.metric_values", METRIC_ID, text="VRM was 12,794.92 miles.")
        )
        # Allowed set uses the DB rendering; text uses thousands separators.
        assert check_fabrication(draft, {"12794.92"})[0].ok
        assert check_fabrication(draft, {"12794.920"})[0].ok

    def test_invalid_allowed_number_fails_loudly(self):
        draft = draft_of(claim("computed.metric_values", METRIC_ID))
        with pytest.raises(ValueError):
            check_fabrication(draft, {"not a number"})


class TestEvaluate:
    def test_pass_requires_full_resolution_and_zero_fabrication(self, capturing_connection):
        conn = capturing_connection({METRIC_ID})
        draft = draft_of(
            claim(
                "computed.metric_values",
                METRIC_ID,
                text="VRM for May 2026 was 12,794.92 miles.",
            )
        )
        report = evaluate(conn, draft, {"12794.92", "2026"})
        assert report.passed is True
        assert report.citation_resolution_rate == "1.0000"
        assert report.fabricated_number_count == 0

    def test_partial_resolution_fails(self, capturing_connection):
        conn = capturing_connection({METRIC_ID})
        draft = draft_of(
            claim("computed.metric_values", METRIC_ID, text="ok."),
            claim("computed.metric_values", "missing-id", text="dangling."),
        )
        report = evaluate(conn, draft, set())
        assert report.passed is False
        assert report.citation_resolution_rate == "0.5000"

    def test_single_fabrication_fails_even_with_full_resolution(self, capturing_connection):
        conn = capturing_connection({METRIC_ID})
        draft = draft_of(
            claim("computed.metric_values", METRIC_ID, text="VRM was 13,000.00 miles.")
        )
        report = evaluate(conn, draft, {"12794.92"})
        assert report.passed is False
        assert report.citation_resolution_rate == "1.0000"
        assert report.fabricated_number_count == 1

    def test_report_is_frozen(self, capturing_connection):
        conn = capturing_connection({METRIC_ID})
        report = evaluate(
            conn,
            draft_of(claim("computed.metric_values", METRIC_ID)),
            set(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.passed = True

    def test_nonterminating_rate_is_quantized(self, capturing_connection):
        conn = capturing_connection({METRIC_ID})
        draft = draft_of(
            claim("computed.metric_values", METRIC_ID),
            claim("computed.metric_values", "missing-1"),
            claim("computed.metric_values", "missing-2"),
        )
        report = evaluate(conn, draft, set())
        assert report.citation_resolution_rate == "0.3333"
        assert report.passed is False
