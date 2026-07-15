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

from headway_api import auth, machine_auth, signing  # noqa: E402
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

        if "FROM auth.users WHERE username" in q:
            u = self.users.get(params[0])
            rows = (
                [(u["user_id"], u["username"], u["password_hash"], u["role"], u["disabled"])]
                if u
                else []
            )
            return FakeCursor(rows)

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
            if "period_start >= %s" in q:
                rows = [r for r in rows if r["period_start"] >= params[i]]
                i += 1
            if "period_end <= %s" in q:
                rows = [r for r in rows if r["period_end"] <= params[i]]
                i += 1
            if "category = %s" in q:
                rows = [r for r in rows if r["category"] == params[i]]
                i += 1
            rows.sort(key=lambda r: (r["period_start"], r["metric"]))
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
            "category": "ntd",  # column default (migration 0024)
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
            "category": "ntd",  # column default (migration 0024)
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
def test_signer():
    return signing.load_signer({signing.ENV_KEY: TEST_SIGNING_SEED_HEX})


@pytest.fixture
def app(fake_db, settings, fake_store, fake_producer, fake_webhook_sender,
        test_signer):
    application = create_app(
        settings=settings,
        db=fake_db,
        object_store=fake_store,
        producer=fake_producer,
        webhook_sender=fake_webhook_sender,
    )
    # The installation signing key (handoff 0019), injected like every other
    # external seam — signing.get_signer serves this cached instance.
    application.state.signer = test_signer
    return application


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
