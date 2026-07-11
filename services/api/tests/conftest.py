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

from headway_api import auth, machine_auth  # noqa: E402
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
        self.api_keys: dict[str, dict] = {}
        self.webhook_subscriptions: dict[str, dict] = {}
        self.settings: dict[str, dict] = {}
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
                self.api_keys,
                self.webhook_subscriptions,
                self.settings,
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
                self.api_keys,
                self.webhook_subscriptions,
                self.settings,
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
            if "WHERE certification_status = 'certified'" in q:
                # The public open-data query: certified figures only, no params.
                rows = [r for r in rows if r["certification_status"] == "certified"]
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
                        r["detail"],
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
                        r["resolution_minutes"],
                    )
                    for r in rows
                ]
            )

        if q.startswith("UPDATE dq.issues SET status = 'resolved'"):
            resolution, resolution_minutes, issue_id = params
            issue = self.dq_issues.get(str(issue_id))
            if issue is None or issue["status"] == "resolved":
                return FakeCursor([])
            issue["status"] = "resolved"
            issue["resolved_at"] = dt.datetime.now(UTC)
            issue["resolution"] = resolution
            issue["resolution_minutes"] = resolution_minutes
            return FakeCursor(
                [
                    (
                        issue["issue_id"], issue["issue_type"],
                        issue["severity"], issue["resolved_at"],
                    )
                ]
            )

        if q.startswith("SELECT status FROM dq.issues"):
            issue = self.dq_issues.get(str(params[0]))
            return FakeCursor([(issue["status"],)] if issue else [])

        if q.startswith("SELECT resolution_minutes FROM dq.issues"):
            issue = self.dq_issues.get(str(params[0]))
            return FakeCursor(
                [(issue["resolution_minutes"],)] if issue else []
            )

        # -- machine API keys (handoff 0006) --------------------------------
        if "FROM auth.api_keys WHERE key_hash" in q:
            rows = [
                (
                    k["key_id"], k["name"], k["key_prefix"], k["scopes"],
                    k["source_label"], k["revoked_at"],
                )
                for k in self.api_keys.values()
                if k["key_hash"] == params[0]
            ]
            return FakeCursor(rows)

        if q.startswith("INSERT INTO auth.api_keys"):
            name, key_hash, key_prefix, scopes, source_label, created_by = params
            key = {
                "key_id": str(uuid.uuid4()),
                "name": name,
                "key_hash": key_hash,
                "key_prefix": key_prefix,
                "scopes": list(scopes),
                "source_label": source_label,
                "created_by": created_by,
                "created_at": dt.datetime.now(UTC),
                "revoked_at": None,
            }
            self.api_keys[key["key_id"]] = key
            return FakeCursor([(key["key_id"], key["created_at"])])

        if q.startswith("UPDATE auth.api_keys SET revoked_at"):
            key = self.api_keys.get(str(params[0]))
            if key is None or key["revoked_at"] is not None:
                return FakeCursor([])
            key["revoked_at"] = dt.datetime.now(UTC)
            return FakeCursor([(key["key_id"], key["revoked_at"])])

        if q.startswith("SELECT key_id FROM auth.api_keys WHERE key_id"):
            key = self.api_keys.get(str(params[0]))
            return FakeCursor([(key["key_id"],)] if key else [])

        if q.startswith("SELECT key_id, name, key_prefix, scopes"):
            rows = sorted(self.api_keys.values(), key=lambda k: k["created_at"])
            return FakeCursor(
                [
                    (
                        k["key_id"], k["name"], k["key_prefix"], k["scopes"],
                        k["source_label"], k["created_by"], k["created_at"],
                        k["revoked_at"],
                    )
                    for k in rows
                ]
            )

        # -- per-agency settings (migration 0014) ----------------------------
        if q.startswith("SELECT setting_key, setting_value, value_type"):
            if "WHERE setting_key = %s" in q:
                rows = [self.settings[params[0]]] if params[0] in self.settings else []
            else:
                rows = sorted(self.settings.values(), key=lambda s: s["setting_key"])
            return FakeCursor(
                [
                    (
                        s["setting_key"], s["setting_value"], s["value_type"],
                        s["description"], s["updated_by"], s["updated_at"],
                    )
                    for s in rows
                ]
            )

        if q.startswith("UPDATE app.settings SET setting_value"):
            new_value, updated_by, setting_key = params
            setting = self.settings.get(setting_key)
            if setting is None:
                return FakeCursor([])
            setting["setting_value"] = new_value
            setting["updated_by"] = updated_by
            setting["updated_at"] = dt.datetime.now(UTC)
            return FakeCursor([(setting["updated_at"],)])

        # -- webhook subscriptions (handoff 0006) ---------------------------
        if q.startswith("INSERT INTO auth.webhook_subscriptions"):
            url, event_types, secret, created_by = params
            sub = {
                "subscription_id": str(uuid.uuid4()),
                "url": url,
                "event_types": list(event_types),
                "secret": secret,
                "created_by": created_by,
                "created_at": dt.datetime.now(UTC),
                "revoked_at": None,
            }
            self.webhook_subscriptions[sub["subscription_id"]] = sub
            return FakeCursor([(sub["subscription_id"], sub["created_at"])])

        if (
            "FROM auth.webhook_subscriptions WHERE revoked_at IS NULL" in q
            and "secret" in q
        ):
            rows = [
                (s["subscription_id"], s["url"], s["event_types"], s["secret"])
                for s in sorted(
                    self.webhook_subscriptions.values(),
                    key=lambda s: s["created_at"],
                )
                if s["revoked_at"] is None
            ]
            return FakeCursor(rows)

        if q.startswith("SELECT subscription_id, url, event_types, created_by"):
            rows = sorted(
                self.webhook_subscriptions.values(), key=lambda s: s["created_at"]
            )
            return FakeCursor(
                [
                    (
                        s["subscription_id"], s["url"], s["event_types"],
                        s["created_by"], s["created_at"], s["revoked_at"],
                    )
                    for s in rows
                ]
            )

        if q.startswith("UPDATE auth.webhook_subscriptions SET revoked_at"):
            sub = self.webhook_subscriptions.get(str(params[0]))
            if sub is None or sub["revoked_at"] is not None:
                return FakeCursor([])
            sub["revoked_at"] = dt.datetime.now(UTC)
            return FakeCursor([(sub["subscription_id"], sub["revoked_at"])])

        if q.startswith(
            "SELECT subscription_id FROM auth.webhook_subscriptions"
        ):
            sub = self.webhook_subscriptions.get(str(params[0]))
            return FakeCursor([(sub["subscription_id"],)] if sub else [])

        # Webhook body values: metric_value_id, metric, value for the ids.
        if q.startswith("SELECT metric_value_id, metric, value") and "ANY(" in q:
            wanted = [str(i) for i in params[0]]
            rows = [
                (mv["metric_value_id"], mv["metric"], mv["value"])
                for i, mv in self.metric_values.items()
                if i in wanted
            ]
            return FakeCursor(rows)

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
            "detail": {},  # JSONB column default (migration 0010)
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
            "resolution_minutes": None,  # migration 0016 — null when unmeasured
        }
        issue.update(overrides)
        self.dq_issues[issue["issue_id"]] = issue
        return issue

    def add_api_key(self, name="test key", *, scopes=("ingest:tides",),
                    source_label="tides_simulated", revoked=False):
        """Seed an auth.api_keys row. Returns (row, full_key) — the full key
        exists only here and in issuance responses, never in the row."""
        new_key = machine_auth.generate_key()
        key = {
            "key_id": str(uuid.uuid4()),
            "name": name,
            "key_hash": new_key.key_hash,
            "key_prefix": new_key.key_prefix,
            "scopes": list(scopes),
            "source_label": source_label,
            "created_by": "cora",
            "created_at": dt.datetime.now(UTC),
            "revoked_at": dt.datetime.now(UTC) if revoked else None,
        }
        self.api_keys[key["key_id"]] = key
        return key, new_key.full_key

    def add_webhook_subscription(self, *, url="https://receiver.example/hook",
                                 event_types=("certification.created",),
                                 secret="a" * 32, revoked=False):
        sub = {
            "subscription_id": str(uuid.uuid4()),
            "url": url,
            "event_types": list(event_types),
            "secret": secret,
            "created_by": "cora",
            "created_at": dt.datetime.now(UTC),
            "revoked_at": dt.datetime.now(UTC) if revoked else None,
        }
        self.webhook_subscriptions[sub["subscription_id"]] = sub
        return sub

    def add_setting(self, setting_key, setting_value, value_type,
                    description="A policy setting.", updated_by="migration:0014"):
        self.settings[setting_key] = {
            "setting_key": setting_key,
            "setting_value": setting_value,
            "value_type": value_type,
            "description": description,
            "updated_by": updated_by,
            "updated_at": dt.datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        }
        return self.settings[setting_key]

    def seed_default_settings(self):
        """The four calc policy knobs exactly as migration 0014 seeds them,
        plus the branding keys exactly as migration 0015 seeds them."""
        self.add_setting(
            "coverage_threshold", "0.95", "decimal",
            description=(
                "Coverage certifiability line. 0.95 is an ENGINEERING "
                "PLACEHOLDER, not an FTA number (REGULATORY_TRACKER.md)."
            ),
        )
        self.add_setting(
            "gap_threshold_seconds", "300", "integer",
            description="Telemetry-gap threshold (engineering default).",
        )
        self.add_setting(
            "layover_max_seconds", "1800", "integer",
            description=(
                "Layover cap; data-informed + Exhibit 35 aligned, "
                "per-agency configurable."
            ),
        )
        self.add_setting(
            "missing_trip_threshold", "0.02", "decimal",
            description=(
                "The REAL FTA threshold (2026 NTD Policy Manual p. 146)."
            ),
        )
        # Branding keys (migration 0015, handoff 0008 pillar C).
        self.add_setting(
            "agency_display_name", "Transit Agency", "text",
            description="The agency's display name for the app shell.",
            updated_by="migration:0015",
        )
        self.add_setting(
            "brand_color_primary", "#1a5fb4", "text",
            description=(
                "Primary brand color. GUARDRAIL: colors that fail "
                "accessibility contrast are refused (WCAG 2.1 AA, 4.5:1)."
            ),
            updated_by="migration:0015",
        )
        self.add_setting(
            "brand_color_accent", "#0b57d0", "text",
            description=(
                "Accent brand color. GUARDRAIL: colors that fail "
                "accessibility contrast are refused (WCAG 2.1 AA, 4.5:1)."
            ),
            updated_by="migration:0015",
        )
        self.add_setting(
            "brand_logo_meta", "unset", "text",
            description=(
                "Maintained by Headway: the uploaded logo's content type, "
                "or 'unset' when none has been uploaded."
            ),
            updated_by="migration:0015",
        )

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


