"""Runner: fake-conn insert assertions, report shape, CLI refusal, determinism.

The fake connection below answers the three SQL shapes the runner and the
grounding harness issue (history SELECT, citation SELECT 1, dq INSERT
RETURNING). No live database, network, or clock anywhere.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Mapping

import pytest

from headway_ai.anomaly import ISSUE_TYPE_COVERAGE_DROP, ISSUE_TYPE_SWING
from headway_ai.anomaly_runner import (
    AnomalyRunReport,
    load_metric_history,
    main,
    run_anomaly_scan,
)
from headway_ai.provider import LabeledOutput


MV_PREV = "5f3c2a9e-1d4b-4c8e-9f0a-7b6d5e4c3b2a"
MV_CUR = "6a4d3b0f-2e5c-4d9f-8a1b-9c8e7d6f5a4b"

#: (metric_value_id, metric, value, period_start, period_end, calc_version, detail-json)
HISTORY_ROWS = [
    (MV_PREV, "vrm", "11500.00", "2026-04-01", "2026-05-01", "0.2.0", '{"coverage": "0.97"}'),
    (MV_CUR, "vrm", "16400.00", "2026-05-01", "2026-06-01", "0.2.0", '{"coverage": "0.90"}'),
]


class FakeCursor:
    def __init__(self, conn: "FakeAnomalyConnection"):
        self._conn = conn
        self._rows: list[tuple] = []

    def execute(self, sql: str, params=()):
        self._conn.executed.append((sql, tuple(params) if not isinstance(params, tuple) else params))
        if "FROM computed.metric_values" in sql and "ORDER BY" in sql:
            self._rows = list(self._conn.history_rows)
        elif sql.startswith("SELECT 1"):
            record_id = params[-1]
            known = {row[0] for row in self._conn.history_rows}
            self._rows = [(1,)] if record_id in known else []
        elif "INSERT INTO dq.issues" in sql:
            issue_id = f"issue-{len(self._conn.inserted_issues) + 1:04d}"
            self._conn.inserted_issues.append(tuple(params))
            self._rows = [(issue_id,)]
        else:
            raise AssertionError(f"fake connection got unexpected SQL: {sql!r}")

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class FakeAnomalyConnection:
    def __init__(self, history_rows=HISTORY_ROWS):
        self.history_rows = list(history_rows)
        self.inserted_issues: list[tuple] = []
        self.executed: list[tuple] = []
        self.commit_count = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commit_count += 1


class FabricatingProvider:
    name = "fabricator"
    version = "1.0-test"

    def generate(self, prompt: str, context: Mapping[str, str]) -> LabeledOutput:
        return LabeledOutput(
            text="Fabricated: the swing was 99999 units.",
            provider_name=self.name,
            provider_version=self.version,
        )


class TestLoadMetricHistory:
    def test_loads_and_normalizes(self):
        conn = FakeAnomalyConnection()
        history = load_metric_history(conn)
        assert [r.metric_value_id for r in history] == [MV_PREV, MV_CUR]
        assert history[0].value == "11500.00"
        assert history[0].detail == {"coverage": "0.97"}
        # Values stay strings end to end — never floats.
        assert isinstance(history[0].value, str)


class TestRunAnomalyScan:
    def test_inserts_expected_dq_rows_and_commits(self):
        conn = FakeAnomalyConnection()
        report = run_anomaly_scan(conn)
        # 11500.00 -> 16400.00 is a swing (delta 4900 > 0.25*11500=2875);
        # coverage 0.97 -> 0.90 is a drop of 0.07 > 0.05.
        assert report.findings_detected == 2
        assert len(conn.inserted_issues) == 2
        assert conn.commit_count == 1

        by_type = {params[0]: params for params in conn.inserted_issues}
        assert set(by_type) == {ISSUE_TYPE_SWING, ISSUE_TYPE_COVERAGE_DROP}
        for issue_type, params in by_type.items():
            _, severity, status, title, description, source_record_ids = params
            assert severity in ("info", "warning")  # a flag NEVER blocks
            assert status == "open"
            assert title
            assert source_record_ids == []  # empty per contract
            # metric_value_ids cited in the description instead.
            assert MV_PREV in description and MV_CUR in description

    def test_grounded_explanation_is_appended_and_labeled(self):
        conn = FakeAnomalyConnection()
        report = run_anomaly_scan(conn)
        assert report.explanations_grounded == 2
        assert report.explanations_rejected == 0
        for params in conn.inserted_issues:
            description = params[4]
            assert "AI-generated explanation" in description
            assert "requires human review" in description
        assert all(issue.explanation_grounded for issue in report.issues_inserted)

    def test_fabricating_provider_finding_survives_without_explanation(self, caplog):
        conn = FakeAnomalyConnection()
        report = run_anomaly_scan(conn, provider=FabricatingProvider())
        # Flags never depend on prose: both rows still inserted...
        assert len(conn.inserted_issues) == 2
        assert report.explanations_grounded == 0
        assert report.explanations_rejected == 2
        assert set(report.rejected_issue_types) == {
            ISSUE_TYPE_SWING,
            ISSUE_TYPE_COVERAGE_DROP,
        }
        # ...but the fabricated prose appears NOWHERE.
        for params in conn.inserted_issues:
            description = params[4]
            assert "99999" not in description
            assert "AI-generated explanation" not in description
        assert not any(issue.explanation_grounded for issue in report.issues_inserted)

    def test_no_findings_inserts_nothing(self):
        quiet = [
            (MV_PREV, "vrm", "100.00", "2026-04-01", "2026-05-01", "0.2.0", '{"coverage": "0.97"}'),
            (MV_CUR, "vrm", "101.00", "2026-05-01", "2026-06-01", "0.2.0", '{"coverage": "0.97"}'),
        ]
        conn = FakeAnomalyConnection(quiet)
        report = run_anomaly_scan(conn)
        assert report.findings_detected == 0
        assert conn.inserted_issues == []
        assert report.issues_inserted == ()

    def test_report_is_frozen_and_json_safe(self):
        conn = FakeAnomalyConnection()
        report = run_anomaly_scan(conn)
        with pytest.raises(AttributeError):
            report.findings_detected = 99  # frozen dataclass
        parsed = json.loads(report.to_json())
        assert parsed["swing_threshold"] == "0.25"
        assert parsed["coverage_drop_threshold"] == "0.05"
        assert "engineering defaults" in parsed["threshold_provenance"]
        assert parsed["issues_inserted_count"] == 2
        assert parsed["provider_name"] == "stub"

    def test_thresholds_are_explicit_inputs_recorded_in_report(self):
        conn = FakeAnomalyConnection()
        report = run_anomaly_scan(
            conn,
            swing_threshold=Decimal("0.50"),
            coverage_drop_threshold=Decimal("0.30"),
        )
        assert report.swing_threshold == Decimal("0.50")
        assert report.coverage_drop_threshold == Decimal("0.30")
        # 4900/11500 < 0.50 and 0.07 < 0.30: nothing flags at these settings.
        assert report.findings_detected == 0

    def test_scan_is_deterministic(self):
        first = run_anomaly_scan(FakeAnomalyConnection())
        second = run_anomaly_scan(FakeAnomalyConnection())
        assert first == second  # frozen dataclasses, byte-identical scan

    def test_runner_never_writes_metric_values(self):
        conn = FakeAnomalyConnection()
        run_anomaly_scan(conn)
        writes = [sql for sql, _ in conn.executed if "INSERT" in sql or "UPDATE" in sql]
        assert writes and all("dq.issues" in sql for sql in writes)


class TestCli:
    def test_refuses_without_pg_env(self, monkeypatch):
        for var in ("PGHOST", "PGDATABASE", "PGSERVICE"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(SystemExit, match="Refusing to guess"):
            main([])

    def test_rejects_missing_threshold_value(self):
        # argparse exits before any env or driver code runs.
        with pytest.raises(SystemExit):
            main(["--swing-threshold"])
