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
import json
import sys
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from headway_api import auth, machine_auth, raw_payloads, signing  # noqa: E402
from headway_api.app import Settings, create_app  # noqa: E402

TEST_SECRET = "test-only-session-secret-not-for-production"

#: Deterministic Ed25519 seed for tests — NEVER a production key. The app
#: fixture injects the loaded signer onto app.state so certify tests sign;
#: the no-key refusal path builds its own app without it.
TEST_SIGNING_SEED_HEX = "ab" * 32

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


def _dq_filters(q: str, params) -> list[tuple[str, object]]:
    """Read back the queue filters ``dq.list_issues`` built, in its order.

    The router appends ``status`` then ``severity`` (handoff 0030), each
    with one positional parameter, before any cursor/limit parameters — so
    walking the query text and the parameters together in that order
    reconstructs the filter exactly, without this fake having to parse SQL.
    """
    out: list[tuple[str, object]] = []
    i = 0
    if "status = %s" in q:
        out.append(("status", params[i]))
        i += 1
    if "severity = %s" in q:
        out.append(("severity", params[i]))
        i += 1
    return out


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
        # Stands in for migration 0005's ``edges_output_idx``. Without it the
        # walk below is a sequential scan per frontier node, which is
        # quadratic in the edge count — so a test that seeds a realistically
        # large lineage graph measures this double's scan instead of the
        # product. Invalidated by ``add_edge``.
        self._lineage_by_output: dict[tuple[str, str], list[dict]] | None = None
        self.certifications: list[dict] = []
        self.audit_events: list[dict] = []
        self.api_keys: dict[str, dict] = {}
        self.webhook_subscriptions: dict[str, dict] = {}
        self.settings: dict[str, dict] = {}
        # Safety & Security (handoff 0010 / migration 0017).
        self.safety_events: dict[str, dict] = {}
        self.safety_classifications: list[dict] = []
        self.operated_modes: list[str] = []
        # Sampling (handoff 0012 / migration 0020).
        self.sampling_plans: dict[str, dict] = {}
        self.sampling_draws: list[dict] = []
        self.sampling_measurements: dict[str, dict] = {}
        # Statistician attestations (handoff 0019 / migration 0029).
        self.attestations: dict[str, dict] = {}
        # Service-day overrides (handoff 0020 / migration 0031), keyed by
        # ISO date string.
        self.service_day_overrides: dict[str, dict] = {}
        # Map wave (handoff 0023): live vehicle positions + GTFS-static
        # geometry (canonical.stops / canonical.trips / canonical.stop_times
        # / canonical.routes).
        self.vehicle_positions: list[dict] = []
        # Sources status (handoff 0025): the raw.records ingest registry.
        self.raw_records: list[dict] = []
        # Calc runs dispatched from the UI (handoff 0026 / migration 0033).
        self.calc_runs: dict[str, dict] = {}
        self.stops: dict[str, dict] = {}
        self.canonical_routes: dict[str, dict] = {}
        self.canonical_trips: dict[str, dict] = {}
        self.stop_times: list[dict] = []
        # Revenue review queue (handoff 0040 / migration 0040): no-run
        # boardings the calculation held out of the figure pending a human
        # decision, keyed by passenger_event_id.
        self.boarding_reviews: dict[str, dict] = {}
        # Single sign-on (handoff 0046 / migration 0043): the one provider
        # row, the claim->role grants, and in-flight authorization requests.
        self.oidc_provider: dict | None = None
        self.oidc_role_mappings: dict[str, dict] = {}
        self.oidc_login_states: dict[str, dict] = {}
        self._next_classification_id = 1
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
                self.safety_events,
                self.safety_classifications,
                self.sampling_plans,
                self.sampling_draws,
                self.sampling_measurements,
                self.attestations,
                self.service_day_overrides,
                self.calc_runs,
                self.boarding_reviews,
                self.oidc_provider,
                self.oidc_role_mappings,
                self.oidc_login_states,
                self._next_classification_id,
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
                self.safety_events,
                self.safety_classifications,
                self.sampling_plans,
                self.sampling_draws,
                self.sampling_measurements,
                self.attestations,
                self.service_day_overrides,
                self.calc_runs,
                self.boarding_reviews,
                self.oidc_provider,
                self.oidc_role_mappings,
                self.oidc_login_states,
                self._next_classification_id,
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

        if q.startswith(
            "SELECT user_id, username, password_hash, role, is_active "
            "FROM auth.users WHERE username"
        ):
            # auth.login — the ONLY query that ever reads a password hash.
            u = self.users.get(params[0])
            rows = (
                [(u["user_id"], u["username"], u["password_hash"], u["role"], u["is_active"])]
                if u
                else []
            )
            return FakeCursor(rows)

        # -- users admin (handoff 0025 / migration 0032) ---------------------
        if q.startswith(
            "SELECT user_id, role, is_active, created_at FROM auth.users "
            "WHERE username"
        ):
            u = self.users.get(params[0])
            rows = (
                [(u["user_id"], u["role"], u["is_active"], u["created_at"])]
                if u
                else []
            )
            return FakeCursor(rows)

        if q.startswith(
            "SELECT username, role, is_active, created_at FROM auth.users"
        ):
            rows = sorted(
                self.users.values(),
                key=lambda u: (u["created_at"], u["username"]),
            )
            return FakeCursor(
                [
                    (u["username"], u["role"], u["is_active"], u["created_at"])
                    for u in rows
                ]
            )

        # The LOCAL-account insert specifically; the federated insert names a
        # different column list and is handled with the rest of single sign-on.
        if q.startswith("INSERT INTO auth.users (username, password_hash, role)"):
            username, password_hash, role = params
            # Honest model of the ON CONFLICT (username) DO NOTHING clause:
            # an existing username returns NO row.
            if username in self.users:
                return FakeCursor([])
            # The migration-0009/0032/0042 CHECK + defaults, modeled honestly.
            assert role in (
                "viewer", "data_steward", "report_preparer",
                "certifying_official", "auditor",
            )
            u = {
                "user_id": str(uuid.uuid4()),
                "username": username,
                "password_hash": password_hash,
                "role": role,
                "is_active": True,
                "auth_source": "local",
                "idp_issuer": None,
                "idp_subject": None,
                "last_login_at": None,
                "created_at": dt.datetime.now(UTC),
            }
            self.users[username] = u
            return FakeCursor([(u["user_id"], u["created_at"])])

        if q.startswith("UPDATE auth.users SET password_hash"):
            password_hash, username = params
            u = self.users.get(username)
            if u is None:
                return FakeCursor([])
            u["password_hash"] = password_hash
            return FakeCursor([(u["user_id"],)])

        if q.startswith("UPDATE auth.users SET is_active"):
            is_active, username = params
            u = self.users.get(username)
            if u is None:
                return FakeCursor([])
            u["is_active"] = bool(is_active)
            return FakeCursor([(u["user_id"],)])

        # The admin Users API updates by USERNAME; the federated role sync
        # updates by user_id and is handled with the rest of single sign-on.
        if q.startswith("UPDATE auth.users SET role = %s WHERE username"):
            role, username = params
            u = self.users.get(username)
            if u is None:
                return FakeCursor([])
            u["role"] = role
            return FakeCursor([(u["user_id"],)])

        if q.startswith(
            "SELECT count(*) FROM auth.users "
            "WHERE role = 'certifying_official' AND is_active"
        ):
            n = sum(
                1
                for u in self.users.values()
                if u["role"] == "certifying_official"
                and u["is_active"]
                and u["username"] != params[0]
            )
            return FakeCursor([(n,)])

        if (
            q.startswith("SELECT metric_value_id, metric, unit")
            and "ANY(%s)" in q
        ):
            # certify._SELECT_FIGURES (handoff 0019): the full figure rows
            # the canonical document covers.
            wanted = [str(i) for i in params[0]]
            rows = [
                (
                    mv["metric_value_id"], mv["metric"], mv["unit"],
                    mv["period_start"], mv["period_end"], mv["scope"],
                    mv["value"], mv["calc_name"], mv["calc_version"],
                    mv["category"], mv["detail"],
                )
                for i, mv in self.metric_values.items()
                if i in wanted
            ]
            return FakeCursor(rows)

        if q.startswith("SELECT metric_value_id, metric, unit"):
            rows = list(self.metric_values.values())
            if "WHERE certification_status = 'certified'" in q:
                # The public open-data query: certified figures only, no params.
                rows = [r for r in rows if r["certification_status"] == "certified"]
            if "AND category = 'ntd'" in q:
                # The migration-0024 hard clause on certifiable read paths.
                rows = [r for r in rows if r["category"] == "ntd"]
            i = 0
            if "metric = %s" in q:
                rows = [r for r in rows if r["metric"] == params[i]]
                i += 1
            if "scope = %s" in q:
                # /metrics/history (handoff 0023) filter.
                rows = [r for r in rows if r["scope"] == params[i]]
                i += 1
            if "calc_version = %s" in q:
                rows = [r for r in rows if r["calc_version"] == params[i]]
                i += 1
            if "period_start >= %s" in q:
                rows = [r for r in rows if r["period_start"] >= params[i]]
                i += 1
            if "period_end <= %s" in q:
                rows = [r for r in rows if r["period_end"] <= params[i]]
                i += 1
            if "category = %s" in q:
                rows = [r for r in rows if r["category"] == params[i]]
                i += 1
            if "ORDER BY period_start, metric, scope, computed_at, metric_value_id" in q:
                # /metrics/history: the fully deterministic ordering.
                rows.sort(
                    key=lambda r: (
                        r["period_start"], r["metric"], r["scope"],
                        r["computed_at"], str(r["metric_value_id"]),
                    )
                )
            else:
                rows.sort(key=lambda r: (r["period_start"], r["metric"]))
            if "LIMIT %s" in q:
                rows = rows[: params[i]]
                i += 1
            return FakeCursor(
                [
                    (
                        r["metric_value_id"], r["metric"], r["unit"],
                        r["period_start"], r["period_end"], r["scope"],
                        r["value"], r["calc_name"], r["calc_version"],
                        r["computed_at"], r["certification_status"],
                        r["detail"], r["category"],
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
                (mv["metric_value_id"], mv["certification_status"], mv["category"])
                for i, mv in self.metric_values.items()
                if i in wanted
            ]
            return FakeCursor(rows)

        if q.startswith("SELECT severity, status, count(*), "):
            # /dq/issues/counts (handoff 0023): the SQL-side GROUP BY over
            # exactly the rows /dq/issues serves under the same filter,
            # carrying the effort sum since handoff 0030.
            rows = list(self.dq_issues.values())
            if "WHERE status = %s" in q:
                rows = [r for r in rows if r["status"] == params[0]]
            grouped: dict[tuple, list[int]] = {}
            for r in rows:
                key = (r["severity"], r["status"])
                cell = grouped.setdefault(key, [0, 0])
                cell[0] += 1
                cell[1] += r["resolution_minutes"] or 0
            return FakeCursor(
                [
                    (sev, st, n, minutes)
                    for (sev, st), (n, minutes) in sorted(grouped.items())
                ]
            )

        if (
            q.startswith("SELECT count(*) FROM dq.issues")
            # ...but NOT the certification gate below, which pins its
            # severity and status as SQL literals.
            and "'blocking'" not in q
        ):
            # The page total (handoff 0030): counted over EXACTLY the rows
            # the page's own filters select — never derived from the page.
            rows = list(self.dq_issues.values())
            for cond, value in _dq_filters(q, params):
                rows = [r for r in rows if r[cond] == value]
            return FakeCursor([(len(rows),)])

        if "count(*) FROM dq.issues" in q:
            n = sum(
                1
                for i in self.dq_issues.values()
                if i["severity"] == "blocking"
                and i["status"] in ("open", "owned")
                # migration 0024: only NTD findings gate certification.
                and (
                    "AND category = 'ntd'" not in q
                    or i["category"] == "ntd"
                )
            )
            return FakeCursor([(n,)])

        if q.startswith("INSERT INTO cert.certifications"):
            # Migration 0030 shape: explicit id + timestamp + the signature
            # trio (the certified_at in the row is EXACTLY the timestamp
            # inside the signed document).
            (certification_id, ids, certified_by, certified_at, attestation,
             canonical_document, signature, key_fingerprint) = params
            cert = {
                "certification_id": str(certification_id),
                "metric_value_ids": list(ids),
                "certified_by": certified_by,
                "certified_at": certified_at,
                "attestation": attestation,
                "canonical_document": canonical_document,
                "signature": signature,
                "key_fingerprint": key_fingerprint,
            }
            self.certifications.append(cert)
            return FakeCursor([(cert["certification_id"], cert["certified_at"])])

        if q.startswith(
            "SELECT certification_id, metric_value_ids, certified_by"
        ):
            rows = list(self.certifications)
            if "WHERE certification_id = %s" in q:
                rows = [
                    c for c in rows
                    if c["certification_id"] == str(params[0])
                ]
            else:
                rows.sort(
                    key=lambda c: (c["certified_at"], c["certification_id"])
                )
            return FakeCursor(
                [
                    (
                        c["certification_id"], c["metric_value_ids"],
                        c["certified_by"], c["certified_at"],
                        c["attestation"], c.get("canonical_document"),
                        c.get("signature"), c.get("key_fingerprint"),
                    )
                    for c in rows
                ]
            )

        if q.startswith(
            "SELECT certification_id, certified_at, key_fingerprint"
        ):
            # public._SELECT_CERTIFICATION_REFS (handoff 0019, point 7).
            return FakeCursor(
                [
                    (
                        c["certification_id"], c["certified_at"],
                        c.get("key_fingerprint"), c["metric_value_ids"],
                    )
                    for c in self.certifications
                ]
            )

        if q.startswith("SELECT DISTINCT c.certification_id"):
            # reports._SELECT_PERIOD_CERTIFICATIONS: certifications whose
            # covered figures fall in the half-open month period and stand
            # certified.
            period_start, period_end = params
            rows = []
            for c in sorted(
                self.certifications,
                key=lambda c: (c["certified_at"], c["certification_id"]),
            ):
                for mv_id in c["metric_value_ids"]:
                    mv = self.metric_values.get(str(mv_id))
                    if (
                        mv is not None
                        and mv["period_start"] >= period_start
                        and mv["period_end"] <= period_end
                        and mv["certification_status"] == "certified"
                    ):
                        rows.append(
                            (
                                c["certification_id"], c["certified_by"],
                                c["certified_at"], c.get("key_fingerprint"),
                                c.get("canonical_document"),
                            )
                        )
                        break
            return FakeCursor(rows)

        if q.startswith("UPDATE computed.metric_values SET certification_status"):
            wanted = [str(i) for i in params[0]]
            n = 0
            for i in wanted:
                if i in self.metric_values:
                    if (
                        "AND category = 'ntd'" in q
                        and self.metric_values[i]["category"] != "ntd"
                    ):
                        # migration 0024: an ops row is never updatable to
                        # certified (the WHERE skips it; the database CHECK
                        # would refuse it anyway).
                        continue
                    self.metric_values[i]["certification_status"] = "certified"
                    n += 1
            return FakeCursor([], rowcount=n)


        # ---- single sign-on (handoff 0046 / migration 0043) ----------------
        # Modelled at the same fidelity as the real schema: the provider row
        # is a singleton, claim_value is UNIQUE (so a duplicate INSERT
        # returns no row), and consuming a login state is a CONDITIONAL
        # UPDATE that exactly one caller can win.

        if q.startswith("SELECT discovery_url, client_id, client_secret_encrypted"):
            p_ = self.oidc_provider
            if p_ is None:
                return FakeCursor([])
            return FakeCursor([(
                p_["discovery_url"], p_["client_id"],
                p_["client_secret_encrypted"], p_["redirect_uri"],
                p_["groups_claim"], p_["username_claim"],
                p_["clock_skew_seconds"], p_["ca_bundle_path"],
                p_["button_label"], p_["is_enabled"],
                p_["updated_by"], p_["updated_at"],
            )])

        if q.startswith("INSERT INTO auth.oidc_provider"):
            (discovery_url, client_id, secret, redirect_uri, groups_claim,
             username_claim, skew, ca_bundle, button_label, is_enabled,
             updated_by) = params
            now = dt.datetime.now(UTC)
            self.oidc_provider = {
                "discovery_url": discovery_url,
                "client_id": client_id,
                "client_secret_encrypted": secret,
                "redirect_uri": redirect_uri,
                "groups_claim": groups_claim,
                "username_claim": username_claim,
                "clock_skew_seconds": skew,
                "ca_bundle_path": ca_bundle,
                "button_label": button_label,
                "is_enabled": is_enabled,
                "updated_by": updated_by,
                "updated_at": now,
            }
            return FakeCursor([(now,)])

        if q.startswith("SELECT mapping_id, claim_value, headway_role"):
            rows = sorted(
                self.oidc_role_mappings.values(), key=lambda m: m["claim_value"]
            )
            return FakeCursor([
                (m["mapping_id"], m["claim_value"], m["headway_role"],
                 m["note"], m["created_by"], m["created_at"])
                for m in rows
            ])

        if q.startswith("INSERT INTO auth.oidc_role_mappings"):
            claim_value, headway_role, note, created_by = params
            # migration 0043's CHECK: the IdP can never be given the
            # certifying_official role, at the database level too.
            assert headway_role in (
                "viewer", "data_steward", "report_preparer", "auditor"
            ), "migration 0043 CHECK would reject this role"
            if any(
                m["claim_value"] == claim_value
                for m in self.oidc_role_mappings.values()
            ):
                return FakeCursor([])  # ON CONFLICT (claim_value) DO NOTHING
            mapping_id = str(uuid.uuid4())
            created_at = dt.datetime.now(UTC)
            self.oidc_role_mappings[mapping_id] = {
                "mapping_id": mapping_id,
                "claim_value": claim_value,
                "headway_role": headway_role,
                "note": note,
                "created_by": created_by,
                "created_at": created_at,
            }
            return FakeCursor([(mapping_id, created_at)])

        if q.startswith("DELETE FROM auth.oidc_role_mappings"):
            m = self.oidc_role_mappings.pop(params[0], None)
            if m is None:
                return FakeCursor([])
            return FakeCursor([(m["claim_value"], m["headway_role"])])

        if q.startswith("INSERT INTO auth.oidc_login_states"):
            state, nonce, verifier, binding, redirect_uri, expires_at = params
            self.oidc_login_states[state] = {
                "state": state,
                "nonce": nonce,
                "code_verifier": verifier,
                "browser_binding": binding,
                "redirect_uri": redirect_uri,
                "expires_at": expires_at,
                "consumed_at": None,
            }
            return FakeCursor([])

        if q.startswith("UPDATE auth.oidc_login_states SET consumed_at"):
            row = self.oidc_login_states.get(params[0])
            now = dt.datetime.now(UTC)
            # The WHERE clause verbatim: unknown, already consumed, or
            # expired all return NO row, so the caller cannot tell them apart.
            if row is None or row["consumed_at"] is not None or row["expires_at"] <= now:
                return FakeCursor([])
            row["consumed_at"] = now
            return FakeCursor([(
                row["nonce"], row["code_verifier"], row["browser_binding"],
                row["redirect_uri"],
            )])

        if q.startswith("DELETE FROM auth.oidc_login_states WHERE expires_at"):
            now = dt.datetime.now(UTC)
            stale = [k for k, v in self.oidc_login_states.items()
                     if v["expires_at"] < now]
            for k in stale:
                del self.oidc_login_states[k]
            return FakeCursor([], rowcount=len(stale))

        if q.startswith("SELECT user_id, username, role, is_active FROM auth.users WHERE idp_issuer"):
            issuer, subject = params
            for u in self.users.values():
                if u.get("idp_issuer") == issuer and u.get("idp_subject") == subject:
                    return FakeCursor([(
                        u["user_id"], u["username"], u["role"], u["is_active"]
                    )])
            return FakeCursor([])

        if q.startswith("SELECT user_id, role, is_active, auth_source FROM auth.users"):
            u = self.users.get(params[0])
            if u is None:
                return FakeCursor([])
            return FakeCursor([(
                u["user_id"], u["role"], u["is_active"], u["auth_source"]
            )])

        if q.startswith("INSERT INTO auth.users (username, role, auth_source"):
            username, role, issuer, subject = params
            assert role in (
                "viewer", "data_steward", "report_preparer", "auditor"
            ), "the IdP may not grant this role"
            if username in self.users:
                return FakeCursor([])  # ON CONFLICT (username) DO NOTHING
            u = {
                "user_id": str(uuid.uuid4()),
                "username": username,
                "password_hash": None,  # migration 0043: federated = no password
                "role": role,
                "is_active": True,
                "auth_source": "oidc",
                "idp_issuer": issuer,
                "idp_subject": subject,
                "last_login_at": None,
                "created_at": dt.datetime.now(UTC),
            }
            self.users[username] = u
            return FakeCursor([(u["user_id"],)])

        if q.startswith("UPDATE auth.users SET role = %s WHERE user_id"):
            role, user_id = params
            for u in self.users.values():
                if u["user_id"] == user_id:
                    u["role"] = role
                    return FakeCursor([(u["username"],)])
            return FakeCursor([])

        if q.startswith("UPDATE auth.users SET last_login_at"):
            for u in self.users.values():
                if u["user_id"] == params[0]:
                    u["last_login_at"] = dt.datetime.now(UTC)
                    return FakeCursor([], rowcount=1)
            return FakeCursor([], rowcount=0)

        # ---- the audit trail, read back (handoff 0046, the auditor role) ---
        if q.startswith("SELECT event_id, at, actor, action, subject_kind"):
            rows = sorted(
                self.audit_events, key=lambda e: e["event_id"], reverse=True
            )
            i = 0
            for column in ("actor", "action", "subject_kind", "subject_id"):
                if f"{column} = %s" in q:
                    rows = [e for e in rows if e[column] == params[i]]
                    i += 1
            if "event_id < %s" in q:
                rows = [e for e in rows if e["event_id"] < params[i]]
                i += 1
            rows = rows[: params[i]]  # LIMIT
            return FakeCursor([
                (e["event_id"], e["at"], e["actor"], e["action"],
                 e["subject_kind"], e["subject_id"], e["detail"])
                for e in rows
            ])

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
            # Handoff 0030: the queue columns are a strict PREFIX of the
            # per-issue columns — source_record_ids rides last and only on
            # the detail query, which is the whole point of the change.
            detail = "source_record_ids" in q
            rows = list(self.dq_issues.values())
            if "WHERE issue_id = %s" in q:
                # GET /dq/issues/{id} (handoff 0026 deep link).
                rows = [r for r in rows if r["issue_id"] == str(params[0])]
            else:
                for cond, value in _dq_filters(q, params):
                    rows = [r for r in rows if r[cond] == value]
            # Deterministic AND total: the primary key breaks every tie, so
            # paging can neither skip nor repeat a row (handoff 0030).
            rows.sort(key=lambda r: (r["created_at"], str(r["issue_id"])))
            if "(created_at, issue_id) > (%s, %s)" in q:
                after = tuple(params[-3:-1])
                rows = [
                    r
                    for r in rows
                    if (r["created_at"], str(r["issue_id"]))
                    > (after[0], str(after[1]))
                ]
            if " LIMIT %s" in q:
                rows = rows[: params[-1]]

            def _row(r):
                queue_columns = (
                    r["issue_id"], r["issue_type"], r["severity"], r["status"],
                    r["owner"], r["title"], r["description"],
                    r["created_at"], r["resolved_at"], r["resolution"],
                    r["resolution_minutes"],
                    # Migration 0035 (handoff 0029): the frozen,
                    # agency-vocabulary context. None for every pre-0035
                    # row — the default here, because that is the shape
                    # 97,067 live rows have.
                    r["subject_context"],
                )
                if detail:
                    return queue_columns + (r["source_record_ids"],)
                return queue_columns

            return FakeCursor([_row(r) for r in rows])

        # -- revenue review queue (handoff 0040 / migration 0040) ------------
        # Registered BEFORE the generic dq.issues resolve handler below: the
        # review router closes a boarding's finding with a two-parameter
        # UPDATE whose prefix would otherwise be swallowed by the
        # three-parameter DQ one.
        if q.startswith(
            "UPDATE dq.issues SET status = 'resolved', resolved_at = now(), "
            "resolution = %s WHERE issue_id"
        ):
            resolution, issue_id = params
            issue = self.dq_issues.get(str(issue_id))
            if issue is None or issue["status"] not in ("open", "owned"):
                return FakeCursor([])
            issue["status"] = "resolved"
            issue["resolved_at"] = dt.datetime.now(UTC)
            issue["resolution"] = resolution
            return FakeCursor([])

        if q.startswith(
            "SELECT issue_id FROM dq.issues WHERE issue_type = %s "
            "AND status IN ('open', 'owned') AND %s = ANY(source_record_ids)"
        ):
            issue_type, record_id = params
            rows = sorted(
                (
                    i
                    for i in self.dq_issues.values()
                    if i["issue_type"] == issue_type
                    and i["status"] in ("open", "owned")
                    and record_id in (i["source_record_ids"] or [])
                ),
                key=lambda i: (i["created_at"], str(i["issue_id"])),
            )
            return FakeCursor([(r["issue_id"],) for r in rows[:1]])

        if q.startswith("SELECT count(*) FROM dq.boarding_revenue_reviews"):
            pending_only = "WHERE verdict IS NULL" in q
            rows = [
                r
                for r in self.boarding_reviews.values()
                if (r["verdict"] is None) == pending_only
            ]
            return FakeCursor([(len(rows),)])

        if q.startswith(
            "SELECT verdict, count(*), coalesce(sum(event_count), 0) "
            "FROM dq.boarding_revenue_reviews"
        ):
            grouped: dict = {}
            for r in self.boarding_reviews.values():
                bucket = grouped.setdefault(r["verdict"], [0, 0])
                bucket[0] += 1
                bucket[1] += r["event_count"]
            return FakeCursor(
                [(v, c, s) for v, (c, s) in grouped.items()]
            )

        if q.startswith("SELECT passenger_event_id, source_record_id"):
            def _review_row(r):
                return (
                    r["passenger_event_id"], r["source_record_id"],
                    r["service_date"], r["event_timestamp"], r["vehicle_id"],
                    r["event_count"], r["suggested_verdict"],
                    r["suggested_reason"], r["calc_name"], r["calc_version"],
                    r["period_start"], r["period_end"], r["first_seen_at"],
                    r["verdict"], r["justification"], r["classified_by"],
                    r["classified_at"], r["dq_issue_id"],
                )

            if "WHERE passenger_event_id = %s" in q:
                r = self.boarding_reviews.get(str(params[0]))
                return FakeCursor([_review_row(r)] if r else [])
            pending_only = "WHERE verdict IS NULL" in q
            rows = [
                r
                for r in self.boarding_reviews.values()
                if (r["verdict"] is None) == pending_only
            ]
            rows.sort(
                key=lambda r: (r["event_timestamp"], r["passenger_event_id"])
            )
            rest = list(params)
            if "(event_timestamp, passenger_event_id) > (%s, %s)" in q:
                after_ts, after_id = rest[0], rest[1]
                rows = [
                    r
                    for r in rows
                    if (r["event_timestamp"], r["passenger_event_id"])
                    > (after_ts, after_id)
                ]
                rest = rest[2:]
            limit = rest[0]
            return FakeCursor([_review_row(r) for r in rows[:limit]])

        if q.startswith("UPDATE dq.boarding_revenue_reviews SET verdict"):
            verdict, justification, actor, dq_issue_id, event_id = params
            r = self.boarding_reviews.get(str(event_id))
            if r is None or r["verdict"] is not None:
                return FakeCursor([])
            r["verdict"] = verdict
            r["justification"] = justification
            r["classified_by"] = actor
            r["classified_at"] = dt.datetime.now(UTC)
            r["dq_issue_id"] = dq_issue_id
            return FakeCursor([(r["classified_at"],)])

        if q.startswith(
            "SELECT metric_value_id, period_start, period_end, scope "
            "FROM computed.metric_values"
        ):
            metric, on_date, _same = params
            rows = sorted(
                (
                    v
                    for v in self.metric_values.values()
                    if v["metric"] == metric
                    and v["certification_status"] == "certified"
                    and v["period_start"] <= on_date < v["period_end"]
                ),
                key=lambda v: v["period_start"],
            )
            return FakeCursor(
                [
                    (
                        v["metric_value_id"], v["period_start"],
                        v["period_end"], v["scope"],
                    )
                    for v in rows[:1]
                ]
            )

        if q.startswith("UPDATE dq.issues SET status = 'resolved'"):
            resolution, resolution_minutes, issue_id = params
            issue = self.dq_issues.get(str(issue_id))
            if issue is None or issue["status"] not in ("open", "owned"):
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

        if q.startswith("UPDATE dq.issues SET status = 'attested'"):
            resolution, issue_id = params
            issue = self.dq_issues.get(str(issue_id))
            if issue is None or issue["status"] not in ("open", "owned"):
                return FakeCursor([])
            issue["status"] = "attested"
            issue["resolved_at"] = dt.datetime.now(UTC)
            issue["resolution"] = resolution
            return FakeCursor(
                [
                    (
                        issue["issue_id"], issue["issue_type"],
                        issue["severity"], issue["resolved_at"],
                    )
                ]
            )

        if q.startswith("SELECT issue_type, status FROM dq.issues"):
            issue = self.dq_issues.get(str(params[0]))
            return FakeCursor(
                [(issue["issue_type"], issue["status"])] if issue else []
            )

        if q.startswith("SELECT status FROM dq.issues"):
            issue = self.dq_issues.get(str(params[0]))
            return FakeCursor([(issue["status"],)] if issue else [])

        if q.startswith("SELECT resolution_minutes FROM dq.issues"):
            issue = self.dq_issues.get(str(params[0]))
            return FakeCursor(
                [(issue["resolution_minutes"],)] if issue else []
            )

        # -- raw-record inspector (handoff 0035) ----------------------------
        # The BATCHED read first (handoff 0047's evidence bundle labels every
        # leaf under a certification in one round trip). It shares a prefix
        # with the single-record query below and is told apart by ANY(%s),
        # exactly as the two statements differ in raw_records.py.
        if (
            q.startswith("SELECT record_id, source, connector, connector_version")
            and "ANY(%s)" in q
        ):
            wanted = {str(i) for i in params[0]}
            rows = [
                (
                    r["record_id"], r["source"], r["connector"],
                    r["connector_version"], r["content_type"],
                    r["payload_encoding"], r["payload_ref"], r["fetched_at"],
                    r["landed_at"], r["parse_status"], r["parse_error"],
                )
                for r in sorted(self.raw_records, key=lambda r: r["record_id"])
                if r["record_id"] in wanted
            ]
            return FakeCursor(rows)

        if q.startswith("SELECT record_id, source, connector, connector_version"):
            rows = [
                (
                    r["record_id"], r["source"], r["connector"],
                    r["connector_version"], r["content_type"],
                    r["payload_encoding"], r["payload_ref"], r["fetched_at"],
                    r["landed_at"], r["parse_status"], r["parse_error"],
                )
                for r in self.raw_records
                if r["record_id"] == params[0]
            ]
            return FakeCursor(rows)

        # The integrity-failure finding's idempotence probe: is there
        # already an unresolved issue of this type against this record?
        if q.startswith("SELECT issue_id FROM dq.issues WHERE issue_type"):
            issue_type, record_id = params
            rows = [
                (i["issue_id"],)
                for i in self.dq_issues.values()
                if i["issue_type"] == issue_type
                and i["status"] != "resolved"
                and record_id in (i["source_record_ids"] or [])
            ]
            return FakeCursor(rows[:1])

        if q.startswith("INSERT INTO dq.issues (issue_type, severity, status, "
                        "title, description, source_record_ids)"):
            issue_type, severity, status, title, description, ids = params
            issue = self.add_dq_issue(
                issue_type=issue_type,
                severity=severity,
                status=status,
                title=title,
                description=description,
                source_record_ids=list(ids),
                created_at=dt.datetime.now(UTC),
            )
            return FakeCursor([(issue["issue_id"],)])

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

        # -- agency workbook latest rows (handoff 0020) ----------------------
        if q.startswith(
            "SELECT DISTINCT ON (metric, scope) metric, scope, metric_value_id"
        ):
            period_start, period_end = params
            wanted = (
                "upt", "upt_avg", "days_operated", "voms", "otp",
                "headway_adherence",
            )
            candidates = [
                r
                for r in self.metric_values.values()
                if r["period_start"] == period_start
                and r["period_end"] == period_end
                and r["metric"] in wanted
            ]
            latest: dict[tuple, dict] = {}
            # Newest computed_at wins (metric_value_id tie-break) — the
            # DISTINCT ON the app's SQL does.
            for r in sorted(
                candidates,
                key=lambda r: (r["computed_at"], str(r["metric_value_id"])),
            ):
                latest[(r["metric"], r["scope"])] = r
            return FakeCursor(
                [
                    (
                        r["metric"], r["scope"], r["metric_value_id"],
                        r["value"], r["unit"], r["calc_name"],
                        r["calc_version"], r["certification_status"],
                        r["category"], r["detail"],
                    )
                    for _k, r in sorted(latest.items())
                ]
            )

        # -- service-day overrides (handoff 0020 / migration 0031) ----------
        if q.startswith("SELECT service_date, assigned_day_type, atypical"):
            rows = sorted(
                self.service_day_overrides.values(),
                key=lambda o: o["service_date"],
            )
            if "WHERE service_date >= %s AND service_date < %s" in q:
                rows = [
                    o for o in rows
                    if params[0] <= o["service_date"] < params[1]
                ]
            elif "WHERE service_date = %s" in q:
                rows = [o for o in rows if o["service_date"] == params[0]]
            return FakeCursor(
                [
                    (
                        o["service_date"], o["assigned_day_type"],
                        o["atypical"], o["reason"], o["updated_by"],
                        o["updated_at"],
                    )
                    for o in rows
                ]
            )

        if q.startswith("INSERT INTO app.service_day_overrides"):
            service_date, assigned, atypical, reason, updated_by = params
            # The migration-0031 CHECKs, honestly modeled by the fake.
            assert assigned in (None, "weekday", "saturday", "sunday")
            assert assigned is not None or atypical
            assert reason.strip()
            row = {
                "service_date": service_date,
                "assigned_day_type": assigned,
                "atypical": atypical,
                "reason": reason,
                "updated_by": updated_by,
                "updated_at": dt.datetime.now(UTC),
            }
            self.service_day_overrides[service_date.isoformat()] = row
            return FakeCursor([(row["updated_at"],)])

        if q.startswith("DELETE FROM app.service_day_overrides"):
            row = self.service_day_overrides.pop(params[0].isoformat(), None)
            return FakeCursor(
                [] if row is None else [(row["service_date"],)]
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

        # -- Safety & Security (handoff 0010 / migration 0017) ---------------
        if q.startswith("INSERT INTO safety.events"):
            (occurred_at, mode, type_of_service, event_category, narrative,
             location, fatalities, injuries, property_damage_usd,
             serious_injury, substantial_damage, towed,
             evacuation_life_safety, assault_on_worker,
             involves_transit_vehicle, involves_second_rail_vehicle,
             grade_crossing, runaway_train, evacuation_to_rail_row,
             entered_by) = params
            event = {
                "event_id": str(uuid.uuid4()),
                "occurred_at": occurred_at,
                "mode": mode,
                "type_of_service": type_of_service,
                "event_category": event_category,
                "narrative": narrative,
                "location": location,
                "fatalities": fatalities,
                "injuries": injuries,
                "property_damage_usd": property_damage_usd,
                "serious_injury": serious_injury,
                "substantial_damage": substantial_damage,
                "towed": towed,
                "evacuation_life_safety": evacuation_life_safety,
                "assault_on_worker": assault_on_worker,
                "involves_transit_vehicle": involves_transit_vehicle,
                "involves_second_rail_vehicle": involves_second_rail_vehicle,
                "grade_crossing": grade_crossing,
                "runaway_train": runaway_train,
                "evacuation_to_rail_row": evacuation_to_rail_row,
                "entered_by": entered_by,
                "entered_at": dt.datetime.now(UTC),
                "superseded_by": None,
            }
            self.safety_events[event["event_id"]] = event
            return FakeCursor([(event["event_id"], event["entered_at"])])

        if q.startswith("INSERT INTO safety.event_classifications"):
            event_id, classification, thresholds_met, classifier_version = params
            row = {
                "classification_id": self._next_classification_id,
                "event_id": str(event_id),
                "classification": classification,
                "thresholds_met": list(thresholds_met),
                "classifier_version": classifier_version,
                "classified_at": dt.datetime.now(UTC),
            }
            self._next_classification_id += 1
            self.safety_classifications.append(row)
            return FakeCursor([(row["classification_id"], row["classified_at"])])

        if "FROM safety.events" in q and ") AS latest" in q:
            rows = self._latest_safety_rows()
            i = 0
            if "occurred_at >= %s AND occurred_at < %s" in q:
                rows = [
                    r for r in rows
                    if params[i] <= r["occurred_at"] < params[i + 1]
                ]
                i += 2
            if "mode = %s" in q:
                rows = [r for r in rows if r["mode"] == params[i]]
                i += 1
            if "classification = %s" in q:
                rows = [r for r in rows if r["classification"] == params[i]]
                i += 1
            if "superseded_by IS NULL" in q:
                rows = [r for r in rows if r["superseded_by"] is None]
            rows.sort(key=lambda r: (r["occurred_at"], r["event_id"]))
            columns = (
                "event_id", "occurred_at", "mode", "type_of_service",
                "event_category", "narrative", "location", "fatalities",
                "injuries", "property_damage_usd", "serious_injury",
                "substantial_damage", "towed", "evacuation_life_safety",
                "assault_on_worker", "involves_transit_vehicle",
                "involves_second_rail_vehicle", "grade_crossing",
                "runaway_train", "evacuation_to_rail_row",
                "entered_by", "entered_at", "superseded_by",
                "classification", "thresholds_met", "classifier_version",
                "classified_at",
            )
            return FakeCursor([tuple(r[c] for c in columns) for r in rows])

        if q.startswith("SELECT superseded_by FROM safety.events"):
            event = self.safety_events.get(str(params[0]))
            return FakeCursor([(event["superseded_by"],)] if event else [])

        if q.startswith("UPDATE safety.events SET superseded_by"):
            replacement_id, event_id = params
            event = self.safety_events.get(str(event_id))
            if event is None or event["superseded_by"] is not None:
                return FakeCursor([])
            event["superseded_by"] = str(replacement_id)
            return FakeCursor([(event["event_id"],)])

        if q.startswith("SELECT DISTINCT r.mode"):
            # The handoff-0009 operated-mode derivation over
            # canonical.vehicle_positions (headway_calc.ss50).
            return FakeCursor([(m,) for m in self.operated_modes])

        # -- Sampling (handoff 0012 / migration 0020) -------------------------
        if q.startswith("INSERT INTO sampling.plans"):
            (report_year, mode, type_of_service, unit, efficiency_option,
             frequency, required_per_period, required_annual,
             table_citation, selector_version, created_by) = params
            plan = {
                "plan_id": str(uuid.uuid4()),
                "report_year": report_year,
                "mode": mode,
                "type_of_service": type_of_service,
                "unit": unit,
                "efficiency_option": efficiency_option,
                "frequency": frequency,
                "required_per_period": required_per_period,
                "required_annual": required_annual,
                "table_citation": table_citation,
                "selector_version": selector_version,
                "status": "created",
                "created_by": created_by,
                "created_at": dt.datetime.now(UTC),
            }
            self.sampling_plans[plan["plan_id"]] = plan
            return FakeCursor(
                [(plan["plan_id"], plan["status"], plan["created_at"])]
            )

        if q.startswith("SELECT plan_id, report_year"):
            if "WHERE plan_id = %s" in q:
                plan = self.sampling_plans.get(str(params[0]))
                rows = [plan] if plan else []
            else:
                rows = list(self.sampling_plans.values())
                i = 0
                if "report_year = %s" in q:
                    rows = [r for r in rows if r["report_year"] == params[i]]
                    i += 1
                if "mode = %s" in q:
                    rows = [r for r in rows if r["mode"] == params[i]]
                    i += 1
                rows.sort(key=lambda r: (r["created_at"], r["plan_id"]))
            columns = (
                "plan_id", "report_year", "mode", "type_of_service", "unit",
                "efficiency_option", "frequency", "required_per_period",
                "required_annual", "table_citation", "selector_version",
                "status", "created_by", "created_at",
            )
            return FakeCursor([tuple(r[c] for c in columns) for r in rows])

        if q.startswith("UPDATE sampling.plans SET status = 'active'"):
            plan = self.sampling_plans.get(str(params[0]))
            if plan is None or plan["status"] != "created":
                return FakeCursor([])
            plan["status"] = "active"
            return FakeCursor([(plan["plan_id"],)])

        if q.startswith("INSERT INTO sampling.draws"):
            (plan_id, period_label, service_units, selected_units, seed,
             seed_source, oversample_units, drawer_version, drawn_by) = params
            # Migration 0022's CHECK constraint, modeled honestly.
            assert seed_source in ("client", "generated"), (
                f"sampling.draws.seed_source CHECK violated: {seed_source!r}"
            )
            draw = {
                "draw_id": str(uuid.uuid4()),
                "plan_id": str(plan_id),
                "period_label": period_label,
                "service_units": list(service_units),
                "selected_units": list(selected_units),
                "seed": seed,
                "seed_source": seed_source,
                "oversample_units": oversample_units,
                "drawer_version": drawer_version,
                "drawn_by": drawn_by,
                "drawn_at": dt.datetime.now(UTC),
            }
            self.sampling_draws.append(draw)
            return FakeCursor([(draw["draw_id"], draw["drawn_at"])])

        if q.startswith("SELECT draw_id, plan_id, period_label"):
            rows = sorted(
                (
                    d for d in self.sampling_draws
                    if d["plan_id"] == str(params[0])
                ),
                key=lambda d: (d["drawn_at"], d["draw_id"]),
            )
            columns = (
                "draw_id", "plan_id", "period_label", "service_units",
                "selected_units", "seed", "seed_source", "oversample_units",
                "drawer_version", "drawn_by", "drawn_at",
            )
            return FakeCursor([tuple(d[c] for c in columns) for d in rows])

        if q.startswith("INSERT INTO sampling.measurements"):
            if "(measurement_id, plan_id" in q:
                (measurement_id, plan_id, unit_id, observed_upt,
                 observed_pmt, service_day_type, service_date, data_source,
                 notes, entered_by) = params
                measurement_id = str(measurement_id)
            else:
                measurement_id = str(uuid.uuid4())
                (plan_id, unit_id, observed_upt, observed_pmt,
                 service_day_type, service_date, data_source, notes,
                 entered_by) = params
            # Honest model of migration 0020's partial unique index
            # measurements_one_active_per_unit — the 2026-07-12 live
            # walkthrough caught an insert-before-link supersede bug this
            # fake had masked without it.
            for existing in self.sampling_measurements.values():
                if (
                    existing["plan_id"] == str(plan_id)
                    and existing["unit_id"] == unit_id
                    and existing["superseded_by"] is None
                ):
                    raise AssertionError(
                        "unique index measurements_one_active_per_unit "
                        "violated: an active measurement for "
                        f"({plan_id}, {unit_id}) already exists"
                    )
            m = {
                "measurement_id": measurement_id,
                "plan_id": str(plan_id),
                "unit_id": unit_id,
                "observed_upt": observed_upt,
                "observed_pmt": Decimal(str(observed_pmt)),
                "service_day_type": service_day_type,
                "service_date": service_date,
                "data_source": data_source,
                "notes": notes,
                "entered_by": entered_by,
                "entered_at": dt.datetime.now(UTC),
                "superseded_by": None,
            }
            self.sampling_measurements[m["measurement_id"]] = m
            return FakeCursor([(m["measurement_id"], m["entered_at"])])

        if q.startswith("SELECT measurement_id, plan_id"):
            if "WHERE measurement_id = %s" in q:
                m = self.sampling_measurements.get(str(params[0]))
                rows = [m] if m else []
            else:
                rows = sorted(
                    (
                        m for m in self.sampling_measurements.values()
                        if m["plan_id"] == str(params[0])
                    ),
                    key=lambda m: (m["entered_at"], m["measurement_id"]),
                )
            columns = (
                "measurement_id", "plan_id", "unit_id", "observed_upt",
                "observed_pmt", "service_day_type", "service_date",
                "data_source", "notes", "entered_by", "entered_at",
                "superseded_by",
            )
            return FakeCursor([tuple(m[c] for c in columns) for m in rows])

        if q.startswith("UPDATE sampling.measurements SET superseded_by"):
            replacement_id, measurement_id = params
            m = self.sampling_measurements.get(str(measurement_id))
            if m is None or m["superseded_by"] is not None:
                return FakeCursor([])
            m["superseded_by"] = str(replacement_id)
            return FakeCursor([(m["measurement_id"],)])

        # -- Statistician attestations (handoff 0019 / migration 0029) -------
        if q.startswith("INSERT INTO cert.attestations"):
            (statistician_name, statistician_credentials, method_description,
             document_reference, metric, scope_pattern, period_start,
             period_end, entered_by) = params
            att = {
                "attestation_id": str(uuid.uuid4()),
                "statistician_name": statistician_name,
                "statistician_credentials": statistician_credentials,
                "method_description": method_description,
                "document_reference": document_reference,
                "metric": metric,
                "scope_pattern": scope_pattern,
                "period_start": period_start,
                "period_end": period_end,
                "entered_by": entered_by,
                "entered_at": dt.datetime.now(UTC),
                "revoked_at": None,
                "revoked_by": None,
                "revocation_reason": None,
            }
            self.attestations[att["attestation_id"]] = att
            return FakeCursor([self._attestation_row(att)])

        if q.startswith(
            "SELECT attestation_id, statistician_name, statistician_credentials, method_description, document_reference, metric"
        ):
            # The full-column attestation SELECT (list / one).
            if "WHERE attestation_id = %s" in q:
                att = self.attestations.get(str(params[0]))
                rows = [att] if att else []
            else:
                rows = list(self.attestations.values())
                i = 0
                if "metric = %s" in q:
                    rows = [r for r in rows if r["metric"] == params[i]]
                    i += 1
                if "revoked_at IS NULL" in q:
                    rows = [r for r in rows if r["revoked_at"] is None]
                rows.sort(key=lambda r: (r["entered_at"], r["attestation_id"]))
            return FakeCursor([self._attestation_row(r) for r in rows])

        if q.startswith(
            "SELECT attestation_id, statistician_name, statistician_credentials, method_description, metric"
        ):
            # dq._SELECT_ATTESTATION_FOR_ISSUE (9 columns).
            att = self.attestations.get(str(params[0]))
            rows = (
                [
                    (
                        att["attestation_id"], att["statistician_name"],
                        att["statistician_credentials"],
                        att["method_description"], att["metric"],
                        att["scope_pattern"], att["period_start"],
                        att["period_end"], att["revoked_at"],
                    )
                ]
                if att
                else []
            )
            return FakeCursor(rows)

        if q.startswith("UPDATE cert.attestations SET revoked_at"):
            revoked_by, reason, attestation_id = params
            att = self.attestations.get(str(attestation_id))
            if att is None or att["revoked_at"] is not None:
                return FakeCursor([])
            att["revoked_at"] = dt.datetime.now(UTC)
            att["revoked_by"] = revoked_by
            att["revocation_reason"] = reason
            return FakeCursor([self._attestation_row(att)])

        # -- Map wave (handoff 0023): vehicles + geometry ---------------------
        if q.startswith("SELECT DISTINCT ON (vp.vehicle_id)"):
            # ops._SELECT_LATEST: latest row per vehicle within the window,
            # source label joined from the row's own source (the fake stores
            # it inline instead of a raw.records join).
            max_age, limit = params
            cutoff = dt.datetime.now(UTC) - dt.timedelta(seconds=max_age)
            latest: dict[str, dict] = {}
            for p in self.vehicle_positions:
                if p["time"] < cutoff:
                    continue
                held = latest.get(p["vehicle_id"])
                if held is None or p["time"] > held["time"]:
                    latest[p["vehicle_id"]] = p
            rows = [
                (
                    p["vehicle_id"], p["time"], p["latitude"], p["longitude"],
                    p["bearing"], p["speed_mps"], p["trip_id"], p["route_id"],
                    p["source_record_id"], p["source"],
                )
                for _vid, p in sorted(latest.items())
            ]
            return FakeCursor(rows[:limit])

        if q.startswith("SELECT count(DISTINCT vehicle_id)"):
            max_age = params[0]
            cutoff = dt.datetime.now(UTC) - dt.timedelta(seconds=max_age)
            vids = {
                p["vehicle_id"]
                for p in self.vehicle_positions
                if p["time"] >= cutoff
            }
            return FakeCursor([(len(vids),)])

        if q.startswith("SELECT now(), max(time) FROM canonical.vehicle_positions"):
            newest = max(
                (p["time"] for p in self.vehicle_positions), default=None
            )
            return FakeCursor([(dt.datetime.now(UTC), newest)])

        if q.startswith("SELECT stop_id, name, latitude, longitude"):
            limit = params[0]
            rows = [
                (s["stop_id"], s["name"], s["latitude"], s["longitude"])
                for s in sorted(self.stops.values(), key=lambda s: s["stop_id"])
            ]
            return FakeCursor(rows[:limit])

        if q.startswith("SELECT count(*) FROM canonical.stops"):
            return FakeCursor([(len(self.stops),)])

        if q.startswith("WITH trip_patterns AS"):
            # geometry._SELECT_ROUTE_PATTERNS, modeled honestly: per trip
            # the ordered stop ids, per route the most frequent pattern
            # (trip_count DESC, then the lexicographically first stop_ids —
            # the SQL's deterministic tie-break), joined to routes.
            limit = params[0]
            per_trip: dict[str, list] = {}
            for st in sorted(
                self.stop_times, key=lambda s: (s["trip_id"], s["stop_sequence"])
            ):
                per_trip.setdefault(st["trip_id"], []).append(st["stop_id"])
            pattern_counts: dict[tuple, int] = {}
            for trip_id, stop_ids in per_trip.items():
                trip = self.canonical_trips.get(trip_id)
                if trip is None:
                    continue  # the SQL join drops stop_times without a trip
                key = (trip["route_id"], tuple(stop_ids))
                pattern_counts[key] = pattern_counts.get(key, 0) + 1
            chosen: dict[str, tuple] = {}
            for (route_id, stop_ids), n in pattern_counts.items():
                held = chosen.get(route_id)
                if held is None or (-n, list(stop_ids)) < (-held[1], list(held[0])):
                    chosen[route_id] = (stop_ids, n)
            rows = []
            for route_id in sorted(chosen):
                route = self.canonical_routes.get(route_id)
                if route is None:
                    continue  # the SQL join requires a canonical.routes row
                stop_ids, n = chosen[route_id]
                rows.append(
                    (
                        route_id, route["short_name"], route["long_name"],
                        route["mode"], list(stop_ids), n,
                    )
                )
            return FakeCursor(rows[:limit])

        if q.startswith("SELECT count(DISTINCT route_id) FROM canonical.trips"):
            return FakeCursor(
                [(len({t["route_id"] for t in self.canonical_trips.values()}),)]
            )

        # -- sources status (handoff 0025, design point 2) --------------------
        if q.startswith("SELECT source, connector, (array_agg"):
            window_hours = params[0]
            assert params[1] == window_hours
            now = dt.datetime.now(UTC)
            cutoff = now - dt.timedelta(hours=window_hours)
            groups: dict[tuple, list[dict]] = {}
            for r in self.raw_records:
                groups.setdefault((r["source"], r["connector"]), []).append(r)
            rows = []
            for (source, connector), records in sorted(groups.items()):
                newest = max(records, key=lambda r: r["landed_at"])
                rows.append(
                    (
                        source,
                        connector,
                        newest["connector_version"],
                        len(records),
                        sum(
                            1 for r in records
                            if r["parse_status"] == "malformed"
                        ),
                        min(r["landed_at"] for r in records),
                        newest["landed_at"],
                        max(r["fetched_at"] for r in records),
                        sum(1 for r in records if r["landed_at"] >= cutoff),
                        sum(
                            1 for r in records
                            if r["parse_status"] == "malformed"
                            and r["landed_at"] >= cutoff
                        ),
                    )
                )
            return FakeCursor(rows)

        # -- calc runs (handoff 0026 / migration 0033) ------------------------
        if q.startswith(
            "SELECT run_id, requested_by, requested_at, period_start, "
            "period_end, status, started_at, finished_at, runner_pid, "
            "summary, stdout_tail FROM computed.calc_runs"
        ):
            rows = list(self.calc_runs.values())
            if "WHERE run_id = %s" in q:
                rows = [r for r in rows if r["run_id"] == str(params[0])]
            else:
                # Newest first, run_id tie-break, LIMIT — the list query.
                rows.sort(key=lambda r: (r["requested_at"], r["run_id"]))
                rows.reverse()
                rows = rows[: params[0]]
            return FakeCursor(
                [
                    (
                        r["run_id"], r["requested_by"], r["requested_at"],
                        r["period_start"], r["period_end"], r["status"],
                        r["started_at"], r["finished_at"], r["runner_pid"],
                        r["summary"], r["stdout_tail"],
                    )
                    for r in rows
                ]
            )

        if q.startswith(
            "SELECT run_id, requested_by, requested_at, period_start, "
            "period_end, status, started_at FROM computed.calc_runs "
            "WHERE status IN ('queued', 'running')"
        ):
            live = [
                r for r in self.calc_runs.values()
                if r["status"] in ("queued", "running")
            ]
            live.sort(key=lambda r: r["requested_at"], reverse=True)
            return FakeCursor(
                [
                    (
                        r["run_id"], r["requested_by"], r["requested_at"],
                        r["period_start"], r["period_end"], r["status"],
                        r["started_at"],
                    )
                    for r in live[:1]
                ]
            )

        if q.startswith("INSERT INTO computed.calc_runs"):
            requested_by, period_start, period_end = params
            # Honest model of the calc_runs_single_flight partial unique
            # index + ON CONFLICT DO NOTHING: a live row means NO row back.
            if any(
                r["status"] in ("queued", "running")
                for r in self.calc_runs.values()
            ):
                return FakeCursor([])
            assert period_start < period_end  # migration-0033 CHECK
            run = {
                "run_id": str(uuid.uuid4()),
                "requested_by": requested_by,
                "requested_at": dt.datetime.now(UTC),
                "period_start": period_start,
                "period_end": period_end,
                "status": "queued",
                "started_at": None,
                "finished_at": None,
                "runner_pid": None,
                "summary": None,
                "stdout_tail": None,
            }
            self.calc_runs[run["run_id"]] = run
            return FakeCursor([(run["run_id"], run["requested_at"])])

        if q.startswith("UPDATE computed.calc_runs SET status = 'failed'"):
            # The stale-run reconcile: failed + finished_at + summary, only
            # while the row is still live.
            summary_json, run_id = params
            run = self.calc_runs.get(str(run_id))
            if run is None or run["status"] not in ("queued", "running"):
                return FakeCursor([])
            run["status"] = "failed"
            run["finished_at"] = dt.datetime.now(UTC)
            run["summary"] = json.loads(summary_json)
            return FakeCursor([(run["run_id"],)])

        if q.startswith("UPDATE computed.calc_runs SET status = 'running'"):
            pid, run_id = params
            run = self.calc_runs.get(str(run_id))
            if run is None or run["status"] != "queued":
                return FakeCursor([])
            run["status"] = "running"
            run["started_at"] = dt.datetime.now(UTC)
            run["runner_pid"] = pid
            return FakeCursor([(run["run_id"], run["started_at"])])

        if q.startswith("UPDATE computed.calc_runs SET status = %s"):
            status, summary_json, tail, run_id = params
            # The migration-0033 CHECKs, honestly modeled: only a terminal
            # status may carry finished_at.
            assert status in ("succeeded", "refused", "failed")
            run = self.calc_runs.get(str(run_id))
            if run is None or run["status"] not in ("queued", "running"):
                return FakeCursor([])
            run["status"] = status
            run["finished_at"] = dt.datetime.now(UTC)
            run["summary"] = json.loads(summary_json)
            run["stdout_tail"] = tail
            return FakeCursor([(run["run_id"], run["finished_at"])])

        if q.startswith("SELECT count(*) FROM computed.metric_values"):
            # /metrics/history cap honesty — same filters as the row query.
            rows = list(self.metric_values.values())
            i = 0
            if "metric = %s" in q:
                rows = [r for r in rows if r["metric"] == params[i]]
                i += 1
            if "scope = %s" in q:
                rows = [r for r in rows if r["scope"] == params[i]]
                i += 1
            if "calc_version = %s" in q:
                rows = [r for r in rows if r["calc_version"] == params[i]]
                i += 1
            if "period_start >= %s" in q:
                rows = [r for r in rows if r["period_start"] >= params[i]]
                i += 1
            if "period_end <= %s" in q:
                rows = [r for r in rows if r["period_end"] <= params[i]]
                i += 1
            return FakeCursor([(len(rows),)])

        raise AssertionError(f"FakeConn has no handler for SQL: {q!r}")

    @staticmethod
    def _attestation_row(att: dict) -> tuple:
        """The routers' _COLUMNS order (routers/attestations.py)."""
        return (
            att["attestation_id"], att["statistician_name"],
            att["statistician_credentials"], att["method_description"],
            att["document_reference"], att["metric"], att["scope_pattern"],
            att["period_start"], att["period_end"], att["entered_by"],
            att["entered_at"], att["revoked_at"], att["revoked_by"],
            att["revocation_reason"],
        )

    def _latest_safety_rows(self) -> list[dict]:
        """Each event merged with its LATEST classification (classified_at,
        classification_id ordering) — the DISTINCT ON the app's SQL does."""
        rows = []
        for event in self.safety_events.values():
            latest = None
            for c in self.safety_classifications:
                if c["event_id"] != event["event_id"]:
                    continue
                if latest is None or (
                    (c["classified_at"], c["classification_id"])
                    > (latest["classified_at"], latest["classification_id"])
                ):
                    latest = c
            merged = dict(event)
            merged["classification"] = latest["classification"] if latest else None
            merged["thresholds_met"] = (
                list(latest["thresholds_met"]) if latest else None
            )
            merged["classifier_version"] = (
                latest["classifier_version"] if latest else None
            )
            merged["classified_at"] = latest["classified_at"] if latest else None
            rows.append(merged)
        return rows

    def _walk_lineage(self, root_id):
        if self._lineage_by_output is None:
            index: dict[tuple[str, str], list[dict]] = {}
            for e in self.lineage_edges:
                index.setdefault((e["output_kind"], e["output_id"]), []).append(e)
            self._lineage_by_output = index
        rows = []
        frontier = [("computed.metric_values", str(root_id))]
        seen = set()
        while frontier:
            key = frontier.pop(0)
            if key in seen:
                continue
            seen.add(key)
            for e in self._lineage_by_output.get(key, ()):
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
    def add_user(self, username, role, *, is_active=True, password_hash=None,
                 auth_source="local", idp_issuer=None, idp_subject=None):
        """Seed one account.

        Migration 0043's CHECK is modelled honestly: a federated account has
        NO password hash and MUST carry both IdP identifiers; a local account
        has a hash and neither. A test that gets this wrong fails here rather
        than passing against a fake that is more permissive than Postgres.
        """
        if auth_source == "oidc":
            assert password_hash is None
            assert idp_issuer and idp_subject
            stored_hash = None
        else:
            stored_hash = password_hash or _HASHES[username]
            assert idp_issuer is None and idp_subject is None
        self.users[username] = {
            "user_id": str(uuid.uuid4()),
            "username": username,
            "password_hash": stored_hash,
            "role": role,
            "is_active": is_active,
            "auth_source": auth_source,
            "idp_issuer": idp_issuer,
            "idp_subject": idp_subject,
            "last_login_at": None,
            "created_at": dt.datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
            + dt.timedelta(minutes=len(self.users)),
        }
        return self.users[username]

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
            "category": "ntd",  # column default (migration 0024)
        }
        mv.update(overrides)
        self.metric_values[mv["metric_value_id"]] = mv
        return mv

    def add_service_day_override(self, service_date, *, assigned_day_type=None,
                                 atypical=False, reason="declared for test",
                                 updated_by="certifier"):
        """Seed an app.service_day_overrides row (handoff 0020)."""
        row = {
            "service_date": service_date,
            "assigned_day_type": assigned_day_type,
            "atypical": atypical,
            "reason": reason,
            "updated_by": updated_by,
            "updated_at": dt.datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        }
        self.service_day_overrides[service_date.isoformat()] = row
        return row

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
            "category": "ntd",  # column default (migration 0024)
            # Migration 0035 (handoff 0029). NULL by default on purpose:
            # every issue in the live queue predates the column, so the
            # default fixture IS the graceful-degradation case.
            "subject_context": None,
        }
        issue.update(overrides)
        self.dq_issues[issue["issue_id"]] = issue
        return issue

    # -- revenue review queue seeder (handoff 0040 / migration 0040) --------
    def add_boarding_review(self, **overrides):
        """Seed one dq.boarding_revenue_reviews row — a no-run boarding the
        calculation held out of the figure pending a human decision.

        Pending by default (all four human columns NULL), because pending IS
        the queue: a classified row is what a test creates deliberately.
        """
        review = {
            "passenger_event_id": f"pe-{uuid.uuid4()}",
            "source_record_id": "c" * 64,
            "service_date": dt.date(2026, 7, 9),
            "event_timestamp": dt.datetime(2026, 7, 9, 15, 12, tzinfo=UTC),
            "vehicle_id": "3684",
            "event_count": 4,
            "suggested_verdict": "pending_review",
            "suggested_reason": (
                "no run assignment but WITHIN the day's revenue-service "
                "window — ambiguous (could be a catch-up bus dispatched "
                "without a formal trip assignment); held pending human "
                "review, never counted or excluded silently"
            ),
            "calc_name": "upt_v0",
            "calc_version": "0.4.0",
            "period_start": dt.date(2026, 7, 1),
            "period_end": dt.date(2026, 8, 1),
            "first_seen_at": dt.datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
            "verdict": None,
            "justification": None,
            "classified_by": None,
            "classified_at": None,
            "dq_issue_id": None,
        }
        review.update(overrides)
        self.boarding_reviews[review["passenger_event_id"]] = review
        return review

    # -- Map wave seeders (handoff 0023) ------------------------------------
    def add_vehicle_position(self, **overrides):
        """Seed one canonical.vehicle_positions row (+ its raw source label,
        which the real query joins from raw.records)."""
        p = {
            "time": dt.datetime.now(UTC),
            "vehicle_id": "bus-1701",
            "trip_id": None,     # nullable by design — never guessed
            "route_id": None,
            "latitude": 42.3601,
            "longitude": -71.0589,
            "bearing": None,
            "speed_mps": None,
            "source_record_id": "a" * 64,
            "source": "gtfs_rt_vehicle_positions",
        }
        p.update(overrides)
        self.vehicle_positions.append(p)
        return p

    def add_raw_record(self, **overrides):
        """Seed one raw.records registry row (handoff 0025 sources status;
        the full column set the inspector reads, handoff 0035)."""
        now = dt.datetime.now(UTC)
        r = {
            "record_id": uuid.uuid4().hex * 2,  # 64 hex chars, like sha256
            "source": "gtfs_rt",
            "connector": "headway-gtfs-rt",
            "connector_version": "0.1.0",
            "content_type": "application/x-protobuf",
            "payload_encoding": "base64",
            "payload_ref": None,
            "parse_status": "ok",
            "parse_error": None,
            "fetched_at": now,
            "landed_at": now,
        }
        r.update(overrides)
        self.raw_records.append(r)
        return r

    def add_stop(self, stop_id, name="Test Stop", latitude=42.36,
                 longitude=-71.06):
        """Seed one canonical.stops row. Pass latitude/longitude None for a
        coordinate-less stop (legal per GTFS; preserved, never invented)."""
        self.stops[stop_id] = {
            "stop_id": stop_id,
            "name": name,
            "latitude": latitude,
            "longitude": longitude,
        }
        return self.stops[stop_id]

    def add_canonical_route(self, route_id, short_name=None, long_name=None,
                            mode="bus"):
        self.canonical_routes[route_id] = {
            "route_id": route_id,
            "short_name": short_name,
            "long_name": long_name,
            "mode": mode,
        }
        return self.canonical_routes[route_id]

    def add_canonical_trip(self, trip_id, route_id):
        self.canonical_trips[trip_id] = {
            "trip_id": trip_id,
            "route_id": route_id,
        }
        return self.canonical_trips[trip_id]

    def add_trip_stops(self, trip_id, stop_ids):
        """Seed the ordered canonical.stop_times rows for one trip."""
        for seq, stop_id in enumerate(stop_ids, start=1):
            self.stop_times.append(
                {"trip_id": trip_id, "stop_id": stop_id, "stop_sequence": seq}
            )

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
        # Themed chrome keys (migration 0027, handoff 0017 design point 7).
        for key in (
            "brand_chrome_header_bg",
            "brand_chrome_header_fg",
            "brand_chrome_accent",
        ):
            self.add_setting(
                key, "unset", "text",
                description=(
                    "Themed chrome (branding v2). GUARDRAIL: chrome pairs "
                    "that fail accessibility contrast are refused (WCAG "
                    "2.1 AA, 4.5:1)."
                ),
                updated_by="migration:0027",
            )

    def add_safety_event(self, **overrides):
        """Seed one safety.events row (handoff 0010 / migration 0017)."""
        event = {
            "event_id": str(uuid.uuid4()),
            "occurred_at": dt.datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
            "mode": "bus",
            "type_of_service": "DO",
            "event_category": "other",
            "narrative": "Seeded safety event.",
            "location": None,
            "fatalities": 0,
            "injuries": 0,
            "property_damage_usd": None,
            "serious_injury": False,
            "substantial_damage": False,
            "towed": False,
            "evacuation_life_safety": False,
            "assault_on_worker": False,
            "involves_transit_vehicle": False,
            "involves_second_rail_vehicle": False,
            "grade_crossing": False,
            "runaway_train": False,
            "evacuation_to_rail_row": False,
            "entered_by": "stella",
            "entered_at": dt.datetime(2026, 6, 10, 13, 0, tzinfo=UTC),
            "superseded_by": None,
        }
        event.update(overrides)
        self.safety_events[event["event_id"]] = event
        return event

    def add_sampling_plan(self, **overrides):
        """Seed one sampling.plans row (handoff 0012 / migration 0020).
        Defaults: DR / APTL / quarterly — Table 43.01 cell (12, 48)."""
        plan = {
            "plan_id": str(uuid.uuid4()),
            "report_year": 2026,
            "mode": "DR",
            "type_of_service": "DO",
            "unit": "vehicle_days",
            "efficiency_option": "aptl",
            "frequency": "quarterly",
            "required_per_period": 12,
            "required_annual": 48,
            "table_citation": (
                "Table 43.01. Ready-to-Use Sampling Plans for Non-Scheduled "
                "Services (p. 4), 'Reporting 100% UPT (APTL Option)': "
                "Vehicle days for a Quarter = 12; Total Sample Size for "
                "Year = 48. (seeded fixture)"
            ),
            "selector_version": "sampling_v0 0.1.0",
            "status": "created",
            "created_by": "stella",
            "created_at": dt.datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
        }
        plan.update(overrides)
        self.sampling_plans[plan["plan_id"]] = plan
        return plan

    def add_sampling_draw(self, plan_id, *, period_label="2026-Q1",
                          service_units=None, selected_units=None,
                          seed="seeded-fixture-seed", seed_source="generated",
                          oversample_units=0):
        # seed_source=None seeds a pre-migration-0022 row (provenance
        # honestly unknown; the column is nullable for exactly that case).
        draw = {
            "draw_id": str(uuid.uuid4()),
            "plan_id": str(plan_id),
            "period_label": period_label,
            "service_units": list(service_units or []),
            "selected_units": list(selected_units or []),
            "seed": seed,
            "seed_source": seed_source,
            "oversample_units": oversample_units,
            "drawer_version": "sampling_v0 0.1.0",
            "drawn_by": "stella",
            "drawn_at": dt.datetime.now(UTC),
        }
        self.sampling_draws.append(draw)
        return draw

    def add_sampling_measurement(self, plan_id, unit_id, *, observed_upt=10,
                                 observed_pmt="40", service_day_type=None):
        m = {
            "measurement_id": str(uuid.uuid4()),
            "plan_id": str(plan_id),
            "unit_id": unit_id,
            "observed_upt": observed_upt,
            "observed_pmt": Decimal(observed_pmt),
            "service_day_type": service_day_type,
            "service_date": None,
            "data_source": "manual_ride_check",
            "notes": None,
            "entered_by": "stella",
            "entered_at": dt.datetime.now(UTC),
            "superseded_by": None,
        }
        self.sampling_measurements[m["measurement_id"]] = m
        return m

    def add_safety_classification(self, event_id, classification="non_major",
                                  thresholds_met=(), classified_at=None,
                                  classifier_version="sscls_v0 0.1.1"):
        row = {
            "classification_id": self._next_classification_id,
            "event_id": str(event_id),
            "classification": classification,
            "thresholds_met": list(thresholds_met),
            "classifier_version": classifier_version,
            "classified_at": classified_at or dt.datetime.now(UTC),
        }
        self._next_classification_id += 1
        self.safety_classifications.append(row)
        return row

    def add_attestation(self, **overrides):
        """Seed one cert.attestations row (handoff 0019 / migration 0029)."""
        att = {
            "attestation_id": str(uuid.uuid4()),
            "statistician_name": "Dr. R. Fisher",
            "statistician_credentials": "PhD statistics",
            "method_description": "Route-stratified expansion factoring",
            "document_reference": "dms://approvals/2026/factoring.pdf",
            "metric": "upt",
            "scope_pattern": "agency",
            "period_start": dt.date(2026, 6, 1),
            "period_end": dt.date(2026, 7, 1),
            "entered_by": "cora",
            "entered_at": dt.datetime(2026, 7, 2, 9, 0, tzinfo=UTC),
            "revoked_at": None,
            "revoked_by": None,
            "revocation_reason": None,
        }
        att.update(overrides)
        self.attestations[att["attestation_id"]] = att
        return att

    def add_calc_run(self, **overrides):
        """Seed one computed.calc_runs row (handoff 0026 / migration 0033)."""
        run = {
            "run_id": str(uuid.uuid4()),
            "requested_by": "stella",
            "requested_at": dt.datetime.now(UTC),
            "period_start": dt.date(2026, 6, 1),
            "period_end": dt.date(2026, 7, 1),
            "status": "queued",
            "started_at": None,
            "finished_at": None,
            "runner_pid": None,
            "summary": None,
            "stdout_tail": None,
        }
        run.update(overrides)
        self.calc_runs[run["run_id"]] = run
        return run

    def add_edge(self, output_kind, output_id, transform_name, transform_version,
                 input_kind, input_id):
        self._lineage_by_output = None
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

    def delete(self, key):
        """Idempotent, like S3 remove_object (routers/branding.py DELETE)."""
        self.call_log.append(("store.delete", key))
        self.objects.pop(key, None)

    # -- raw-record inspector seams (handoff 0035), mirroring MinioObjectStore
    def stat(self, key):
        """Size without reading, None when the object is not there."""
        self.call_log.append(("store.stat", key))
        data = self.objects.get(key)
        return None if data is None else len(data)

    def stream(self, key, chunk_size=1024 * 1024):
        self.call_log.append(("store.stream", key))
        data = self.objects.get(key)
        if data is None:
            return None, None
        chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]
        return len(data), iter(chunks or [b""])


