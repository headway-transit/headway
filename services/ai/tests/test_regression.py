"""The four shipped fixture verdicts + the gate's own failure behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from headway_ai.regression import DEFAULT_FIXTURES_DIR, load_fixture, main, run_fixture

FIXTURES = sorted(DEFAULT_FIXTURES_DIR.glob("*.json"))


def fixture_by_name(name: str) -> dict:
    for path in FIXTURES:
        fixture = load_fixture(path)
        if fixture["name"] == name:
            return fixture
    raise AssertionError(f"missing fixture {name!r}")


class TestShippedFixtureVerdicts:
    def test_all_four_required_fixtures_ship(self):
        names = {load_fixture(path)["name"] for path in FIXTURES}
        assert {
            "grounded_draft_passes",
            "dangling_citation_fails",
            "fabricated_number_fails",
            "wrong_record_kind_fails",
        } <= names

    def test_grounded_draft_passes(self):
        report = run_fixture(fixture_by_name("grounded_draft_passes"))
        assert report.passed is True
        assert report.citation_resolution_rate == "1.0000"
        assert report.fabricated_number_count == 0

    def test_dangling_citation_fails(self):
        report = run_fixture(fixture_by_name("dangling_citation_fails"))
        assert report.passed is False
        assert report.citation_resolution_rate == "0.0000"
        assert report.fabricated_number_count == 0

    def test_fabricated_number_fails(self):
        report = run_fixture(fixture_by_name("fabricated_number_fails"))
        assert report.passed is False
        assert report.citation_resolution_rate == "1.0000"  # citation is real...
        assert report.fabricated_number_count == 1  # ...the number is not

    def test_wrong_record_kind_fails(self):
        # Subtle case: correct number, real id, wrong cited kind.
        report = run_fixture(fixture_by_name("wrong_record_kind_fails"))
        assert report.passed is False
        assert report.citation_resolution_rate == "0.5000"
        assert report.fabricated_number_count == 0


class TestGateBehavior:
    def test_gate_exits_zero_on_shipped_fixtures(self, capsys):
        assert main([str(DEFAULT_FIXTURES_DIR)]) == 0
        out = capsys.readouterr().out
        assert "grounding regression gate: PASS" in out

    def test_gate_exits_nonzero_on_verdict_mismatch(self, tmp_path: Path, capsys):
        fixture = fixture_by_name("grounded_draft_passes")
        fixture["expected"]["passed"] = False  # deliberately wrong expectation
        (tmp_path / "tampered.json").write_text(json.dumps(fixture), encoding="utf-8")
        assert main([str(tmp_path)]) == 1
        assert "FAIL" in capsys.readouterr().out

    def test_gate_exits_nonzero_on_empty_fixture_dir(self, tmp_path: Path):
        assert main([str(tmp_path)]) == 1

    def test_gate_exits_nonzero_on_broken_fixture(self, tmp_path: Path, capsys):
        (tmp_path / "broken.json").write_text("{\"name\": \"x\"}", encoding="utf-8")
        assert main([str(tmp_path)]) == 1
        assert "error running fixture" in capsys.readouterr().out

    def test_gate_detects_regression_in_fabrication_count(self, tmp_path: Path):
        fixture = fixture_by_name("fabricated_number_fails")
        fixture["expected"]["fabricated_number_count"] = 0
        (tmp_path / "regressed.json").write_text(json.dumps(fixture), encoding="utf-8")
        assert main([str(tmp_path)]) == 1


class TestFixtureConnectionIsReadOnly:
    def test_no_write_surface(self):
        from headway_ai.regression import FixtureConnection

        conn = FixtureConnection({"raw.records": ["a"]})
        assert not hasattr(conn, "commit")
        assert not hasattr(conn, "execute")
        cursor = conn.cursor()
        with pytest.raises(ValueError):
            cursor.execute("INSERT INTO raw.records VALUES (%s)", ("a",))
