"""POST /sandbox/preview (handoff 0017, design point 6): the what-if
modeling preview — read-only, ephemeral, never certifiable.

The calc-level no-write guarantee is pinned in services/calc
(tests/test_preview.py: zero INSERTs, zero commits). Here we pin the API
composition: knob validation (unknown knobs and unparseable values refused
in plain language), NTD/ops section routing, exact deltas, the changes-
nothing banner + persisted=false, the pointer at the audited settings flow,
and THE ATTACK: after a preview, nothing new exists in metric values or DQ
issues, and certifying a preview 'result' is impossible because previews
have no id — plus the certify route's standing ops refusal for anything the
REAL ops runner persists (the migration-0024 wall, proven live by psql
attack in handoff 0017's evidence)."""

import datetime as dt

from conftest import auth_header

from headway_api.routers import sandbox

PERIOD = {"period_start": "2026-07-09", "period_end": "2026-07-10"}


def _fake_ntd_report():
    return {
        "persisted": False,
        "period_start": "2026-07-09",
        "period_end": "2026-07-10",
        "period_convention": "half-open [period_start, period_end), UTC",
        "positions_loaded": 100,
        "passenger_events_loaded": 50,
        "operated_trips_loaded": 10,
        "stop_times_loaded": 40,
        "variants": [
            {
                "label": "baseline",
                "thresholds": {"coverage_threshold": "0.95"},
                "threshold_sources": {"coverage_threshold": "settings"},
                "outcomes": [
                    {
                        "calc_name": "vrm_v0", "calc_version": "0.2.0",
                        "metric": "vrm", "unit": "miles", "scope": "agency",
                        "value": None, "blocked": True, "detail": None,
                        "findings": [
                            {
                                "issue_type": "coverage_below_threshold",
                                "severity": "blocking",
                                "title": "Coverage 0.67 below 0.95",
                            }
                        ],
                    }
                ],
            },
            {
                "label": "proposed",
                "thresholds": {"coverage_threshold": "0.60"},
                "threshold_sources": {"coverage_threshold": "explicit"},
                "outcomes": [
                    {
                        "calc_name": "vrm_v0", "calc_version": "0.2.0",
                        "metric": "vrm", "unit": "miles", "scope": "agency",
                        "value": "12794.92", "blocked": False,
                        "detail": {"coverage": "0.6667"},
                        "findings": [],
                    }
                ],
            },
        ],
    }


def _fake_ops_report():
    return {
        "persisted": False,
        "category": "ops",
        "period_start": "2026-07-09",
        "period_end": "2026-07-10",
        "period_convention": "half-open [period_start, period_end), UTC",
        "positions_loaded": 100,
        "schedule_rows_loaded": 500,
        "passages_derived": 200,
        "derivation": {"considered": 300, "derived": 200},
        "variants": [
            {
                "label": "baseline",
                "thresholds": {
                    "otp_early_tolerance_seconds": "60",
                    "otp_late_tolerance_seconds": "300",
                },
                "threshold_sources": {
                    "otp_early_tolerance_seconds": "settings",
                    "otp_late_tolerance_seconds": "settings",
                },
                "outcomes": [
                    {
                        "calc_name": "otp_v0", "calc_version": "0.1.0",
                        "metric": "otp", "unit": "percent", "scope": "agency",
                        "value": "54.10", "blocked": False,
                        "detail": None, "findings": [],
                    }
                ],
            },
            {
                "label": "proposed",
                "thresholds": {
                    "otp_early_tolerance_seconds": "60",
                    "otp_late_tolerance_seconds": "600",
                },
                "threshold_sources": {
                    "otp_early_tolerance_seconds": "settings",
                    "otp_late_tolerance_seconds": "explicit",
                },
                "outcomes": [
                    {
                        "calc_name": "otp_v0", "calc_version": "0.1.0",
                        "metric": "otp", "unit": "percent", "scope": "agency",
                        "value": "61.30", "blocked": False,
                        "detail": None, "findings": [],
                    }
                ],
            },
        ],
    }


class _Report:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return self._payload


def _patch_previews(monkeypatch, ntd=None, ops=None):
    calls = {"ntd": [], "ops": []}

    def fake_preview(conn, start, end, variants, read_settings=True):
        calls["ntd"].append((start, end, variants))
        return _Report(ntd or _fake_ntd_report())

    def fake_ops_preview(conn, start, end, variants, read_settings=True):
        calls["ops"].append((start, end, variants))
        return _Report(ops or _fake_ops_report())

    monkeypatch.setattr(sandbox.calc_runner, "preview_period", fake_preview)
    monkeypatch.setattr(
        sandbox.calc_runner, "preview_ops_period", fake_ops_preview
    )
    return calls


def _preview(client, fake_db, proposed, username="vera"):
    return client.post(
        "/sandbox/preview",
        json={**PERIOD, "proposed": proposed},
        headers=auth_header(fake_db, username),
    )