class FakeProducer:
    def __init__(self, call_log=None):
        self.produced: list[tuple[str, bytes, bytes]] = []
        self.call_log = call_log if call_log is not None else []

    def produce(self, topic, key, value):
        self.call_log.append(("producer.produce", topic, key))
        self.produced.append((topic, key, value))


class FakeEnvelopeStream:
    """Stands in for the broker in the raw-record inspector (handoff 0035).

    GTFS-Realtime payloads are never written to the object store: the
    connector base64-encodes the exact bytes into the ingest envelope and
    produces it keyed by record_id (contracts/topics.v0.md), so the broker
    is the only place those bytes exist. This fake replaces ONLY the bounded
    topic lookup — the routing, the hashing and the decoding under test are
    the real ones. A record_id absent from ``messages`` reproduces the real
    "the broker no longer retains that message" path.
    """

    def __init__(self):
        self.messages: dict[str, bytes] = {}
        self.lookups: list[tuple[str, tuple]] = []

    def __call__(self, record, topics):
        self.lookups.append((record.record_id, tuple(topics)))
        return self.messages.get(record.record_id)


class FakeCalcRunLauncher:
    """Records calc-run launches (handoff 0026) instead of spawning a real
    subprocess thread. Tests drive routers.calc_runs.execute_run directly
    (with a fake spawn) to exercise the lifecycle synchronously."""

    def __init__(self):
        self.launched: list[tuple[str, dt.date, dt.date]] = []

    def __call__(self, run_id, period_start, period_end):
        self.launched.append((run_id, period_start, period_end))


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



