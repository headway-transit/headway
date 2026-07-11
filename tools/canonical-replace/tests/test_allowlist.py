"""Allowlist behavior: only known canonical tables; protected data refused
with a plain-language explanation, and nothing ever hits the database."""

from __future__ import annotations

import pytest

import replace
from conftest import FakeConnection


def _run(conn, table, out):
    return replace.run(
        conn,
        table=table,
        where="service_date = %s",
        params=["2026-07-09"],
        execute=True,
        out=out,
    )


def test_raw_records_refused_with_immutability_explanation():
    conn = FakeConnection()
    messages: list[str] = []
    code = _run(conn, "raw.records", messages.append)

    assert code == 2
    text = "\n".join(messages)
    assert "REFUSED" in text
    assert "raw.records" in text
    assert "immutable" in text
    assert "never touches it" in text
    assert conn.executed == []  # nothing hit the database
    assert conn.commits == 0


def test_audit_events_refused():
    conn = FakeConnection()
    messages: list[str] = []
    code = _run(conn, "audit.events", messages.append)

    assert code == 2
    text = "\n".join(messages)
    assert "append-only" in text
    assert conn.executed == []


def test_computed_refused_with_superseded_explanation():
    conn = FakeConnection()
    messages: list[str] = []
    code = _run(conn, "computed.metric_values", messages.append)

    assert code == 2
    text = "\n".join(messages)
    assert "REFUSED" in text
    assert "superseded" in text
    assert "new calc run" in text
    assert "never deleted" in text
    assert conn.executed == []


def test_cert_and_dq_refused():
    for table in ("cert.certifications", "dq.issues"):
        conn = FakeConnection()
        messages: list[str] = []
        assert _run(conn, table, messages.append) == 2
        assert "REFUSED" in "\n".join(messages)
        assert conn.executed == []


def test_unknown_table_refused_naming_the_allowlist():
    conn = FakeConnection()
    messages: list[str] = []
    code = _run(conn, "canonical.stop_times", messages.append)

    assert code == 2
    text = "\n".join(messages)
    assert "not a replaceable table" in text
    for allowed in replace.ALLOWLIST:
        assert allowed in text
    assert conn.executed == []


@pytest.mark.parametrize("table", sorted(replace.ALLOWLIST))
def test_allowlisted_tables_are_accepted(table):
    conn = FakeConnection()  # no matching rows
    messages: list[str] = []
    code = _run(conn, table, messages.append)

    assert code == 0
    assert "Nothing to do" in "\n".join(messages)
    # Exactly the key-column SELECT ran; no writes for an empty match.
    assert len(conn.executed) == 1
    assert conn.executed[0][0].lstrip().upper().startswith("SELECT")


def test_allowlist_output_kinds_match_table_names():
    # Handoff 0001: output_kind is the canonical table name.
    for table, spec in replace.ALLOWLIST.items():
        assert spec.output_kind == table
