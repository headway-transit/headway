"""Safety & Security endpoints (handoff 0010): validated audited entry with
synchronous deterministic classification (sscls_v0), list filters,
append-only supersede corrections, and the computed S&S-40/S&S-50 deadlines
including zero-event months for operated modes.
"""

from __future__ import annotations

import datetime as dt
import json

from conftest import auth_header

UTC = dt.timezone.utc

VALID_EVENT = {
    "occurred_at": "2026-06-15T14:30:00Z",
    "mode": "bus",
    "type_of_service": "DO",
    "event_category": "collision",
    "narrative": "Bus 1207 struck a utility pole at low speed.",
    "location": "Elm St & 3rd Ave",
    "injuries": 2,
}


# --- POST /safety/events --------------------------------------------------------


def test_create_requires_data_steward(client, fake_db):
    denied = client.post(
        "/safety/events", json=VALID_EVENT, headers=auth_header(fake_db, "vera")
    )
    assert denied.status_code == 403
    assert "data steward" in denied.json()["detail"]
    assert fake_db.safety_events == {}


def test_create_classifies_synchronously_with_explanation_and_citation(
    client, fake_db
):
    response = client.post(
        "/safety/events", json=VALID_EVENT, headers=auth_header(fake_db, "stella")
    )
    assert response.status_code == 201
    body = response.json()
    result = body["result"]
    # Two injuries with immediate transport on a non-rail mode → major
    # (the Example 4A rule; Exhibit 5, p. 16).
    assert result["classification"] == "major"
    assert result["thresholds_met"] == ["injury_immediate_transport"]
    assert result["classifier_version"] == "sscls_v0 0.1.1"
    explanation = result["explanations"][0]
    assert "2 person(s)" in explanation["plain_language"]
    assert "Immediate transport away from the scene" in explanation["citation"]
    assert "REGULATORY_TRACKER.md" in explanation["citation"]
    assert "ONE reportable major event" in result["summary"]

    # The row and its classification both landed, and the classification
    # row was written through the classifier (version string, migration
    # 0017 only-writer rule).
    event = fake_db.safety_events[body["event_id"]]
    assert event["narrative"] == VALID_EVENT["narrative"]
    assert event["entered_by"] == "stella"
    (classification,) = fake_db.safety_classifications
    assert classification["event_id"] == body["event_id"]
    assert classification["classification"] == "major"
    assert classification["classifier_version"] == "sscls_v0 0.1.1"


def test_create_is_audited_in_the_same_transaction(client, fake_db):
    response = client.post(
        "/safety/events", json=VALID_EVENT, headers=auth_header(fake_db, "stella")
    )
    audit = fake_db.audit_events[-1]
    assert audit["action"] == "safety_event_create"
    assert audit["subject_kind"] == "safety.events"
    assert audit["subject_id"] == response.json()["event_id"]
    assert audit["event_id"] == response.json()["audit_event_id"]
    assert fake_db.tx_log == ["commit"]


def test_create_validation_is_plain_language(client, fake_db):
    headers = auth_header(fake_db, "stella")

    naive = client.post(
        "/safety/events",
        json={**VALID_EVENT, "occurred_at": "2026-06-15T14:30:00"},
        headers=headers,
    )
    assert naive.status_code == 422
    assert "include a time zone" in str(naive.json())

    bad_category = client.post(
        "/safety/events",
        json={**VALID_EVENT, "event_category": "explosion"},
        headers=headers,
    )
    assert bad_category.status_code == 422
    assert "not an event category Headway knows" in str(bad_category.json())

    negative = client.post(
        "/safety/events",
        json={**VALID_EVENT, "injuries": -1},
        headers=headers,
    )
    assert negative.status_code == 422
    assert "counts of people" in str(negative.json())

    negative_damage = client.post(
        "/safety/events",
        json={**VALID_EVENT, "property_damage_usd": "-5"},
        headers=headers,
    )
    assert negative_damage.status_code == 422
    assert "has not been assessed" in str(negative_damage.json())
    assert fake_db.safety_events == {}


