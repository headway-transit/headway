"""Tests for the view-DDL generator (handoff 0037, design point 6).

Two layers:
  - golden files: the committed sample pack under ../sample is regenerated
    into a temp dir and compared byte-for-byte, so any change to the
    generated SQL/click-path is a deliberate, reviewed change;
  - rule tests: the binding rules (explicit columns, never SELECT *,
    CONVERT baked in for declared datetime formats, least-privilege
    grants, loud refusals instead of guessed formats) are asserted
    directly, so they hold for future adapters too.

Run from tools/view-ddl:  python3 -m pytest -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = TOOL_DIR.parents[1]
SPEC = REPO_DIR / "adapters" / "tripspark" / "streets" / "mapping.v0.yaml"
SAMPLE = TOOL_DIR / "sample"

sys.path.insert(0, str(TOOL_DIR))
import generate  # noqa: E402

PACK_FILES = [
    "01-create-view.sql",
    "02-create-login-and-grant.sql",
    "03-verify-view.sql",
    "SSMS-CLICK-PATH.md",
]

TRIPSPARK_COLUMNS = [
    "VehicleLocationAPCKey", "VehicleName", "TotalCount", "BoardCount",
    "AlightCount", "UnmodifiedAlightCount", "APCSource", "IsTripper",
    "IsDetour", "TripName", "RouteName", "RouteShortName", "PatternName",
    "StopName", "StopCode", "PatternPointRank", "DirectionKey",
    "EventDateISO",
]


def run_tool(out: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL_DIR / "generate.py"), str(SPEC),
         "--out", str(out), *extra],
        capture_output=True, text=True,
    )


def test_golden_sample_pack_matches_regeneration(tmp_path):
    result = run_tool(tmp_path)
    assert result.returncode == 0, result.stderr
    for name in PACK_FILES:
        got = (tmp_path / name).read_text(encoding="utf-8")
        want = (SAMPLE / name).read_text(encoding="utf-8")
        assert got == want, (
            f"{name} drifted from the committed sample. If the change is "
            "deliberate, regenerate the pack:\n  python3 "
            "tools/view-ddl/generate.py "
            "adapters/tripspark/streets/mapping.v0.yaml "
            "--out tools/view-ddl/sample"
        )


def test_view_lists_every_column_explicitly_in_order(tmp_path):
    run_tool(tmp_path)
    view = (tmp_path / "01-create-view.sql").read_text(encoding="utf-8")
    positions = []
    for col in TRIPSPARK_COLUMNS:
        marker = f"AS [{col}]"
        assert marker in view, f"column {col} missing from the view"
        positions.append(view.index(marker))
    assert positions == sorted(positions), "columns out of adapter order"


def test_never_select_star_anywhere(tmp_path):
    run_tool(tmp_path)
    for name in PACK_FILES:
        if name.endswith(".sql"):
            sql = (tmp_path / name).read_text(encoding="utf-8")
            executable = "\n".join(
                ln for ln in sql.splitlines()
                if not ln.strip().startswith("--")
            )
            assert "SELECT *" not in executable
            assert "*" not in executable.replace("COUNT_BIG(*)", "")


def test_datetime_column_gets_exact_convert(tmp_path):
    run_tool(tmp_path)
    view = (tmp_path / "01-create-view.sql").read_text(encoding="utf-8")
    # EventDateISO is declared "%Y-%m-%dT%H:%M:%S" -> varchar(19), style 126.
    assert ("CONVERT(varchar(19), src.[FILL_IN_EventDateISO], 126) "
            "AS [EventDateISO]") in view


def test_grants_are_least_privilege(tmp_path):
    run_tool(tmp_path)
    sql = (tmp_path / "02-create-login-and-grant.sql").read_text("utf-8")
    grants = [ln for ln in sql.splitlines() if ln.strip().startswith("GRANT")]
    assert grants == [
        "GRANT SELECT ON [dbo].[vw_headway_apc] TO [headway_ro];"
    ], "exactly one grant: SELECT on the view, nothing else"
    for forbidden in ("db_owner", "db_datareader", "sysadmin", "ALTER",
                      "INSERT", "UPDATE", "DELETE", "CONTROL"):
        assert forbidden not in sql
    assert "PASTE_A_NEW_STRONG_PASSWORD_HERE" in sql  # placeholder, no real secret
    assert "CHECK_POLICY = ON" in sql


def test_click_path_is_for_the_zero_sql_reader(tmp_path):
    run_tool(tmp_path)
    doc = (tmp_path / "SSMS-CLICK-PATH.md").read_text(encoding="utf-8")
    for required in (
        "Commands completed successfully",   # the expected-output anchor
        "Connect to Server",                 # the SSMS click-path
        "F5",                                # how to execute
        "Never email a password",            # secret handling
        "do not open the CSV in Excel",      # the Excel-mangling warning
        "strips leading zeros",
        "The view is the contract",
    ):
        assert required in doc, f"click-path doc missing: {required!r}"


def test_unknown_datetime_format_is_refused_not_guessed(tmp_path):
    spec = tmp_path / "weird.yaml"
    spec.write_text(
        "source_label: acme_weird\n"
        "source_format:\n  csv:\n    columns: [K, When]\n"
        "fields:\n  event_timestamp:\n"
        "    from: When\n    coerce: datetime\n"
        "    format: \"%d/%m/%Y %H:%M\"\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(TOOL_DIR / "generate.py"), str(spec),
         "--out", str(tmp_path / "out")],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "no exact SQL Server CONVERT" in (result.stdout + result.stderr)
    assert not (tmp_path / "out" / "01-create-view.sql").exists()


def test_datetime_without_declared_format_is_refused(tmp_path):
    spec = tmp_path / "nofmt.yaml"
    spec.write_text(
        "source_label: acme_nofmt\n"
        "source_format:\n  csv:\n    columns: [K, When]\n"
        "fields:\n  event_timestamp:\n"
        "    from: When\n    coerce: datetime\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(TOOL_DIR / "generate.py"), str(spec),
         "--out", str(tmp_path / "out")],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "without declaring a format" in (result.stdout + result.stderr)


def test_cursor_column_must_be_in_contract(tmp_path):
    result = run_tool(tmp_path, "--cursor-column", "NoSuchColumn")
    assert result.returncode != 0
    assert "not one of the adapter's declared columns" in (
        result.stdout + result.stderr
    )


def test_default_cursor_is_first_declared_column(tmp_path):
    run_tool(tmp_path)
    verify = (tmp_path / "03-verify-view.sql").read_text(encoding="utf-8")
    assert "ORDER BY [VehicleLocationAPCKey] DESC" in verify


@pytest.mark.parametrize("bad", ["a.b.c.d", ""])
def test_bad_view_name_refused(tmp_path, bad):
    result = run_tool(tmp_path, "--view-name", bad)
    assert result.returncode != 0
