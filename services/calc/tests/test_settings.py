"""Unit tests for headway_calc.settings.load_policy_settings — the audited
app.settings read path (migration 0014) that closes handoff 0002's
runner-reads-settings loop.

Covers: the seeded rows parse into a frozen PolicySettings (Decimal via str,
never float; ints for the seconds knobs); a missing table (relation does not
exist, SQLSTATE 42P01) is the ONE tolerated absence — None + rollback + a
WARNING log; a missing knob row or an unparseable/wrong-typed value raises a
typed SettingsError (the run must refuse, never guess); any other database
error propagates unchanged. No live database — RecordingConnection only.
"""

from __future__ import annotations

import dataclasses
import logging
from decimal import Decimal

import pytest
from conftest import SEEDED_SETTINGS_ROWS, RecordingConnection

from headway_calc.settings import (
    InvalidSettingValueError,
    MissingSettingError,
    PolicySettings,
    SettingsError,
    load_policy_settings,
)


def _rows(**overrides: tuple[str, str]) -> list[tuple]:
    """The seeded rows with (value, value_type) overridden per key."""
    return [
        (key, *overrides.get(key, (value, value_type)))
        for key, value, value_type in SEEDED_SETTINGS_ROWS
    ]


# --- happy path --------------------------------------------------------------


def test_seeded_rows_parse_into_frozen_policy_settings():
    conn = RecordingConnection()  # serves the migration-0014 seed rows
    settings = load_policy_settings(conn)

    assert settings == PolicySettings(
        coverage_threshold=Decimal("0.95"),
        gap_threshold_seconds=300,
        layover_max_seconds=1800,
        missing_trip_threshold=Decimal("0.02"),
    )
    # Decimal via str, NEVER float — and the seconds knobs are ints.
    assert isinstance(settings.coverage_threshold, Decimal)
    assert isinstance(settings.missing_trip_threshold, Decimal)
    assert isinstance(settings.gap_threshold_seconds, int)
    assert isinstance(settings.layover_max_seconds, int)
    assert dataclasses.is_dataclass(settings)
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.coverage_threshold = Decimal("0")  # type: ignore[misc]

    # One SELECT against app.settings; nothing written, nothing committed.
    assert len(conn.statements_matching("app.settings")) == 1
    assert conn.commits == [] and conn.rollback_count == 0


def test_agency_set_values_are_read_exactly():
    conn = RecordingConnection(
        settings_rows=_rows(
            coverage_threshold=("0.90", "decimal"),
            gap_threshold_seconds=("600", "integer"),
        )
    )
    settings = load_policy_settings(conn)
    assert settings.coverage_threshold == Decimal("0.90")
    assert settings.gap_threshold_seconds == 600
    assert settings.layover_max_seconds == 1800
    assert settings.missing_trip_threshold == Decimal("0.02")


# --- missing table: the ONE tolerated absence --------------------------------


def test_missing_table_returns_none_rolls_back_and_warns(caplog):
    conn = RecordingConnection(settings_table_missing=True)
    with caplog.at_level(logging.WARNING, logger="headway_calc.settings"):
        assert load_policy_settings(conn) is None

    # The failed statement aborted the (fake) transaction: rolled back so
    # the caller's subsequent reads/writes can proceed.
    assert conn.rollback_count == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "app.settings does not exist" in warnings[0].getMessage()
    assert "CODE DEFAULTS" in warnings[0].getMessage()
    assert "migration 0014" in warnings[0].getMessage()


def test_other_database_errors_propagate_unchanged():
    class ExplodingConnection:
        def cursor(self):
            return self

        def execute(self, sql, params=None):
            raise RuntimeError("connection dropped mid-statement")

        def rollback(self):  # pragma: no cover — must not be reached
            raise AssertionError("must not swallow a non-42P01 error")

    with pytest.raises(RuntimeError, match="connection dropped"):
        load_policy_settings(ExplodingConnection())


# --- table exists but cannot be trusted: LOUD typed refusal ------------------


