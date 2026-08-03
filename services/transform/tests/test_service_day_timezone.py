"""Where the service-day timezone comes from — ADR-0015's worked example.

The failure this closes: on 2026-08-03 a partner agency's telematics feed
refused every page for three days. The variable the normalizer reads was
documented in this service's README and plumbed nowhere, so there was no path
an operator could take. Their ITS manager is an expert in his data and not a
systems administrator.

What is asserted here is the ORDER and the ABSENCES, because those are where
a two-home setting goes wrong: the environment wins so scripted installs keep
working, the database answers so a person can fix their own installation, and
nothing at all still means nothing — never UTC, never the server's zone.
"""

from __future__ import annotations

import pytest

from headway_transform.service_day_timezone import (
    ENV_VAR,
    SETTING_KEY,
    resolve_service_day_timezone,
)


class FakeConn:
    """Just enough of a psycopg connection: one settings row, or a failure."""

    def __init__(self, value=None, *, present=True, raises=False):
        self.value = value
        self.present = present
        self.raises = raises
        self.asked = []

    def execute(self, sql, params):
        if self.raises:
            raise RuntimeError("settings table unreachable")
        self.asked.append((sql, params))
        rows = [(self.value,)] if self.present else []

        class _Cur:
            def fetchone(self_inner):
                return rows[0] if rows else None

        return _Cur()


@pytest.fixture(autouse=True)
def _no_ambient_env(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)


def test_the_environment_wins(monkeypatch):
    """A scripted fleet install must be able to set this without a human
    clicking anything — the same posture as HEADWAY_ACCESS_MODE for
    install.sh --yes."""
    monkeypatch.setenv(ENV_VAR, "America/Denver")
    conn = FakeConn("America/Los_Angeles")

    value, source = resolve_service_day_timezone(conn)

    assert value == "America/Denver"
    assert ENV_VAR in source
    # And it does not even ask the database — the precedence is decided before
    # the query, not after it.
    assert conn.asked == []


def test_otherwise_the_database_decides():
    """So an operator can fix their own installation from the admin screen,
    and the change is attributed — app.settings records updated_by and
    updated_at, which a .env edit over SSH never did."""
    conn = FakeConn("America/Los_Angeles")

    value, source = resolve_service_day_timezone(conn)

    assert value == "America/Los_Angeles"
    assert "Settings" in source
    assert conn.asked[0][1] == (SETTING_KEY,)


@pytest.mark.parametrize(
    "conn,why",
    [
        (FakeConn(""), "the setting exists but is blank"),
        (FakeConn("   "), "the setting is whitespace"),
        (FakeConn(None), "the setting is NULL"),
        (FakeConn(present=False), "there is no settings row (pre-0044)"),
        (FakeConn(raises=True), "the settings table is unreachable"),
    ],
)
def test_undeclared_stays_undeclared(conn, why):
    """NO FALLBACK. Not UTC, not the server's zone, not anything.

    A guessed zone silently dates a federal figure to the wrong day, which is
    the exact failure the normalizer's refusal exists to prevent. An
    installation that has not declared its zone is not misconfigured — it is
    undeclared, and Headway says so.
    """
    value, source = resolve_service_day_timezone(conn)
    assert value == "", why
    assert source == "nothing", why


def test_an_unreadable_settings_table_is_not_fatal():
    """A transform that refused to start because it could not read an OPTIONAL
    setting would take down every other feed over one that may not even be
    configured. Degrade, do not die."""
    value, source = resolve_service_day_timezone(FakeConn(raises=True))
    assert (value, source) == ("", "nothing")


def test_the_environment_still_wins_when_the_database_is_unreachable(monkeypatch):
    """The automation path must not depend on the database being healthy."""
    monkeypatch.setenv(ENV_VAR, "America/Chicago")
    value, source = resolve_service_day_timezone(FakeConn(raises=True))
    assert value == "America/Chicago"
    assert ENV_VAR in source


def test_the_source_is_always_reported():
    """Two homes for one setting is a support burden unless the running
    service can say which one it read."""
    for conn, expected in (
        (FakeConn("America/New_York"), "Settings"),
        (FakeConn(present=False), "nothing"),
    ):
        _, source = resolve_service_day_timezone(conn)
        assert expected in source