def test_create_cyber_major_via_scenario_g(client, fake_db):
    response = client.post(
        "/safety/events",
        json={
            **VALID_EVENT,
            "event_category": "cyber",
            "injuries": 0,
            "substantial_damage": True,
            "narrative": "Unauthorized access to dispatch servers halted service.",
        },
        headers=auth_header(fake_db, "stella"),
    )
    result = response.json()["result"]
    assert result["classification"] == "major"
    assert result["thresholds_met"] == ["cyber_substantial_damage"]
    assert "Scenario G" in result["explanations"][0]["citation"]


def test_create_assault_on_worker_no_injury_is_non_major(client, fake_db):
    response = client.post(
        "/safety/events",
        json={
            **VALID_EVENT,
            "event_category": "assault",
            "injuries": 0,
            "assault_on_worker": True,
        },
        headers=auth_header(fake_db, "stella"),
    )
    result = response.json()["result"]
    assert result["classification"] == "non_major"
    assert result["thresholds_met"] == []
    basis = result["non_major_basis"][0]
    assert basis["threshold"] == "non_major_assault_on_worker"
    assert "do not require an injury" in basis["citation"]


def test_create_runaway_train_field_flows_to_classifier_and_row(
    client, fake_db
):
    # Migration 0018 / addendum correction round: the runaway_train field
    # reaches the row and triggers the rail-only p. 17 threshold.
    response = client.post(
        "/safety/events",
        json={
            **VALID_EVENT,
            "mode": "subway",
            "event_category": "other",
            "injuries": 0,
            "runaway_train": True,
            "narrative": "Unmanned car rolled through the yard after a brake software fault.",
        },
        headers=auth_header(fake_db, "stella"),
    )
    assert response.status_code == 201
    body = response.json()
    result = body["result"]
    assert result["classification"] == "major"
    assert result["thresholds_met"] == ["runaway_train"]
    assert "uncommanded, uncontrolled, or unmanned" in result["explanations"][0]["citation"]
    event = fake_db.safety_events[body["event_id"]]
    assert event["runaway_train"] is True
    assert event["evacuation_to_rail_row"] is False


def test_create_single_injury_other_safety_event_is_non_major_p22(
    client, fake_db
):
    # The 0.1.0 bug fix through the API: one immediate-transport injury in
    # an Other Safety Event (slip/trip/fall/...) is NON-major and belongs
    # on the S&S-50 (p. 22) — with the citation in the response.
    response = client.post(
        "/safety/events",
        json={
            **VALID_EVENT,
            "event_category": "other",
            "injuries": 1,
            "narrative": "Passenger slipped on wet stairs; one EMS transport.",
        },
        headers=auth_header(fake_db, "stella"),
    )
    result = response.json()["result"]
    assert result["classification"] == "non_major"
    (basis,) = result["non_major_basis"]
    assert basis["threshold"] == "other_safety_event_single_injury"
    assert "Non-Major Summary Report" in basis["citation"]
    # Two injuries in the same event category ARE major (p. 22).
    two = client.post(
        "/safety/events",
        json={**VALID_EVENT, "event_category": "other", "injuries": 2},
        headers=auth_header(fake_db, "stella"),
    ).json()["result"]
    assert two["classification"] == "major"
    assert two["thresholds_met"] == ["injury_two_or_more"]


# --- GET /safety/events ---------------------------------------------------------


def _seed_events(fake_db):
    major = fake_db.add_safety_event(
        occurred_at=dt.datetime(2026, 6, 5, 9, 0, tzinfo=UTC),
        event_category="collision", injuries=2,
    )
    fake_db.add_safety_classification(
        major["event_id"], "major", ("injury_immediate_transport",)
    )
    non_major = fake_db.add_safety_event(
        occurred_at=dt.datetime(2026, 6, 20, 9, 0, tzinfo=UTC),
        mode="rail", event_category="collision", injuries=1,
    )
    fake_db.add_safety_classification(non_major["event_id"], "non_major")
    july = fake_db.add_safety_event(
        occurred_at=dt.datetime(2026, 7, 2, 9, 0, tzinfo=UTC),
        event_category="fire",
    )
    fake_db.add_safety_classification(july["event_id"], "non_major")
    return major, non_major, july


