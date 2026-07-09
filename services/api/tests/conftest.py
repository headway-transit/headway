"""Test fixtures: the app wired to a FAKE database connection.

No Docker/Postgres is available in this environment, so the psycopg3
connection is replaced by ``FakeConn`` — an object with the same
``execute()`` / ``transaction()`` shape the app uses, dispatching on the
exact SQL the app issues and keeping state in dicts. Transactions snapshot
state on entry and restore it if the block raises, so tests can assert that
a refused certification really left nothing behind.

Live verification against real PostgreSQL is PENDING (see README).
"""

from __future__ import annotations

import copy
import datetime as dt
import sys
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from headway_api import auth  # noqa: E402
from headway_api.app import Settings, create_app  # noqa: E402

TEST_SECRET = "test-only-session-secret-not-for-production"

# bcrypt is deliberately slow; hash each test password once per session.
_PASSWORDS = {
    "vera": "viewer-pass-1",
    "stella": "steward-pass-1",
    "petra": "preparer-pass-1",
    "cora": "certifier-pass-1",
    "dora": "disabled-pass-1",
}
_HASHES = {u: auth.hash_password(p) for u, p in _PASSWORDS.items()}

UTC = dt.timezone.utc


class FakeCursor:
    def __init__(self, rows, rowcount=None):
        self._rows = list(rows)
        self.rowcount = rowcount if rowcount is not None else len(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    """Just enough of a psycopg3 connection for headway_api's queries."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.metric_values: dict[str, dict] = {}
        self.dq_issues: dict[str, dict] = {}
        self.lineage_edges: list[dict] = []
        self.certifications: list[dict] = []
        self.audit_events: list[dict] = []
        self._next_event_id = 1
        self.executed: list[tuple[str, tuple]] = []
        self.tx_log: list[str] = []

    # -- transaction with honest rollback ---------------------------------
    @contextmanager
    def transaction(self):
        snapshot = copy.deepcopy(
            (
                self.users,
                self.metric_values,
                self.dq_issues,
                self.certifications,
                self.audit_events,
                self._next_event_id,
            )
        )
        try:
            yield
        except BaseException:
            (
                self.users,
                self.metric_values,
                self.dq_issues,
                self.certifications,
                self.audit_events,
                self._next_event_id,
            ) = snapshot
            self.tx_log.append("rollback")
            raise
        self.tx_log.append("commit")

    # -- SQL dispatch ------------------------------------------------------
    def execute(self, sql, params=None):
        q = " ".join(sql.split())
        params = params or ()
        self.executed.append((q, params))

        if "FROM auth.users WHERE username" in q:
            u = self.users.get(params[0])
            rows = (
                [(u["user_id"], u["username"], u["password_hash"], u["role"], u["disabled"])]
                if u
                else []
            )
            return FakeCursor(rows)

        if q.startswith("SELECT metric_value_id, metric, unit"):
            rows = list(self.metric_values.values())
            i = 0
            if "metric = %s" in q:
                rows = [r for r in rows if r["metric"] == params[i]]
                i += 1
            if "period_start >= %s" in q:
                rows = [r for r in rows if r["period_start"] >= params[i]]
                i += 1
            if "period_end <= %s" in q:
                rows = [r for r in rows if r["period_end"] <= params[i]]
                i += 1
            rows.sort(key=lambda r: (r["period_start"], r["metric"]))
            return FakeCursor(
                [
                    (
                        r["metric_value_id"], r["metric"], r["unit"],
                        r["period_start"], r["period_end"], r["scope"],
                        r["value"], r["calc_name"], r["calc_version"],
                        r["computed_at"], r["certification_status"],
                    )
                    for r in rows
                ]
            )

        if "WITH RECURSIVE walk" in q:
            return FakeCursor(self._walk_lineage(params[0]))

        if q.startswith("SELECT metric_value_id FROM computed.metric_values"):
            mv = self.metric_values.get(str(params[0]))
            return FakeCursor([(mv["metric_value_id"],)] if mv else [])

        if "SELECT metric_value_id, certification_status" in q and "ANY(" in q:
            wanted = [str(i) for i in params[0]]
            rows = [
                (mv["metric_value_id"], mv["certification_status"])
                for i, mv in self.metric_values.items()
                if i in wanted
            ]
            return FakeCursor(rows)

        if "count(*) FROM dq.issues" in q:
            n = sum(
                1
                for i in self.dq_issues.values()
                if i["severity"] == "blocking" and i["status"] != "resolved"
            )
            return FakeCursor([(n,)])

        if q.startswith("INSERT INTO cert.certifications"):
            ids, certified_by, attestation = params
            cert = {
                "certification_id": str(uuid.uuid4()),
                "metric_value_ids": list(ids),
                "certified_by": certified_by,
                "certified_at": dt.datetime.now(UTC),
                "attestation": attestation,
            }
            self.certifications.append(cert)
            return FakeCursor([(cert["certification_id"], cert["certified_at"])])

        if q.startswith("UPDATE computed.metric_values SET certification_status"):
            wanted = [str(i) for i in params[0]]
            n = 0
            for i in wanted:
                if i in self.metric_values:
                    self.metric_values[i]["certification_status"] = "certified"
                    n += 1
            return FakeCursor([], rowcount=n)

        if q.startswith("INSERT INTO audit.events"):
            actor, action, subject_kind, subject_id, detail = params
            event = {
                "event_id": self._next_event_id,
                "at": dt.datetime.now(UTC),
                "actor": actor,
                "action": action,
                "subject_kind": subject_kind,
                "subject_id": subject_id,
                "detail": detail,
            }
            self._next_event_id += 1
            self.audit_events.append(event)
            return FakeCursor([(event["event_id"],)])

        if q.startswith("SELECT issue_id, issue_type"):
            rows = list(self.dq_issues.values())
            if "WHERE status = %s" in q:
                rows = [r for r in rows if r["status"] == params[0]]
            rows.sort(key=lambda r: r["created_at"])
            return FakeCursor(
                [
                    (
                        r["issue_id"], r["issue_type"], r["severity"], r["status"],
                        r["owner"], r["title"], r["description"],
                        r["source_record_ids"], r["created_at"],
                        r["resolved_at"], r["resolution"],
                    )
                    for r in rows
                ]
            )

        if q.startswith("UPDATE dq.issues SET status = 'resolved'"):
            resolution, issue_id = params
            issue = self.dq_issues.get(str(issue_id))
            if issue is None or issue["status"] == "resolved":
                return FakeCursor([])
            issue["status"] = "resolved"
            issue["resolved_at"] = dt.datetime.now(UTC)
            issue["resolution"] = resolution
            return FakeCursor([(issue["issue_id"], issue["resolved_at"])])

        if q.startswith("SELECT status FROM dq.issues"):
            issue = self.dq_issues.get(str(params[0]))
            return FakeCursor([(issue["status"],)] if issue else [])

        raise AssertionError(f"FakeConn has no handler for SQL: {q!r}")

    def _walk_lineage(self, root_id):
        rows = []
        frontier = [("computed.metric_values", str(root_id))]
        seen = set()
        while frontier:
            kind, node_id = frontier.pop(0)
            if (kind, node_id) in seen:
                continue
            seen.add((kind, node_id))
            for e in self.lineage_edges:
                if e["output_kind"] == kind and e["output_id"] == node_id:
                    rows.append(
                        (
                            e["output_kind"], e["output_id"],
                            e["transform_name"], e["transform_version"],
                            e["input_kind"], e["input_id"],
                        )
                    )
                    frontier.append((e["input_kind"], e["input_id"]))
        return rows

    # -- seeding helpers ----------------------------------------------------
    def add_user(self, username, role, *, disabled=False, password_hash=None):
        self.users[username] = {
            "user_id": str(uuid.uuid4()),
            "username": username,
            "password_hash": password_hash or _HASHES[username],
            "role": role,
            "disabled": disabled,
        }

    def add_metric_value(self, **overrides):
        mv = {
            "metric_value_id": str(uuid.uuid4()),
            "metric": "vrm",
            "unit": "miles",
            "period_start": dt.date(2026, 6, 1),
            "period_end": dt.date(2026, 6, 30),
            "scope": "agency",
            "value": Decimal("1234.567"),
            "calc_name": "vrm_v0",
            "calc_version": "0.1.0",
            "computed_at": dt.datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
            "certification_status": "uncertified",
        }
        mv.update(overrides)
        self.metric_values[mv["metric_value_id"]] = mv
        return mv

    def add_dq_issue(self, **overrides):
        issue = {
            "issue_id": str(uuid.uuid4()),
            "issue_type": "gap",
            "severity": "warning",
            "status": "open",
            "owner": None,
            "title": "AVL feed gap on 2026-06-14",
            "description": "No vehicle positions received between 02:00 and 03:00.",
            "source_record_ids": None,
            "created_at": dt.datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
            "resolved_at": None,
            "resolution": None,
        }
        issue.update(overrides)
        self.dq_issues[issue["issue_id"]] = issue
        return issue

    def add_edge(self, output_kind, output_id, transform_name, transform_version,
                 input_kind, input_id):
        self.lineage_edges.append(
            {
                "output_kind": output_kind,
                "output_id": str(output_id),
                "transform_name": transform_name,
                "transform_version": transform_version,
                "input_kind": input_kind,
                "input_id": str(input_id),
            }
        )


@pytest.fixture
def fake_db():
    db = FakeConn()
    db.add_user("vera", "viewer")
    db.add_user("stella", "data_steward")
    db.add_user("petra", "report_preparer")
    db.add_user("cora", "certifying_official")
    db.add_user("dora", "viewer", disabled=True)
    return db


@pytest.fixture
def settings():
    return Settings(session_secret=TEST_SECRET, token_ttl_seconds=600)


@pytest.fixture
def app(fake_db, settings):
    return create_app(settings=settings, db=fake_db)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def token_for(db: FakeConn, username: str, *, ttl_seconds: int = 600) -> str:
    u = db.users[username]
    return auth.issue_token(
        secret=TEST_SECRET,
        sub=u["user_id"],
        username=username,
        role=u["role"],
        ttl_seconds=ttl_seconds,
    )


def auth_header(db: FakeConn, username: str, **kwargs) -> dict:
    return {"Authorization": f"Bearer {token_for(db, username, **kwargs)}"}
