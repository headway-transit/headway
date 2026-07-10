"""The CI grounding regression gate: ``python3 -m headway_ai.regression``.

Loads every eval fixture from ``services/ai/eval_fixtures/`` (or a
directory passed as argv[1]), builds a fake DB-API connection from each
fixture's record universe (NO live database is ever touched), runs the
grounding harness, and compares the verdict against the fixture's
expected values. Any mismatch — or an empty fixture directory — exits
nonzero, failing the build. A grounding regression is a build failure,
not a warning.

Fixture JSON shape::

    {
      "name": "...", "description": "...",
      "universe": {"raw.records": ["<id>", ...], ...},
      "allowed_numbers": ["12794.92", ...],
      "record_count_whitelist": [],
      "draft": {
        "provider_name": "stub", "provider_version": "0.1.0",
        "claims": [{"text": "...", "cited_record_kind": "...",
                    "cited_record_id": "...", "numeric_values": ["..."]}]
      },
      "expected": {"passed": true,
                   "citation_resolution_rate": "1.0000",
                   "fabricated_number_count": 0}
    }
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence

from headway_ai.claims import Claim, GroundedDraft
from headway_ai.grounding import EvalReport, evaluate

__all__ = ["FixtureConnection", "load_fixture", "run_fixture", "main"]

DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "eval_fixtures"

_FROM_TABLE_RE = re.compile(r"\bFROM\s+([A-Za-z_][\w.]*)", re.IGNORECASE)


class _FixtureCursor:
    """DB-API-shaped cursor answering existence SELECTs from a fixture universe."""

    def __init__(self, universe: Mapping[str, frozenset[str]]) -> None:
        self._universe = universe
        self._row: tuple[int, ...] | None = None

    def execute(self, sql: str, params: Sequence[str] = ()) -> None:
        match = _FROM_TABLE_RE.search(sql)
        if match is None:
            raise ValueError(f"fixture connection cannot interpret query: {sql!r}")
        table = match.group(1)
        if table == "lineage.edges" and len(params) == 2:
            # lineage-node resolution: params are (output_kind, output_id)
            kind, record_id = params
        elif len(params) == 1:
            kind, record_id = table, params[0]
        else:
            raise ValueError(f"unexpected parameter shape for {table!r}: {params!r}")
        exists = record_id in self._universe.get(kind, frozenset())
        self._row = (1,) if exists else None

    def fetchone(self) -> tuple[int, ...] | None:
        return self._row

    def close(self) -> None:
        self._row = None


class FixtureConnection:
    """Read-only fake DB-API connection over a fixture record universe.

    Used by the regression gate and unit tests so the harness's SQL is
    exercised without any live database (and can never write to one).
    """

    def __init__(self, universe: Mapping[str, Sequence[str]]) -> None:
        self._universe = {kind: frozenset(ids) for kind, ids in universe.items()}

    def cursor(self) -> _FixtureCursor:
        return _FixtureCursor(self._universe)


def load_fixture(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        fixture = json.load(handle)
    for key in ("name", "universe", "allowed_numbers", "draft", "expected"):
        if key not in fixture:
            raise ValueError(f"{path.name}: fixture missing required key {key!r}")
    return fixture


def run_fixture(fixture: dict) -> EvalReport:
    draft_spec = fixture["draft"]
    draft = GroundedDraft(
        claims=tuple(
            Claim(
                text=claim["text"],
                cited_record_kind=claim["cited_record_kind"],
                cited_record_id=claim["cited_record_id"],
                numeric_values=tuple(claim.get("numeric_values", ())),
            )
            for claim in draft_spec["claims"]
        ),
        provider_name=draft_spec["provider_name"],
        provider_version=draft_spec["provider_version"],
    )
    conn = FixtureConnection(fixture["universe"])
    return evaluate(
        conn,
        draft,
        fixture["allowed_numbers"],
        record_count_whitelist=fixture.get("record_count_whitelist", ()),
    )


def _verdict_mismatches(expected: Mapping, report: EvalReport) -> list[str]:
    mismatches: list[str] = []
    checks = {
        "passed": report.passed,
        "citation_resolution_rate": report.citation_resolution_rate,
        "fabricated_number_count": report.fabricated_number_count,
    }
    for key, actual in checks.items():
        if key in expected and expected[key] != actual:
            mismatches.append(f"{key}: expected {expected[key]!r}, got {actual!r}")
    if "passed" not in expected:
        mismatches.append("fixture 'expected' block must include 'passed'")
    return mismatches


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    fixtures_dir = Path(args[0]) if args else DEFAULT_FIXTURES_DIR
    fixture_paths = sorted(fixtures_dir.glob("*.json"))
    if not fixture_paths:
        print(f"grounding regression gate: FAIL — no fixtures found in {fixtures_dir}")
        return 1

    failures = 0
    for path in fixture_paths:
        try:
            fixture = load_fixture(path)
            report = run_fixture(fixture)
            mismatches = _verdict_mismatches(fixture["expected"], report)
        except Exception as exc:  # a broken fixture is a gate failure, not a skip
            print(f"FAIL {path.name}: error running fixture: {exc}")
            failures += 1
            continue
        detail = (
            f"passed={report.passed} rate={report.citation_resolution_rate} "
            f"fabricated={report.fabricated_number_count}"
        )
        if mismatches:
            failures += 1
            print(f"FAIL {fixture['name']} ({path.name}): {detail}")
            for mismatch in mismatches:
                print(f"     {mismatch}")
        else:
            print(f"ok   {fixture['name']} ({path.name}): {detail} — matches expected verdict")

    total = len(fixture_paths)
    if failures:
        print(f"grounding regression gate: FAIL — {failures}/{total} fixture(s) mismatched")
        return 1
    print(f"grounding regression gate: PASS — {total}/{total} fixture verdicts matched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