def test_list_events_any_signed_in_role_with_filters(client, fake_db):
    major, non_major, july = _seed_events(fake_db)
    headers = auth_header(fake_db, "vera")

    everything = client.get("/safety/events", headers=headers)
    assert everything.status_code == 200
    assert [e["event_id"] for e in everything.json()] == [
        major["event_id"], non_major["event_id"], july["event_id"]
    ]

    june = client.get("/safety/events?month=2026-06", headers=headers)
    assert [e["event_id"] for e in june.json()] == [
        major["event_id"], non_major["event_id"]
    ]

    rail = client.get("/safety/events?mode=rail", headers=headers)
    assert [e["event_id"] for e in rail.json()] == [non_major["event_id"]]

    majors = client.get("/safety/events?classification=major", headers=headers)
    assert [e["event_id"] for e in majors.json()] == [major["event_id"]]

    combined = client.get(
        "/safety/events?month=2026-06&mode=bus&classification=major",
        headers=headers,
    )
    assert [e["event_id"] for e in combined.json()] == [major["event_id"]]
    record = combined.json()[0]
    assert record["classification"] == "major"
    assert record["thresholds_met"] == ["injury_immediate_transport"]
    assert record["classifier_version"] == "sscls_v0 0.1.1"


def test_list_events_refuses_bad_filters_plainly(client, fake_db):
    headers = auth_header(fake_db, "vera")
    bad_class = client.get(
        "/safety/events?classification=huge", headers=headers
    )
    assert bad_class.status_code == 422
    assert "not a classification Headway knows" in bad_class.json()["detail"]
    bad_month = client.get("/safety/events?month=June", headers=headers)
    assert bad_month.status_code == 422
    assert "YYYY-MM" in bad_month.json()["detail"]


def test_list_events_serves_damage_as_exact_string(client, fake_db):
    from decimal import Decimal

    event = fake_db.add_safety_event(property_damage_usd=Decimal("31000.10"))
    fake_db.add_safety_classification(event["event_id"], "not_reportable")
    (record,) = client.get(
        "/safety/events", headers=auth_header(fake_db, "vera")
    ).json()
    assert record["property_damage_usd"] == "31000.10"


# --- POST /safety/events/{id}/supersede -------------------------------------------


