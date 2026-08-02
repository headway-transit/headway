"""The OIDC login state is SINGLE USE — proved against a real engine.

Migration 0043 lists replay as one of four defences on the callback, and
delegates it entirely to the database::

    UPDATE auth.oidc_login_states SET consumed_at = now()
     WHERE state = %s AND consumed_at IS NULL AND expires_at > now()
    RETURNING nonce, code_verifier, browser_binding, redirect_uri

The comment on that constant says "two concurrent callbacks replaying one
state cannot both match ``consumed_at IS NULL``, so exactly one wins and the
other is refused". That claim is about READ COMMITTED row locking and
re-evaluation, which is a property of PostgreSQL — not of the API, and not of
anything a test double can model. The unit suite's fake connection returns
whatever it is told to; it would pass just as happily against an
implementation with a read-then-write race in it. Handoff 0046 left this open,
and the 2026-08-02 external review confirmed it could not test it either.

So it is tested here, where there is a real engine, the way the claim is
written: two connections, genuinely overlapping, one state.

The SQL is IMPORTED from the router, never re-typed. A copy in a test proves
the copy works.
"""

from __future__ import annotations

import datetime as dt
import os
import secrets
import threading

import pytest

# tests/integration is not a package (no __init__.py); pytest puts this
# directory on sys.path, so the sibling conftest imports as a plain module.
from conftest import ADMIN_URL_ENV, SKIP_REASON

pytestmark = pytest.mark.skipif(
    not os.environ.get(ADMIN_URL_ENV, "").strip(), reason=SKIP_REASON
)

UTC = dt.timezone.utc

#: Long enough that a blocked connection is unambiguously blocked rather than
#: merely slow. The assertion it supports can only produce a FALSE PASS if the
#: engine is slow, never a false failure, so a generous value is the safe one.
BLOCKED_FOR_SECONDS = 1.0

#: Ceiling on waiting for the loser once the winner has committed. If the
#: lock is never released this fails the test instead of hanging CI.
RELEASE_TIMEOUT_SECONDS = 30.0


def _login_state_sql():
    """The production statements, imported rather than restated."""
    from headway_api.routers.oidc import (
        _CONSUME_LOGIN_STATE,
        _INSERT_LOGIN_STATE,
        _SWEEP_LOGIN_STATES,
    )

    return _INSERT_LOGIN_STATE, _CONSUME_LOGIN_STATE, _SWEEP_LOGIN_STATES


def _seed_state(observer, *, expires_in_minutes: float) -> tuple[str, tuple]:
    """One in-flight authorization request, seeded outside the app."""
    insert_sql, _, _ = _login_state_sql()
    state = secrets.token_urlsafe(32)
    values = (
        state,
        secrets.token_urlsafe(16),                    # nonce
        secrets.token_urlsafe(32),                    # code_verifier (PKCE)
        secrets.token_hex(32),                        # browser_binding (sha256 hex)
        "https://headway.integration.test/auth/oidc/callback",
        dt.datetime.now(UTC) + dt.timedelta(minutes=expires_in_minutes),
    )
    observer.execute(insert_sql, values)
    return state, values


def test_two_concurrent_callbacks_replaying_one_state_cannot_both_win(
    migrated_db, observer
):
    """The race migration 0043 says cannot happen, actually raced.

    Connection A consumes the state inside an OPEN transaction and holds the
    row lock. Connection B — a genuinely separate backend, the way a second
    HTTP worker would be — issues the identical UPDATE and must block on that
    lock rather than read a stale ``consumed_at IS NULL``. When A commits, B
    re-evaluates its WHERE against the new row version and matches nothing.

    A read-then-write implementation would let both callbacks through here,
    and a test double cannot tell the difference.
    """
    import psycopg

    _, consume_sql, _ = _login_state_sql()
    state, seeded = _seed_state(observer, expires_in_minutes=10)

    winner = psycopg.connect(migrated_db, autocommit=False)
    loser_row: dict = {}
    loser_failure: dict = {}
    about_to_replay = threading.Event()

    def replay():
        conn = psycopg.connect(migrated_db, autocommit=True)
        try:
            about_to_replay.set()
            loser_row["row"] = conn.execute(consume_sql, (state,)).fetchone()
        except Exception as exc:  # surfaced as a failure, never swallowed
            loser_failure["error"] = exc
        finally:
            conn.close()

    thread = threading.Thread(target=replay, name="replayed-callback")
    try:
        won = winner.execute(consume_sql, (state,)).fetchone()
        # A wins: it gets back exactly what the callback needs to finish.
        assert won is not None
        nonce, code_verifier, browser_binding, redirect_uri = won
        assert (nonce, code_verifier, browser_binding, redirect_uri) == seeded[1:5]

        thread.start()
        assert about_to_replay.wait(timeout=10.0), "replay thread never started"
        thread.join(timeout=BLOCKED_FOR_SECONDS)
        # THE POINT: B is stuck on A's row lock. If it had returned by now it
        # either won a second time or read around the uncommitted write.
        assert thread.is_alive(), (
            "the replayed UPDATE did not block on the winner's row lock — "
            "single-use is not being enforced by the database"
        )

        winner.commit()
        thread.join(timeout=RELEASE_TIMEOUT_SECONDS)
        assert not thread.is_alive(), "the row lock was never released"
    finally:
        winner.close()
        thread.join(timeout=RELEASE_TIMEOUT_SECONDS)

    assert "error" not in loser_failure, loser_failure.get("error")
    # B is refused. Not an error, not a partial result — nothing to work with,
    # which is what makes the callback return the same generic refusal a
    # forged state gets.
    assert loser_row["row"] is None

    consumed = observer.execute(
        "SELECT consumed_at FROM auth.oidc_login_states WHERE state = %s",
        (state,),
    ).fetchone()
    assert consumed[0] is not None


def test_an_expired_state_is_refused_by_the_same_statement(observer):
    """``expires_at > now()`` is part of the same conditional UPDATE, so an
    expired state is refused without a second round trip and without Python
    comparing clocks. now() is the DATABASE's clock — the one clock every
    worker shares."""
    _, consume_sql, _ = _login_state_sql()
    state, _ = _seed_state(observer, expires_in_minutes=-1)

    assert observer.execute(consume_sql, (state,)).fetchone() is None
    # Refused, and NOT marked consumed: it was never used.
    row = observer.execute(
        "SELECT consumed_at FROM auth.oidc_login_states WHERE state = %s",
        (state,),
    ).fetchone()
    assert row[0] is None


def test_the_sweep_removes_expired_states_and_leaves_live_ones(observer):
    """Migration 0043: "Rows expire and are swept on each start; the table
    stays small by construction." The sweep must not take a live sign-in with
    it — that would log out a user mid-redirect."""
    _, _, sweep_sql = _login_state_sql()
    expired, _ = _seed_state(observer, expires_in_minutes=-5)
    live, _ = _seed_state(observer, expires_in_minutes=5)

    observer.execute(sweep_sql)

    remaining = {
        r[0]
        for r in observer.execute(
            "SELECT state FROM auth.oidc_login_states WHERE state = ANY(%s)",
            ([expired, live],),
        ).fetchall()
    }
    assert remaining == {live}
