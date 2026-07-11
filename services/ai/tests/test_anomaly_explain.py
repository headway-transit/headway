"""The grounding gate around anomaly explanations.

Proves the two load-bearing properties:
1. the StubProvider template path yields drafts that PASS grounding
   (citations resolve, every number comes from the cited rows), and
2. a fabricating provider's draft is DROPPED loudly and returned in the
   rejected list — the finding survives, the ungrounded prose never does.
"""

from __future__ import annotations

import logging
from typing import Mapping

import pytest

from headway_ai.anomaly import detect_all, detect_metric_swings
from headway_ai.anomaly_explain import (
    allowed_numbers_for_rows,
    explain_findings,
)
from headway_ai.anomaly import normalize_history
from headway_ai.provider import LabeledOutput, StubProvider


MV_PREV = "5f3c2a9e-1d4b-4c8e-9f0a-7b6d5e4c3b2a"
MV_CUR = "6a4d3b0f-2e5c-4d9f-8a1b-9c8e7d6f5a4b"


def history() -> list[dict]:
    return [
        {
            "metric_value_id": MV_PREV,
            "metric": "vrm",
            "value": "11500.00",
            "period_start": "2026-04-01",
            "period_end": "2026-05-01",
            "calc_version": "0.2.0",
            "detail": {"coverage": "0.97"},
        },
        {
            "metric_value_id": MV_CUR,
            "metric": "vrm",
            "value": "16400.00",
            "period_start": "2026-05-01",
            "period_end": "2026-06-01",
            "calc_version": "0.2.0",
            "detail": {"coverage": "0.96"},
        },
    ]


class FabricatingProvider:
    """Deliberately hostile fake: injects a number absent from every row."""

    name = "fabricator"
    version = "666.0"

    def generate(self, prompt: str, context: Mapping[str, str]) -> LabeledOutput:
        return LabeledOutput(
            text="The metric moved by roughly 99999 units, a 42.6 percent jump.",
            provider_name=self.name,
            provider_version=self.version,
        )


class TestAllowedNumbers:
    def test_only_row_numbers_are_allowed(self):
        rows = normalize_history(history())
        allowed = set(allowed_numbers_for_rows(rows))
        assert {"11500.00", "16400.00", "0.97", "0.96", "2026"} <= allowed
        assert "99999" not in allowed
        assert "42.6" not in allowed


class TestStubProviderPath:
    def test_grounded_explanations_pass_and_are_labeled(self, capturing_connection):
        conn = capturing_connection({MV_PREV, MV_CUR})
        findings = detect_metric_swings(history())
        assert len(findings) == 1
        batch = explain_findings(conn, findings, history())
        assert batch.rejected == ()
        assert len(batch.explained) == 1
        explained = batch.explained[0]
        # Structurally labeled: LabeledOutput and GroundedDraft both frozen-True.
        assert explained.output.ai_generated is True
        assert explained.draft.ai_generated is True
        assert explained.eval_report.passed is True
        assert explained.eval_report.citation_resolution_rate == "1.0000"
        assert explained.eval_report.fabricated_number_count == 0
        # Every compared metric_value_id is cited by a claim.
        cited = {claim.cited_record_id for claim in explained.draft.claims}
        assert {MV_PREV, MV_CUR} <= cited
        assert all(
            claim.cited_record_kind == "computed.metric_values"
            for claim in explained.draft.claims
        )

    def test_stub_path_is_deterministic(self, capturing_connection):
        findings = detect_metric_swings(history())
        first = explain_findings(capturing_connection({MV_PREV, MV_CUR}), findings, history())
        second = explain_findings(capturing_connection({MV_PREV, MV_CUR}), findings, history())
        assert first.explained[0].output.text == second.explained[0].output.text
        assert first.explained[0].draft == second.explained[0].draft

    def test_default_provider_is_the_stub(self, capturing_connection):
        conn = capturing_connection({MV_PREV, MV_CUR})
        batch = explain_findings(conn, detect_metric_swings(history()), history())
        assert batch.explained[0].output.provider_name == StubProvider.name


class TestGroundingDropPath:
    def test_fabricating_provider_is_dropped_loudly(self, capturing_connection, caplog):
        conn = capturing_connection({MV_PREV, MV_CUR})
        findings = detect_metric_swings(history())
        with caplog.at_level(logging.ERROR, logger="headway_ai.anomaly_explain"):
            batch = explain_findings(
                conn, findings, history(), provider=FabricatingProvider()
            )
        # Dropped, never emitted: rejected list carries the failing report.
        assert batch.explained == ()
        assert len(batch.rejected) == 1
        rejected = batch.rejected[0]
        assert rejected.finding == findings[0]  # the FLAG survives intact
        assert rejected.eval_report.passed is False
        assert rejected.eval_report.fabricated_number_count >= 1
        # Loud log names the drop.
        assert any(
            "DROPPING ungrounded anomaly explanation" in record.message
            for record in caplog.records
        )

    def test_unresolvable_citation_is_also_dropped(self, capturing_connection, caplog):
        # Same draft, but the connection knows neither id: citation check fails.
        conn = capturing_connection(set())
        findings = detect_metric_swings(history())
        with caplog.at_level(logging.ERROR, logger="headway_ai.anomaly_explain"):
            batch = explain_findings(conn, findings, history())
        assert batch.explained == ()
        assert len(batch.rejected) == 1
        assert batch.rejected[0].eval_report.citation_resolution_rate != "1.0000"

    def test_finding_citing_unknown_row_fails_loudly(self, capturing_connection):
        findings = detect_metric_swings(history())
        with pytest.raises(ValueError, match="absent from the supplied history rows"):
            explain_findings(
                capturing_connection({MV_PREV, MV_CUR}), findings, history()[:1]
            )


class TestVersionChangeExplanation:
    def test_version_change_info_finding_explains_grounded(self, capturing_connection):
        rows = history()
        rows[1]["calc_version"] = "0.4.0"
        conn = capturing_connection({MV_PREV, MV_CUR})
        findings = detect_all(rows)
        batch = explain_findings(conn, findings, rows)
        assert batch.rejected == ()
        assert {e.finding.issue_type for e in batch.explained} >= {
            "anomaly_calc_version_change"
        }