# ---------------------------------------------------------------------------
# A fake identity provider with REAL cryptography (handoff 0046)
# ---------------------------------------------------------------------------
#
# The point of this fake is that almost nothing about it is fake. It holds
# real RSA keys, publishes a real JWKS, and mints real RS256-signed ID
# tokens, so every assertion about signature verification, algorithm
# allow-listing and key rotation exercises the production verifier rather
# than a stub that agrees with it. What is faked is only the transport: no
# socket is opened.
#
# Its token endpoint verifies PKCE for real (S256 over the stored challenge)
# and checks the client credentials, so a test that breaks PKCE or the client
# secret fails HERE, the way a provider would fail it.

_RSA_KEYS: dict[str, object] = {}


def _rsa_key(name: str):
    """RSA keys are expensive to generate; make each one once per session."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    if name not in _RSA_KEYS:
        _RSA_KEYS[name] = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
    return _RSA_KEYS[name]


def _jwk_from_rsa(private_key, kid: str) -> dict:
    import base64 as _b64

    numbers = private_key.public_key().public_numbers()

    def b64u(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return _b64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": b64u(numbers.n),
        "e": b64u(numbers.e),
    }


class FakeIdentityProvider:
    """A standards-shaped OIDC provider: discovery, JWKS, token endpoint."""

    def __init__(
        self,
        issuer="https://idp.example.gov/realms/agency",
        client_id="headway-api",
        client_secret="provider-issued-client-secret",
    ):
        self.issuer = issuer
        self.client_id = client_id
        self.client_secret = client_secret
        self.discovery_url = issuer + "/.well-known/openid-configuration"
        self.jwks_uri = issuer + "/protocol/openid-connect/certs"
        self.token_endpoint = issuer + "/protocol/openid-connect/token"
        self.authorization_endpoint = issuer + "/protocol/openid-connect/auth"
        self.signing_kid = "key-2026-a"
        self._published_kids = [self.signing_kid]
        self.codes: dict[str, dict] = {}
        self.token_calls: list[dict] = []
        self.jwks_fetches = 0
        self.discovery_fetches = 0
        #: Set to a JSON error body to make the token endpoint refuse.
        self.token_error: tuple[int, dict] | None = None

    # -- keys ------------------------------------------------------------
    def rotate_signing_key(self, kid="key-2026-b", *, publish=True):
        """Start signing with a NEW key. When ``publish`` is true the new key
        is added to the JWKS, which is exactly what a provider does — and
        what a relying party with a pinned key cannot survive."""
        self.signing_kid = kid
        if publish and kid not in self._published_kids:
            self._published_kids.append(kid)

    def jwks(self) -> dict:
        self.jwks_fetches += 1
        return {
            "keys": [_jwk_from_rsa(_rsa_key(kid), kid) for kid in self._published_kids]
        }

    def discovery(self) -> dict:
        self.discovery_fetches += 1
        return {
            "issuer": self.issuer,
            "authorization_endpoint": self.authorization_endpoint,
            "token_endpoint": self.token_endpoint,
            "jwks_uri": self.jwks_uri,
            "code_challenge_methods_supported": ["S256", "plain"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_basic", "client_secret_post"
            ],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    # -- the browser hop, without a browser --------------------------------
    def authorize(self, authorization_url: str) -> str:
        """Play the part of the user consenting. Records the nonce and the
        PKCE challenge exactly as a provider would, and returns the code."""
        from urllib.parse import parse_qs, urlparse

        params = parse_qs(urlparse(authorization_url).query)
        assert params["response_type"] == ["code"], "implicit flow must never be used"
        assert params["code_challenge_method"] == ["S256"]
        code = "code-" + uuid.uuid4().hex
        self.codes[code] = {
            "nonce": params["nonce"][0],
            "code_challenge": params["code_challenge"][0],
            "redirect_uri": params["redirect_uri"][0],
            "used": False,
        }
        return code

    # -- ID tokens ---------------------------------------------------------
    def id_token(self, *, sub="idp-subject-0001", nonce, username="sso.steward",
                 groups=("transit-data-stewards",), kid=None, **overrides) -> str:
        import jwt as _jwt

        now = dt.datetime.now(UTC)
        claims = {
            "iss": self.issuer,
            "sub": sub,
            "aud": self.client_id,
            "exp": int((now + dt.timedelta(minutes=5)).timestamp()),
            "iat": int(now.timestamp()),
            "nonce": nonce,
            "preferred_username": username,
            "email": f"{username}@example.gov",
            "groups": list(groups),
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not _ABSENT}
        kid = kid or self.signing_kid
        alg = overrides.pop("_alg", "RS256")
        return _jwt.encode(
            claims, _rsa_key(kid), algorithm=alg, headers={"kid": kid}
        )

    def token_response(self, code: str, code_verifier: str) -> dict:
        record = self.codes[code]
        # PKCE, verified for real.
        import base64 as _b64
        import hashlib as _hashlib

        expected = _b64.urlsafe_b64encode(
            _hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        assert expected == record["code_challenge"], "PKCE verifier did not match"
        record["used"] = True
        return {
            "access_token": "provider-access-token",
            "token_type": "Bearer",
            "id_token": self.id_token(nonce=record["nonce"], **record.get("claims", {})),
        }


class _Absent:
    def __repr__(self):
        return "<absent>"


#: Pass as a claim value to OMIT that claim entirely (as opposed to setting
#: it to null, which is a different test).
_ABSENT = _Absent()
ABSENT = _ABSENT


class FakeOidcHttp:
    """The transport seam. Serves the fake provider's documents; refuses any
    other address the way the real client would."""

    def __init__(self, idp: FakeIdentityProvider, ca_bundle_path=None):
        self.idp = idp
        self.ca_bundle_path = ca_bundle_path
        self.requested: list[str] = []

    def get_json(self, url: str) -> dict:
        from headway_api.oidc import OidcConfigurationError

        self.requested.append(url)
        if url == self.idp.discovery_url:
            return self.idp.discovery()
        if url == self.idp.jwks_uri:
            return self.idp.jwks()
        raise OidcConfigurationError(
            f"Headway could not reach {url} (ConnectError). Check that the "
            f"Headway server can reach your identity provider."
        )

    def _check_client(self, data, auth):
        secret = None
        if auth is not None:
            client_id, secret = auth
        else:
            client_id = data.get("client_id")
            secret = data.get("client_secret")
        if client_id != self.idp.client_id or secret != self.idp.client_secret:
            return {"error": "invalid_client"}
        return None

    def post_form(self, url: str, data: dict, *, auth=None) -> dict:
        from headway_api.oidc import OidcError

        self.requested.append(url)
        self.idp.token_calls.append({"data": dict(data), "auth": auth})
        if self.idp.token_error is not None:
            status, body = self.idp.token_error
            raise OidcError(
                f"token endpoint refused the code exchange: HTTP {status} "
                f"{body.get('error', 'unknown_error')}"
            )
        bad = self._check_client(data, auth)
        if bad is not None:
            raise OidcError("token endpoint refused the code exchange: HTTP 401 invalid_client")
        record = self.idp.codes.get(data.get("code"))
        if record is None or record["used"]:
            raise OidcError("token endpoint refused the code exchange: HTTP 400 invalid_grant")
        return self.idp.token_response(data["code"], data["code_verifier"])

    def post_form_probe(self, url: str, data: dict, *, auth=None):
        self.requested.append(url)
        self.idp.token_calls.append({"data": dict(data), "auth": auth, "probe": True})
        bad = self._check_client(data, auth)
        if bad is not None:
            return 401, bad
        # A made-up code, refused after the credentials were accepted —
        # exactly what the admin test action reads as a pass.
        return 400, {"error": "invalid_grant"}


@pytest.fixture
def fake_db():
    db = FakeConn()
    db.add_user("vera", "viewer")
    db.add_user("stella", "data_steward")
    db.add_user("petra", "report_preparer")
    db.add_user("cora", "certifying_official")
    db.add_user("dora", "viewer", is_active=False)
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
def test_signer():
    return signing.load_signer({signing.ENV_KEY: TEST_SIGNING_SEED_HEX})


@pytest.fixture
def fake_calc_launcher():
    return FakeCalcRunLauncher()


@pytest.fixture
def fake_envelope_stream():
    return FakeEnvelopeStream()


@pytest.fixture
def fake_payload_reader(fake_store, fake_envelope_stream):
    """The REAL composite reader over a fake store and a fake broker
    (handoff 0035): routing by payload_encoding, streaming reads, hashing
    and decoding are all the production code paths."""
    return raw_payloads.CompositeRawPayloadReader(
        raw_payloads.ObjectStorePayloadReader(fake_store),
        raw_payloads.EnvelopeStreamPayloadReader(fake_envelope_stream),
    )


@pytest.fixture
def app(fake_db, settings, fake_store, fake_producer, fake_webhook_sender,
        test_signer, fake_calc_launcher, fake_payload_reader, oidc_metadata):
    application = create_app(
        settings=settings,
        db=fake_db,
        object_store=fake_store,
        producer=fake_producer,
        webhook_sender=fake_webhook_sender,
        calc_run_launcher=fake_calc_launcher,
        raw_payload_reader=fake_payload_reader,
        oidc_metadata=oidc_metadata,
    )
    # The at-rest encryption key for configuration secrets (handoff 0046),
    # injected like every other external seam.
    application.state.secret_key = TEST_SECRET_ENCRYPTION_KEY
    # The installation signing key (handoff 0019), injected like every other
    # external seam — signing.get_signer serves this cached instance.
    application.state.signer = test_signer
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c



@pytest.fixture
def fake_idp():
    """A standards-shaped identity provider with real RSA keys."""
    return FakeIdentityProvider()


@pytest.fixture
def fake_oidc_http(fake_idp):
    return FakeOidcHttp(fake_idp)


@pytest.fixture
def oidc_metadata(fake_idp, fake_oidc_http):
    """The REAL discovery/JWKS cache over a fake transport: caching, TTLs,
    rotation-on-unknown-kid and the refresh rate limit are all production
    code paths in every test that touches sign-in."""
    from headway_api.oidc import ProviderMetadata

    return ProviderMetadata(http_factory=lambda ca: fake_oidc_http)


#: Deterministic AES-256 key for the at-rest encryption of configuration
#: secrets — NEVER a production key.
TEST_SECRET_ENCRYPTION_KEY = bytes.fromhex("cd" * 32)


def configure_sso(db: FakeConn, idp: FakeIdentityProvider, *, enabled=True,
                  client_secret=None, groups_claim="groups",
                  clock_skew_seconds=120, ca_bundle_path=None):
    """Seed a provider configuration, with the client secret encrypted at
    rest by the production code path."""
    from headway_api import secrets_at_rest

    secret = idp.client_secret if client_secret is None else client_secret
    db.oidc_provider = {
        "discovery_url": idp.discovery_url,
        "client_id": idp.client_id,
        "client_secret_encrypted": (
            secrets_at_rest.encrypt(
                secret,
                associated_data=secrets_at_rest.AD_OIDC_CLIENT_SECRET,
                key=TEST_SECRET_ENCRYPTION_KEY,
            )
            if secret
            else None
        ),
        "redirect_uri": "https://headway.example.gov/auth/callback",
        "groups_claim": groups_claim,
        "username_claim": "preferred_username",
        "clock_skew_seconds": clock_skew_seconds,
        "ca_bundle_path": ca_bundle_path,
        "button_label": "Sign in with County SSO",
        "is_enabled": enabled,
        "updated_by": "cora",
        "updated_at": dt.datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
    }


def map_claim(db: FakeConn, claim_value: str, role: str, *, created_by="cora"):
    mapping_id = str(uuid.uuid4())
    db.oidc_role_mappings[mapping_id] = {
        "mapping_id": mapping_id,
        "claim_value": claim_value,
        "headway_role": role,
        "note": None,
        "created_by": created_by,
        "created_at": dt.datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
    }
    return mapping_id


def sso_sign_in(client, idp: FakeIdentityProvider, **id_token_claims):
    """Drive a whole authorization-code + PKCE sign-in through the API.

    Returns the callback response. ``id_token_claims`` are applied to the ID
    token the provider mints, so a test can bend exactly one thing (a wrong
    audience, a stale nonce, an unmapped group) and leave the rest genuine.
    """
    started = client.post("/auth/oidc/start")
    assert started.status_code == 200, started.text
    body = started.json()
    code = idp.authorize(body["authorization_url"])
    idp.codes[code]["claims"] = id_token_claims
    return client.post(
        "/auth/oidc/callback",
        json={
            "code": code,
            "state": body["state"],
            "browser_token": body["browser_token"],
        },
    )


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


def add_auditor(db: FakeConn, username: str = "audra"):
    """Seed an auditor account (handoff 0046). It gets a real bcrypt hash so
    it is an ordinary LOCAL account in every respect but its role — the
    read-only behaviour must come from the role, never from how it signs in."""
    return db.add_user(username, "auditor", password_hash=_HASHES["vera"])


def machine_header(full_key: str) -> dict:
    return {"Authorization": f"Bearer {full_key}"}