def test_ntd_preview_banner_deltas_and_changes_nothing(
    client, fake_db, monkeypatch
):
    calls = _patch_previews(monkeypatch)
    values_before = dict(fake_db.metric_values)
    issues_before = dict(fake_db.dq_issues)
    r = _preview(client, fake_db, {"coverage_threshold": "0.60"})
    assert r.status_code == 200
    body = r.json()
    assert body["persisted"] is False
    assert "changes nothing" in body["banner"]
    assert "PUT /settings/{key}" in body["settings_flow_note"]
    assert body["ops"] is None
    section = body["ntd"]
    assert section["baseline_threshold_sources"]["coverage_threshold"] == (
        "settings"
    )
    (impact,) = section["metrics"]
    assert impact["metric"] == "vrm"
    assert impact["category"] == "ntd"
    # The baseline refused (blocking finding surfaced, not routed); the
    # proposed value stands; no delta across a refusal.
    assert impact["baseline"]["blocked"] is True
    assert impact["baseline"]["findings"][0]["severity"] == "blocking"
    assert impact["proposed"]["value"] == "12794.92"
    assert impact["delta"] is None
    # THE WALL, API side: the preview changed NOTHING.
    assert fake_db.metric_values == values_before
    assert fake_db.dq_issues == issues_before
    assert fake_db.audit_events == []
    # Only the NTD preview ran; the proposed variant carried only the
    # proposed knob.
    assert len(calls["ntd"]) == 1 and calls["ops"] == []
    _, _, variants = calls["ntd"][0]
    assert variants[1].coverage_threshold == "0.60"
    assert variants[1].gap_threshold_seconds is None


def test_ops_preview_delta_is_exact(client, fake_db, monkeypatch):
    _patch_previews(monkeypatch)
    r = _preview(client, fake_db, {"otp_late_tolerance_seconds": "600"})
    body = r.json()
    assert body["ntd"] is None
    (impact,) = body["ops"]["metrics"]
    assert impact["category"] == "ops"
    assert impact["delta"] == "7.20"  # 61.30 - 54.10, exactly
    assert body["ops"]["derivation"]["derived"] == 200


def test_mixed_knobs_produce_both_sections(client, fake_db, monkeypatch):
    calls = _patch_previews(monkeypatch)
    r = _preview(
        client,
        fake_db,
        {
            "coverage_threshold": "0.90",
            "otp_late_tolerance_seconds": "600",
        },
    )
    body = r.json()
    assert body["ntd"] is not None and body["ops"] is not None
    assert len(calls["ntd"]) == 1 and len(calls["ops"]) == 1


def test_unknown_knob_refused_naming_the_valid_set(client, fake_db, monkeypatch):
    calls = _patch_previews(monkeypatch)
    r = _preview(client, fake_db, {"imbalance_threshold": "0.2"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "imbalance_threshold is not a policy knob" in detail
    assert "coverage_threshold" in detail
    assert calls["ntd"] == [] and calls["ops"] == []


def test_unparseable_values_refused_plain_language(client, fake_db, monkeypatch):
    _patch_previews(monkeypatch)
    r = _preview(client, fake_db, {"coverage_threshold": "high"})
    assert r.status_code == 422
    assert "not a decimal number" in r.json()["detail"]
    r = _preview(client, fake_db, {"layover_max_seconds": "half an hour"})
    assert r.status_code == 422
    assert "not a whole number" in r.json()["detail"]


def test_bad_period_and_empty_proposed_refused(client, fake_db, monkeypatch):
    _patch_previews(monkeypatch)
    r = client.post(
        "/sandbox/preview",
        json={
            "period_start": "2026-07-10",
            "period_end": "2026-07-09",
            "proposed": {"coverage_threshold": "0.9"},
        },
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 422
    assert "half-open" in r.json()["detail"]
    r = client.post(
        "/sandbox/preview",
        json={**PERIOD, "proposed": {}},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 422  # pydantic min_length=1


def test_broken_settings_table_refuses_503(client, fake_db, monkeypatch):
    from headway_calc.settings import MissingSettingError

    def broken(conn, start, end, variants, read_settings=True):
        raise MissingSettingError("app.settings exists but is missing knobs")

    monkeypatch.setattr(sandbox.calc_runner, "preview_period", broken)
    r = _preview(client, fake_db, {"coverage_threshold": "0.9"})
    assert r.status_code == 503
    assert "app.settings" in r.json()["detail"]


def test_preview_requires_authentication(client):
    r = client.post(
        "/sandbox/preview",
        json={**PERIOD, "proposed": {"coverage_threshold": "0.9"}},
    )
    assert r.status_code == 401


def test_attack_preview_results_cannot_be_certified(client, fake_db, monkeypatch):
    """A preview yields NO metric_value_id (nothing was persisted), so there
    is nothing to certify: certifying any fabricated id 404s, and the ops
    category (which the REAL ops runner persists under) is refused by the
    certify route + the migration-0024 CHECK (proven live by attack)."""
    _patch_previews(monkeypatch)
    r = _preview(client, fake_db, {"coverage_threshold": "0.60"})
    assert r.status_code == 200
    # No new rows exist to point a certification at.
    assert fake_db.metric_values == {}
    fabricated = "00000000-0000-0000-0000-00000000beef"
    r = client.post(
        "/certifications",
        json={"metric_value_ids": [fabricated], "attestation": "attempt"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 404
    assert fake_db.certifications == []
