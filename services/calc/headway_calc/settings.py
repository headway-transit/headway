"""Injectable reader for app.settings — the audited per-agency policy knobs.

Closes the loop opened by migration 0014 / handoff 0002's Response: agencies
set calc policy through the audited settings API (``PUT /settings/{key}``),
and the runner reads the same rows here so a threshold set through the API
governs the next run. This module is stdlib-only and deterministic (no env,
no driver, no clock): it takes any DB-API connection, exactly like
headway_calc.reader.

The four policy knobs (seeded by migration 0014, never client-creatable):
``coverage_threshold`` (decimal), ``gap_threshold_seconds`` (integer),
``layover_max_seconds`` (integer), ``missing_trip_threshold`` (decimal).
``imbalance_threshold`` is deliberately NOT a settings knob — it is not
seeded in app.settings.

Parsing rules (the same discipline as the write side): decimal values are
parsed with ``Decimal(str)`` — floating point NEVER touches a policy number —
and integer values with ``int``. Failure is LOUD and typed:

- table exists but a knob row is missing            -> MissingSettingError
- a row's value or value_type cannot be trusted     -> InvalidSettingValueError

There are no silent code-default fallbacks once the table exists: a broken
settings table means the agency's stated policy is unknowable, and a guessed
threshold could certify a figure the agency never approved.

The ONE tolerated absence is the table itself (relation ``app.settings`` does
not exist — a pre-migration-0014 database): ``load_policy_settings`` returns
``None`` after rolling back the failed statement and logging a WARNING, and
the caller proceeds on the calc library's code defaults. That path is
detected strictly by PostgreSQL's undefined-table condition (SQLSTATE 42P01,
duck-typed off the driver exception so this module stays driver-free); any
other database error propagates unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

#: PostgreSQL condition ``undefined_table`` ("relation ... does not exist").
_UNDEFINED_TABLE_SQLSTATE = "42P01"

#: The four seeded calc policy knobs (migration 0014) and the value_type each
#: row must carry — the contract between the settings surface and this reader.
POLICY_SETTING_TYPES: dict[str, str] = {
    "coverage_threshold": "decimal",
    "gap_threshold_seconds": "integer",
    "layover_max_seconds": "integer",
    "missing_trip_threshold": "decimal",
}

_SELECT_POLICY_SETTINGS_SQL = (
    "SELECT setting_key, setting_value, value_type FROM app.settings "
    "WHERE setting_key IN (%s, %s, %s, %s) "
    "ORDER BY setting_key"
)


class SettingsError(Exception):
    """A policy setting cannot be trusted — the run must refuse, never guess."""


class MissingSettingError(SettingsError):
    """app.settings exists but one or more seeded policy knobs are absent."""


class InvalidSettingValueError(SettingsError):
    """A policy setting row exists but its value/value_type is unusable."""


@dataclass(frozen=True)
class PolicySettings:
    """The four agency policy knobs as read from app.settings — immutable.

    Decimals stay Decimal (parsed from the TEXT value, never through float);
    the two ``*_seconds`` knobs are ints per their seeded value_type.
    """

    coverage_threshold: Decimal
    gap_threshold_seconds: int
    layover_max_seconds: int
    missing_trip_threshold: Decimal


def _is_undefined_table(exc: BaseException) -> bool:
    """Duck-typed SQLSTATE 42P01 check — driver-free (stdlib purity).

    psycopg3 exceptions expose ``sqlstate`` (and ``diag.sqlstate``); psycopg2
    exposes ``pgcode``. The class-name check covers drivers that subclass a
    generated ``UndefinedTable`` without exposing the code as an attribute.
    """
    candidates = (
        getattr(exc, "sqlstate", None),
        getattr(exc, "pgcode", None),
        getattr(getattr(exc, "diag", None), "sqlstate", None),
    )
    if _UNDEFINED_TABLE_SQLSTATE in candidates:
        return True
    return type(exc).__name__ == "UndefinedTable"


def _parse(key: str, raw_value: str, value_type: str) -> Decimal | int:
    """Parse one row's TEXT value per its value_type — loud, typed failure."""
    expected_type = POLICY_SETTING_TYPES[key]
    if value_type != expected_type:
        raise InvalidSettingValueError(
            f"app.settings row {key!r} declares value_type {value_type!r} but "
            f"this policy knob is seeded as {expected_type!r} (migration "
            f"0014). Refusing to run on a policy value of the wrong type — "
            f"fix the row; the runner never guesses a threshold."
        )
    if value_type == "decimal":
        try:
            value = Decimal(raw_value)
        except InvalidOperation:
            value = None
        if value is None or not value.is_finite():
            raise InvalidSettingValueError(
                f"app.settings row {key!r} holds {raw_value!r}, which is not "
                f"a finite decimal. Refusing to run on an unparseable policy "
                f"value — fix the row via the settings API; the runner never "
                f"guesses a threshold."
            )
        return value
    try:
        return int(raw_value)
    except ValueError:
        raise InvalidSettingValueError(
            f"app.settings row {key!r} holds {raw_value!r}, which is not an "
            f"integer. Refusing to run on an unparseable policy value — fix "
            f"the row via the settings API; the runner never guesses a "
            f"threshold."
        ) from None


def load_policy_settings(conn) -> PolicySettings | None:
    """Read the four calc policy knobs from app.settings.

    Returns a frozen PolicySettings when the table exists and every knob
    parses; raises MissingSettingError / InvalidSettingValueError (both
    SettingsError) when the table exists but cannot be trusted — the caller
    must refuse the run, NEVER substitute a code default for a broken row.

    Returns None — the one tolerated absence — when relation app.settings
    does not exist (a pre-migration-0014 database), after rolling back the
    failed statement and logging a WARNING that the run proceeds on the calc
    library's code defaults.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            _SELECT_POLICY_SETTINGS_SQL, tuple(sorted(POLICY_SETTING_TYPES))
        )
        rows = cur.fetchall()
    except Exception as exc:
        if not _is_undefined_table(exc):
            raise
        # The failed statement aborts an open transaction on a real driver;
        # roll it back so the caller's reads/writes can proceed.
        conn.rollback()
        logger.warning(
            "app.settings does not exist (pre-migration-0014 database): "
            "this run is governed by the calc library's CODE DEFAULTS for "
            "any threshold not given explicitly. Apply migration 0014 to "
            "give the agency an audited settings surface."
        )
        return None

    by_key = {row[0]: row for row in rows}
    missing = sorted(POLICY_SETTING_TYPES.keys() - by_key.keys())
    if missing:
        raise MissingSettingError(
            f"app.settings exists but is missing the policy knob(s) "
            f"{', '.join(missing)}. These rows are seeded by migration 0014 "
            f"and are never optional once the table exists — the runner "
            f"refuses rather than silently substituting code defaults for "
            f"an agency's audited policy. Restore the row(s) (re-run the "
            f"0014 seed) and re-run."
        )

    parsed = {
        key: _parse(key, str(row[1]), row[2]) for key, row in by_key.items()
    }
    return PolicySettings(
        coverage_threshold=parsed["coverage_threshold"],
        gap_threshold_seconds=parsed["gap_threshold_seconds"],
        layover_max_seconds=parsed["layover_max_seconds"],
        missing_trip_threshold=parsed["missing_trip_threshold"],
    )