def test_supersede_links_original_and_classifies_replacement(client, fake_db):
    original = fake_db.add_safety_event(injuries=0)
    fake_db.add_safety_classification(original["event_id"], "not_reportable")

    response = client.post(
        f"/safety/events/{original['event_id']}/supersede",
        json={
            **VALID_EVENT,
            "reason": "Hospital confirmed two immediate transports.",
        },
        headers=auth_header(fake_db, "stella"),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["original_event_id"] == original["event_id"]
    replacement_id = body["replacement_event_id"]
    assert body["result"]["classification"] == "major"

    # Append-only: the original still exists, now pointing at the
    # replacement; the replacement is a full new row with its own verdict.
    assert fake_db.safety_events[original["event_id"]]["superseded_by"] == replacement_id
    assert fake_db.safety_events[replacement_id]["superseded_by"] is None
    latest = fake_db.safety_classifications[-1]
    assert latest["event_id"] == replacement_id

    audit = fake_db.audit_events[-1]
    assert audit["action"] == "safety_event_supersede"
    assert audit["subject_id"] == original["event_id"]
    detail = json.loads(audit["detail"])
    assert detail["replacement_event_id"] == replacement_id
    assert detail["reason"].startswith("Hospital confirmed")


def test_supersede_refuses_unknown_and_double_corrections(client, fake_db):
    headers = auth_header(fake_db, "stella")
    payload = {**VALID_EVENT, "reason": "fix"}

    missing = client.post(
        "/safety/events/no-such-event/supersede", json=payload, headers=headers
    )
    assert missing.status_code == 404

    original = fake_db.add_safety_event()
    replacement = fake_db.add_safety_event()
    fake_db.safety_events[original["event_id"]]["superseded_by"] = replacement["event_id"]
    events_before = dict(fake_db.safety_events)
    double = client.post(
        f"/safety/events/{original['event_id']}/supersede",
        json=payload, headers=headers,
    )
    assert double.status_code == 409
    assert "already corrected" in double.json()["detail"]
    # The refused correction left nothing behind (transaction rollback).
    assert fake_db.safety_events == events_before


def test_supersede_requires_data_steward_and_a_reason(client, fake_db):
    original = fake_db.add_safety_event()
    denied = client.post(
        f"/safety/events/{original['event_id']}/supersede",
        json={**VALID_EVENT, "reason": "x"},
        headers=auth_header(fake_db, "vera"),
    )
    assert denied.status_code == 403
    no_reason = client.post(
        f"/safety/events/{original['event_id']}/supersede",
        json=VALID_EVENT,
        headers=auth_header(fake_db, "stella"),
    )
    assert no_reason.status_code == 422


# --- GET /safety/deadlines ---------------------------------------------------------


def test_deadlines_ss40_thirty_days_and_ss50_end_of_following_month(
    client, fake_db
):
    fake_db.operated_modes = ["bus", "ferry"]
    major, non_major, july = _seed_events(fake_db)

    response = client.get(
        "/safety/deadlines?month=2026-06", headers=auth_header(fake_db, "vera")
    )
    assert response.status_code == 200
    body = response.json()

    # S&S-40: occurred_at + 30 days (Exhibit 2, p. 4), quote-cited.
    (ss40,) = body["ss40"]
    assert ss40["event_id"] == major["event_id"]
    assert ss40["due_date"] == "2026-07-05"  # 2026-06-05 + 30 days
    assert "30 days after the date of the event" in body["ss40_citation"]
    assert "no NTD submission tracking" in body["ss40_note"]

    # S&S-50: per mode for the month, due end of the following month,
    # INCLUDING the zero-event operated mode (ferry) — "even if no event
    # occurs".
    by_mode = {row["mode"]: row for row in body["ss50"]}
    assert set(by_mode) == {"bus", "ferry", "rail"}
    assert all(row["due_date"] == "2026-07-31" for row in body["ss50"])
    assert by_mode["ferry"]["zero_event"] is True
    assert by_mode["ferry"]["non_major_event_count"] == 0
    assert by_mode["rail"]["non_major_event_count"] == 1
    assert by_mode["rail"]["zero_event"] is False
    # bus has a major event but no NON-major event → a zero-event S&S-50
    # row (the major event is S&S-40 territory).
    assert by_mode["bus"]["zero_event"] is True
    assert "even if no event occurs" in body["ss50_citation"]


def test_deadlines_exclude_superseded_majors(client, fake_db):
    original = fake_db.add_safety_event(fatalities=1)
    fake_db.add_safety_classification(original["event_id"], "major", ("fatality",))
    replacement = fake_db.add_safety_event(fatalities=1)
    fake_db.add_safety_classification(
        replacement["event_id"], "major", ("fatality",)
    )
    fake_db.safety_events[original["event_id"]]["superseded_by"] = replacement["event_id"]

    body = client.get(
        "/safety/deadlines?month=2026-06", headers=auth_header(fake_db, "vera")
    ).json()
    assert [d["event_id"] for d in body["ss40"]] == [replacement["event_id"]]


def test_deadlines_null_operated_mode_buckets_as_unknown(client, fake_db):
    fake_db.operated_modes = ["bus", None]
    body = client.get(
        "/safety/deadlines?month=2026-06", headers=auth_header(fake_db, "vera")
    ).json()
    assert [row["mode"] for row in body["ss50"]] == ["bus", "unknown"]


def test_deadlines_refuse_bad_month_and_require_auth(client, fake_db):
    bad = client.get(
        "/safety/deadlines?month=nope", headers=auth_header(fake_db, "vera")
    )
    assert bad.status_code == 422
    anonymous = client.get("/safety/deadlines?month=2026-06")
    assert anonymous.status_code == 401