# ---------------------------------------------------------------------------
# Fakes for the external systems (handoff 0006): object store, Kafka producer,
# and webhook HTTP sender — all behind the small protocols the app consumes.
# The store and producer share ONE call log so tests can assert
# store-before-produce ordering (the tides.go precedent).
# ---------------------------------------------------------------------------


class FakeObjectStore:
    def __init__(self, call_log=None):
        self.objects: dict[str, bytes] = {}
        self.call_log = call_log if call_log is not None else []

    def put(self, key, data, content_type):
        self.call_log.append(("store.put", key))
        self.objects[key] = bytes(data)

    def get(self, key):
        self.call_log.append(("store.get", key))
        return self.objects.get(key)


class FakeProducer:
    def __init__(self, call_log=None):
        self.produced: list[tuple[str, bytes, bytes]] = []
        self.call_log = call_log if call_log is not None else []

    def produce(self, topic, key, value):
        self.call_log.append(("producer.produce", topic, key))
        self.produced.append((topic, key, value))


class FakeWebhookSender:
    """Records every delivery; serves queued outcomes (int status code or an
    Exception to raise), defaulting to 200."""

    def __init__(self):
        self.deliveries: list[tuple[str, bytes, dict]] = []
        self.outcomes: list = []

    def post(self, url, body, headers):
        self.deliveries.append((url, bytes(body), dict(headers)))
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return 200


@pytest.fixture
def fake_db():
    db = FakeConn()
    db.add_user("vera", "viewer")
    db.add_user("stella", "data_steward")
    db.add_user("petra", "report_preparer")
    db.add_user("cora", "certifying_official")
    db.add_user("dora", "viewer", disabled=True)
    db.seed_default_settings()
    return db


@pytest.fixture
def settings():
    return Settings(session_secret=TEST_SECRET, token_ttl_seconds=600)


@pytest.fixture
def ingest_call_log():
    """Shared store/producer call log — asserts store-before-produce order."""
    return []


@pytest.fixture
def fake_store(ingest_call_log):
    return FakeObjectStore(call_log=ingest_call_log)


@pytest.fixture
def fake_producer(ingest_call_log):
    return FakeProducer(call_log=ingest_call_log)


@pytest.fixture
def fake_webhook_sender():
    return FakeWebhookSender()


@pytest.fixture
def app(fake_db, settings, fake_store, fake_producer, fake_webhook_sender):
    return create_app(
        settings=settings,
        db=fake_db,
        object_store=fake_store,
        producer=fake_producer,
        webhook_sender=fake_webhook_sender,
    )


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


def machine_header(full_key: str) -> dict:
    return {"Authorization": f"Bearer {full_key}"}