def test_missing_knob_row_raises_typed_error_naming_the_keys():
    rows = [r for r in SEEDED_SETTINGS_ROWS if r[0] != "coverage_threshold"]
    with pytest.raises(MissingSettingError) as excinfo:
        load_policy_settings(RecordingConnection(settings_rows=rows))
    message = str(excinfo.value)
    assert "coverage_threshold" in message
    assert "migration 0014" in message
    assert "refuses" in message
    assert isinstance(excinfo.value, SettingsError)


def test_all_knob_rows_missing_names_every_key():
    with pytest.raises(MissingSettingError) as excinfo:
        load_policy_settings(RecordingConnection(settings_rows=[]))
    message = str(excinfo.value)
    # The NTD loader names exactly ITS knob set — the ops knobs (migration
    # 0024) are a separate loader by design and never gate an NTD run.
    from headway_calc.settings import POLICY_SETTING_TYPES

    for key in POLICY_SETTING_TYPES:
        assert key in message
    assert "otp_early_tolerance_seconds" not in message


def test_ops_loader_reads_only_ops_knobs():
    from headway_calc.settings import load_ops_policy_settings

    settings = load_ops_policy_settings(RecordingConnection())
    assert settings is not None
    assert settings.otp_early_tolerance_seconds == 60
    assert settings.otp_late_tolerance_seconds == 300


def test_ops_loader_missing_knob_refuses_never_guesses():
    from headway_calc.settings import load_ops_policy_settings

    # A table holding only the NTD knobs (a post-0014, pre-0024 database
    # where migrations were half-applied) must refuse the ops run.
    ntd_only = [r for r in SEEDED_SETTINGS_ROWS if not r[0].startswith("otp_")]
    with pytest.raises(MissingSettingError) as excinfo:
        load_ops_policy_settings(RecordingConnection(settings_rows=ntd_only))
    assert "otp_early_tolerance_seconds" in str(excinfo.value)
    assert "migration 0024" in str(excinfo.value)


def test_ops_loader_tolerates_missing_table_with_warning(caplog):
    from headway_calc.settings import load_ops_policy_settings

    with caplog.at_level(logging.WARNING, logger="headway_calc.settings"):
        result = load_ops_policy_settings(
            RecordingConnection(settings_table_missing=True)
        )
    assert result is None
    assert any("CODE DEFAULTS" in r.message for r in caplog.records)


def test_ops_loader_unparseable_value_refuses():
    from headway_calc.settings import load_ops_policy_settings

    rows = [
        ("otp_early_tolerance_seconds", "sixty", "integer"),
        ("otp_late_tolerance_seconds", "300", "integer"),
    ]
    with pytest.raises(InvalidSettingValueError):
        load_ops_policy_settings(RecordingConnection(settings_rows=rows))


@pytest.mark.parametrize("bad_value", ["not-a-number", "", "NaN", "Infinity"])
def test_unparseable_decimal_raises_typed_error(bad_value):
    conn = RecordingConnection(
        settings_rows=_rows(coverage_threshold=(bad_value, "decimal"))
    )
    with pytest.raises(InvalidSettingValueError) as excinfo:
        load_policy_settings(conn)
    message = str(excinfo.value)
    assert "coverage_threshold" in message
    assert repr(bad_value) in message
    assert "never guesses" in message


@pytest.mark.parametrize("bad_value", ["12.5", "", "ten", "1e3"])
def test_unparseable_integer_raises_typed_error(bad_value):
    conn = RecordingConnection(
        settings_rows=_rows(gap_threshold_seconds=(bad_value, "integer"))
    )
    with pytest.raises(InvalidSettingValueError) as excinfo:
        load_policy_settings(conn)
    assert "gap_threshold_seconds" in str(excinfo.value)


def test_wrong_value_type_raises_typed_error():
    """A decimal knob whose row claims value_type 'text' is a contract
    violation, not something to parse anyway."""
    conn = RecordingConnection(
        settings_rows=_rows(missing_trip_threshold=("0.02", "text"))
    )
    with pytest.raises(InvalidSettingValueError) as excinfo:
        load_policy_settings(conn)
    message = str(excinfo.value)
    assert "missing_trip_threshold" in message
    assert "'text'" in message and "'decimal'" in message
