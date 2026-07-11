"""Core replacement behavior against the fake connection: dry-run makes no
writes, execution deletes edges then rows then writes the dq.issues info row
in one transaction, batching works, and the edgeless guard refuses unless
overridden."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import replace
from conftest import FakeConnection

TABLE = "canonical.passenger_events"
KIND = "canonical.passenger_events"
WHERE = "service_date = %s"
PARAMS = ["2026-07-09"]

TS = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
RID = "cd" * 32


def _rows_and_edges(n: int):
    spec = replace.ALLOWLIST[TABLE]
    rows = [(f"pe-{i:04d}", TS, RID) for i in range(n)]
    edges = [(KIND, spec.build_output_id(*row)) for row in rows]
    return rows, edges


def _run(conn, *, execute=False, allow_edgeless=False, batch_size=1000, out=None):
    messages: list[str] = []
    code = replace.run(
        conn,
        table=TABLE,
        where=WHERE,
        params=PARAMS,
        execute=execute,
        allow_edgeless=allow_edgeless,
        batch_size=batch_size,
        out=(out if out is not None else messages.append),
    )
    return code, messages


def test_dry_run_is_default_and_writes_nothing():
    rows, edges = _rows_and_edges(3)
    conn = FakeConnection(canonical_rows=rows, edges=edges)

    code, messages = _run(conn)  # execute defaults to False

    assert code == 0
    text = "\n".join(messages)
    assert "DRY RUN" in text
    assert "rows matching: 3" in text
    assert "output_ids: 3" in text  # edge count line
    # Only reads hit the database: the key SELECT + edge count SELECT.
    assert all(
        sql.lstrip().upper().startswith("SELECT") for sql, _ in conn.executed
    )
    assert conn.commits == 0
    assert conn.dq_rows == []
    assert len(conn.edges) == 3  # nothing deleted


def test_execute_deletes_edges_then_rows_then_dq_in_one_commit():
    rows, edges = _rows_and_edges(3)
    conn = FakeConnection(canonical_rows=rows, edges=edges)

    code, messages = _run(conn, execute=True)

    assert code == 0
    statements = [sql for sql, _ in conn.executed]
    edge_deletes = [
        i for i, s in enumerate(statements) if s.startswith("DELETE FROM lineage.edges")
    ]
    row_deletes = [
        i for i, s in enumerate(statements) if s.startswith(f"DELETE FROM {TABLE}")
    ]
    dq_inserts = [
        i for i, s in enumerate(statements) if "INSERT INTO dq.issues" in s
    ]
    assert edge_deletes and row_deletes and dq_inserts
    # Transactional order: every edge delete precedes the row delete, which
    # precedes the dq provenance insert; exactly one commit, no rollbacks.
    assert max(edge_deletes) < row_deletes[0] < dq_inserts[0]
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert conn.edges == [] and conn.canonical_rows == []

    text = "\n".join(messages)
    assert "deleted 3 lineage edge(s)" in text
    assert f"deleted 3 row(s) from {TABLE}" in text


def test_row_delete_reuses_where_and_params():
    rows, edges = _rows_and_edges(1)
    conn = FakeConnection(canonical_rows=rows, edges=edges)

    _run(conn, execute=True)

    (sql, params) = conn.sql_like(f"delete from {TABLE}")[0]
    assert WHERE in sql
    assert params == PARAMS


def test_edge_deletes_are_batched():
    rows, edges = _rows_and_edges(5)
    conn = FakeConnection(canonical_rows=rows, edges=edges)

    code, _ = _run(conn, execute=True, batch_size=2)

    assert code == 0
    edge_deletes = conn.sql_like("delete from lineage.edges")
    assert len(edge_deletes) == 3  # 2 + 2 + 1
    assert [len(params[1]) for _, params in edge_deletes] == [2, 2, 1]
    # Every delete targets the output_kind + an output_id list.
    for _, params in edge_deletes:
        assert params[0] == KIND
    assert conn.edges == []


def test_duplicate_edges_for_one_output_id_are_all_deleted():
    # A re-normalized route/trip has several edges sharing one output_id;
    # deleting by (output_kind, output_id) must remove them all.
    rows, edges = _rows_and_edges(1)
    conn = FakeConnection(canonical_rows=rows, edges=edges * 3)

    code, messages = _run(conn, execute=True)

    assert code == 0
    assert conn.edges == []
    assert "deleted 3 lineage edge(s)" in "\n".join(messages)


def test_edgeless_refusal_deletes_nothing():
    rows, _ = _rows_and_edges(2)
    conn = FakeConnection(canonical_rows=rows, edges=[])  # zero edges exist

    code, messages = _run(conn, execute=True)

    assert code == 2
    text = "\n".join(messages)
    assert "WARNING" in text
    assert "FORMAT DRIFT" in text
    assert "REFUSED" in text
    assert "--allow-edgeless" in text
    assert conn.sql_like("delete from") == []
    assert conn.commits == 0
    assert conn.dq_rows == []
    assert conn.canonical_rows == rows  # untouched


def test_edgeless_override_proceeds_with_loud_warning():
    rows, _ = _rows_and_edges(2)
    conn = FakeConnection(canonical_rows=rows, edges=[])

    code, messages = _run(conn, execute=True, allow_edgeless=True)

    assert code == 0
    text = "\n".join(messages)
    assert "FORMAT DRIFT" in text
    assert "proceeding WITHOUT lineage edges" in text
    assert conn.commits == 1
    assert conn.canonical_rows == []
    assert len(conn.dq_rows) == 1
    assert "--allow-edgeless was given" in conn.dq_rows[0][3]


def test_dry_run_warns_about_edgeless_but_exits_zero():
    rows, _ = _rows_and_edges(2)
    conn = FakeConnection(canonical_rows=rows, edges=[])

    code, messages = _run(conn, execute=False)

    assert code == 0
    text = "\n".join(messages)
    assert "FORMAT DRIFT" in text
    assert "DRY RUN" in text
    assert conn.commits == 0


def test_dq_info_row_documents_the_replacement():
    rows, edges = _rows_and_edges(2)
    conn = FakeConnection(canonical_rows=rows, edges=edges)

    code, _ = _run(conn, execute=True)

    assert code == 0
    assert len(conn.dq_rows) == 1
    issue_type, severity, title, description, source_record_ids = conn.dq_rows[0]
    assert issue_type == "canonical_replacement"
    assert severity == "info"
    assert TABLE in title
    # what / why-param / counts:
    assert TABLE in description
    assert WHERE in description
    assert "2026-07-09" in description
    assert "2 row(s)" in description
    assert "2 lineage.edges row(s)" in description
    # provenance anchors to the doomed rows' source records:
    assert source_record_ids == [RID]


def test_no_matching_rows_is_a_clean_noop():
    conn = FakeConnection(canonical_rows=[], edges=[])

    code, messages = _run(conn, execute=True)

    assert code == 0
    assert "Nothing to do" in "\n".join(messages)
    assert conn.sql_like("delete from") == []
    assert conn.commits == 0
    assert conn.dq_rows == []


def test_failure_mid_transaction_rolls_back():
    rows, edges = _rows_and_edges(2)
    conn = FakeConnection(
        canonical_rows=rows,
        edges=edges,
        fail_on_sql_containing=f"DELETE FROM {TABLE}",
    )

    with pytest.raises(RuntimeError, match="injected failure"):
        _run(conn, execute=True)

    assert conn.commits == 0
    assert conn.rollbacks == 1
    assert conn.dq_rows == []


def test_cli_dry_run_and_yes_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        replace.parse_args(
            ["--table", TABLE, "--where", WHERE, "--dry-run", "--yes"]
        )


def test_cli_defaults_to_dry_run():
    args = replace.parse_args(
        ["--table", TABLE, "--where", WHERE, "--param", "2026-07-09"]
    )
    assert args.yes is False
    assert args.param == ["2026-07-09"]
