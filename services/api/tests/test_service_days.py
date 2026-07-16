"""Service-day overrides (handoff 0020, migration 0031): the audited
day-type calendar surface — any signed-in role reads, only the certifying
official writes, declarations validated (vocabulary, meaningfulness,
required reason), old→new in the audit detail."""

import datetime as dt
import json

from conftest import auth_header

JULY_3 = "2026-07-03"


def _put(client, fake_db, username="cora", date=JULY_3, **body):
    payload = {"reason": "Independence Day observed: Sunday schedule"}
    payload.update(body)
    return client.put(
        f"/settings/service-days/{date}",
        json=payload,
        headers=auth_header(fake_db, username),
    )


def test_declare_holiday_override_and_read_it_back(client, fake_db):
    r = _put(client, fake_db, assigned_day_type="sunday")
    assert r.status_code == 200
    body = r.json()
    assert body["service_date"] == JULY_3
    assert body["assigned_day_type"] == "sunday"
    assert body["atypical"] is False
    assert body["updated_by"] == "cora"
    assert body["audit_event_id"]

    listed = client.get(
        "/settings/service-days", headers=auth_header(fake_db, "vera")
    )
    assert listed.status_code == 200
    assert [o["service_date"] for o in listed.json()] == [JULY_3]

    # The declaration is audited with old (none) and new values.
    event = fake_db.audit_events[-1]
    assert event["action"] == "service_day_override_set"
    assert event["subject_id"] == JULY_3
    detail = json.loads(event["detail"])
    assert detail["old"] is None
    assert detail["new"]["assigned_day_type"] == "sunday"


def test_replacing_a_declaration_audits_old_and_new(client, fake_db):
    _put(client, fake_db, assigned_day_type="sunday")
    r = _put(
        client,
        fake_db,
        assigned_day_type="saturday",
        atypical=True,
        reason="corrected: Saturday schedule, festival detours",
    )
    assert r.status_code == 200
    event = fake_db.audit_events[-1]
    detail = json.loads(event["detail"])
    assert detail["old"]["assigned_day_type"] == "sunday"
    assert detail["new"]["assigned_day_type"] == "saturday"
    assert detail["new"]["atypical"] is True


def test_atypical_flag_only_declaration_is_valid(client, fake_db):
    r = _put(
        client, fake_db, atypical=True, reason="parade detours all day"
    )
    assert r.status_code == 200
    assert r.json()["assigned_day_type"] is None
    assert r.json()["atypical"] is True


def test_meaningless_declaration_is_422(client, fake_db):
    r = _put(client, fake_db, reason="says nothing")
    assert r.status_code == 422
    assert "declares nothing" in r.json()["detail"]
    assert fake_db.service_day_overrides == {}


def test_unknown_day_type_is_plain_language_422(client, fake_db):
    r = _put(client, fake_db, assigned_day_type="holiday")
    assert r.status_code == 422
    assert "'weekday', 'saturday' or 'sunday'" in r.json()["detail"]


def test_blank_reason_is_422(client, fake_db):
    r = _put(client, fake_db, assigned_day_type="sunday", reason="   ")
    assert r.status_code == 422
    assert "reason" in r.json()["detail"]


def test_writes_require_certifying_official(client, fake_db):
    for username in ("vera", "stella", "petra"):
        r = _put(client, fake_db, username=username, assigned_day_type="sunday")
        assert r.status_code == 403, username
        d = client.delete(
            f"/settings/service-days/{JULY_3}",
            headers=auth_header(fake_db, username),
        )
        assert d.status_code == 403, username
    assert fake_db.service_day_overrides == {}
    assert fake_db.audit_events == []


def test_anonymous_is_401(client):
    assert client.get("/settings/service-days").status_code == 401


def test_range_read_is_half_open_and_requires_both_bounds(client, fake_db):
    fake_db.add_service_day_override(dt.date(2026, 7, 3), assigned_day_type="sunday")
    fake_db.add_service_day_override(dt.date(2026, 8, 1), atypical=True)
    r = client.get(
        "/settings/service-days",
        params={"from_date": "2026-07-01", "to_date": "2026-08-01"},
        headers=auth_header(fake_db, "vera"),
    )
    assert [o["service_date"] for o in r.json()] == [JULY_3]
    half = client.get(
        "/settings/service-days",
        params={"from_date": "2026-07-01"},
        headers=auth_header(fake_db, "vera"),
    )
    assert half.status_code == 422


def test_delete_removes_and_audits_the_old_declaration(client, fake_db):
    fake_db.add_service_day_override(
        dt.date(2026, 7, 3), assigned_day_type="sunday", reason="holiday"
    )
    r = client.delete(
        f"/settings/service-days/{JULY_3}",
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 200
    assert r.json()["removed"] is True
    assert fake_db.service_day_overrides == {}
    event = fake_db.audit_events[-1]
    assert event["action"] == "service_day_override_removed"
    detail = json.loads(event["detail"])
    assert detail["old"]["assigned_day_type"] == "sunday"
    assert detail["new"] is None


def test_delete_of_undeclared_date_is_404(client, fake_db):
    r = client.delete(
        f"/settings/service-days/{JULY_3}",
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 404
    assert "nothing to remove" in r.json()["detail"]
