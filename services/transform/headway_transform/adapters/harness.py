"""Validation harness core for vendor adapters (handoff 0015, design point 3).

Proves, for one mapping spec + its committed fixtures:

1. the spec is machine-valid (contracts/adapter-mapping.v0.schema.json +
   semantic checks) and has at least one sample fixture (registration bar);
2. every mapped record passes the TARGET CONTRACT's validation (the engine
   refuses to emit a nonconforming record, and the harness re-checks the
   arithmetic: canonical rows == contract records == mapped count);
3. every fixture row is accounted for: mapped, filtered (with the declared
   filter's reason), or explicitly quarantined with a reason — and the counts
   match the fixture's committed ``<fixture>.expected.json`` exactly, so an
   accidental behavior change in mapping or quarantine is a red build, not a
   silent drift;
4. deterministic round-trip: two runs over the same bytes produce identical
   records, canonical rows, lineage edges, findings, and counts (the property
   that makes Kafka redelivery idempotent under the migration-0023 keys).

The CLI wrapper is ``adapters/validate`` at the repo root (CI runs it over
every registered adapter). Exit is nonzero on ANY failure.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .engine import AdapterRunResult, run_adapter
from .registry import FIXTURES_DIRNAME, AdapterRegistry, RegistryError, fixture_files
from .spec import SpecError, load_spec

EXPECTED_SUFFIX = ".expected.json"
_EXPECTED_KEYS = ("total_rows", "mapped", "quarantined", "filtered")


@dataclass
class HarnessReport:
    """Outcome of validating one adapter (or a whole adapters directory)."""

    ok: bool = True
    lines: list[str] = field(default_factory=list)

    def note(self, line: str) -> None:
        self.lines.append(line)

    def fail(self, line: str) -> None:
        self.ok = False
        self.lines.append(f"FAIL {line}")


def _fingerprint(result: AdapterRunResult) -> str:
    """Stable digest of everything a run produced (determinism check)."""
    payload = repr(
        (
            result.records,
            [repr(r) for r in result.passenger_events],
            [repr(r) for r in result.dr_trips],
            [
                (e.output_kind, e.output_id, e.transform_name,
                 e.transform_version, e.input_kind, e.input_id)
                for e in result.edges
            ],
            [
                (f.issue_type, f.severity, f.title, f.description,
                 tuple(f.source_record_ids))
                for f in result.findings
            ],
            (result.total_rows, result.mapped_count,
             result.quarantined_count, result.filtered_count,
             result.file_refused),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_adapter(spec_path: Path, report: HarnessReport) -> None:
    """Run the full harness for one mapping spec; append to the report."""
    try:
        spec = load_spec(spec_path)
    except SpecError as exc:
        report.fail(f"{spec_path}: {exc}")
        return
    report.note(
        f"spec {spec.vendor}/{spec.product} -> {spec.target_contract} "
        f"(source_label {spec.source_label}, spec {spec.spec_sha12}): "
        "schema + semantic checks OK"
    )

    fixtures = fixture_files(spec_path)
    if not fixtures:
        report.fail(
            f"{spec_path}: no sample fixtures under "
            f"{spec_path.parent / FIXTURES_DIRNAME}/ — a spec without a "
            "verified sample fixture cannot be registered"
        )
        return

    for fixture in fixtures:
        _validate_fixture(spec_path, spec, fixture, report)


def _validate_fixture(spec_path, spec, fixture: Path, report: HarnessReport) -> None:
    failures_before = sum(1 for line in report.lines if line.startswith("FAIL"))
    expected_path = fixture.with_name(fixture.name + EXPECTED_SUFFIX)
    if not expected_path.is_file():
        report.fail(
            f"{fixture}: missing {expected_path.name} — every fixture "
            "commits its expected row accounting (total_rows/mapped/"
            "quarantined/filtered) so mapping drift is a red build"
        )
        return
    try:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        report.fail(f"{expected_path}: not valid JSON: {exc}")
        return
    missing_keys = [k for k in _EXPECTED_KEYS if k not in expected]
    if missing_keys:
        report.fail(f"{expected_path}: missing key(s) {', '.join(missing_keys)}")
        return

    file_bytes = fixture.read_bytes()
    record_id = hashlib.sha256(file_bytes).hexdigest()
    result = run_adapter(spec, file_bytes, record_id, spec.source_label)
    rerun = run_adapter(spec, file_bytes, record_id, spec.source_label)

    prefix = f"{fixture.name}"

    # 3) full accounting: every row mapped / filtered / quarantined.
    if not result.file_refused and not result.accounted():
        report.fail(
            f"{prefix}: row accounting broken — total {result.total_rows} != "
            f"mapped {result.mapped_count} + filtered {result.filtered_count} "
            f"+ quarantined {result.quarantined_count}"
        )
    quarantine_findings = [
        f for f in result.findings if f.issue_type == "adapter_row_quarantined"
    ]
    if len(quarantine_findings) != result.quarantined_count:
        report.fail(
            f"{prefix}: {result.quarantined_count} quarantined row(s) but "
            f"{len(quarantine_findings)} quarantine finding(s) — every "
            "quarantine must carry a reasoned finding"
        )
    unreasoned = [f for f in quarantine_findings if not f.description.strip()]
    if unreasoned:
        report.fail(f"{prefix}: {len(unreasoned)} quarantine finding(s) lack a reason")

    # 2) every mapped record passed contract validation (engine refuses
    #    otherwise); re-check the arithmetic end to end.
    canonical = len(result.passenger_events) + len(result.dr_trips)
    if not (len(result.records) == result.mapped_count == canonical):
        report.fail(
            f"{prefix}: mapped-record arithmetic broken — records "
            f"{len(result.records)}, mapped {result.mapped_count}, "
            f"canonical rows {canonical}"
        )
    # two lineage edges per canonical row: normalizer edge + adapter edge.
    if len(result.edges) != 2 * canonical:
        report.fail(
            f"{prefix}: expected {2 * canonical} lineage edges "
            f"(normalizer + adapter per row), got {len(result.edges)}"
        )

    # committed expectations.
    actual = {
        "total_rows": result.total_rows,
        "mapped": result.mapped_count,
        "quarantined": result.quarantined_count,
        "filtered": result.filtered_count,
    }
    if bool(expected.get("file_refused", False)) != result.file_refused:
        report.fail(
            f"{prefix}: file_refused expected "
            f"{bool(expected.get('file_refused', False))}, got {result.file_refused}"
        )
    mismatches = [
        f"{k} expected {expected[k]}, got {actual[k]}"
        for k in _EXPECTED_KEYS
        if expected[k] != actual[k]
    ]
    if mismatches:
        report.fail(f"{prefix}: expected counts mismatch — " + "; ".join(mismatches))

    # 4) deterministic round-trip.
    if _fingerprint(result) != _fingerprint(rerun):
        report.fail(f"{prefix}: two runs over the same bytes differ — nondeterministic")

    failures_after = sum(1 for line in report.lines if line.startswith("FAIL"))
    if failures_after == failures_before:
        report.note(
            f"  fixture {prefix}: rows {result.total_rows} = "
            f"mapped {result.mapped_count} + filtered {result.filtered_count} "
            f"+ quarantined {result.quarantined_count}"
            + (" [file refused]" if result.file_refused else "")
            + f"; canonical {canonical}, edges {len(result.edges)}, "
            f"deterministic OK"
        )


def validate_all(adapters_dir: Path) -> HarnessReport:
    """Validate every registered adapter under adapters_dir."""
    report = HarnessReport()
    try:
        registry = AdapterRegistry.load(adapters_dir)
    except RegistryError as exc:
        report.fail(str(exc))
        return report
    report.note(
        f"registry: {len(registry)} adapter(s) registered "
        f"({', '.join(registry.labels())})"
    )
    for label in registry.labels():
        spec = registry.lookup(label)
        assert spec is not None
        validate_adapter(Path(spec.path), report)
    return report
