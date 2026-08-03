"""The reported-dataset registry — declared cadence beside observed arrival.

From the partner agency's ITS manager (2026-08-03), whose NTD certification
framework opened with an ownership matrix: dataset, owner, system of record,
frequency, NTD form. Headway had no concept of any of it, and everything else
he asked for — cross-source reconciliation, allowable variances, proactive
drift — needs the system to first know two sources exist and who owns each.

What is worth testing here is not CRUD. It is that the registry never
INVENTS anything, and that the four arrival states stay distinct:

- a dataset nobody feeds is 'not_received', which is a coverage gap and not a
  fault — his own matrix had an "eventually" section;
- a dataset with no declared cadence is 'no_cadence', because "late" has no
  meaning without one, and cadence is never inferred from arrivals;
- 'overdue' is the only state that says something is wrong;
- and last_received_at comes from raw.records, never from anything typed.
"""

from __future__ import annotations

import datetime as dt

from conftest import UTC, auth_header


def _record(fake_db, source: str, *, ago: dt.timedelta) -> None:
    fake_db.add_raw_record(source=source, landed_at=dt.datetime.now(UTC) - ago)


def _put(client, fake_db, key: str, **body):
    payload = {
        "display_name": body.pop("display_name", key.title()),
        "owner": body.pop("owner", "Planning"),
        "system_of_record": body.pop("system_of_record", "APC/Farebox"),
        **body,
    }
    return client.put(
        f"/datasets/{key}", json=payload, headers=auth_header(fake_db, "cora")
    )


def _only(client, fake_db, user="vera"):
    page = client.get("/datasets", headers=auth_header(fake_db, user)).json()
    assert len(page["datasets"]) == 1, page
    return page["datasets"][0]


def test_the_registry_starts_empty_and_says_why(client, fake_db):
    """Never seeded. Every row is an agency fact — their departments, their
    vendors, their forms — and an ownership matrix that is subtly wrong is
    worse than an absent one, because it sends someone to the wrong
    department in the middle of a filing."""
    page = client.get("/datasets", headers=auth_header(fake_db, "vera")).json()
    assert page["datasets"] == []
    assert "never fills it in for you" in page["registry_note"]


def test_a_dataset_nobody_feeds_is_a_gap_not_a_fault(client, fake_db):
    """His matrix had fleet inventory, operating expenses and employee counts
    under 'Eventually:'. Recording them states the gap deliberately."""
    assert _put(
        client, fake_db, "fleet_inventory",
        display_name="Fleet Inventory", owner="Asset Mgmt",
        system_of_record="EAM", ntd_forms=["A-30"],
    ).status_code == 200

    row = _only(client, fake_db)
    assert row["arrival_state"] == "not_received"
    assert row["last_received_at"] is None
    assert "not a fault" in row["arrival_note"]


def test_a_source_that_never_delivered_is_distinguished_from_one_never_named(
    client, fake_db
):
    """Both are 'not_received', but the advice differs: one is a coverage gap,
    the other is probably a typo in the source name."""
    _put(client, fake_db, "ridership", headway_sources=["tides"])
    row = _only(client, fake_db)
    assert row["arrival_state"] == "not_received"
    assert "Check the source name" in row["arrival_note"]


def test_arriving_without_a_declared_cadence_is_not_late(client, fake_db):
    """Cadence is NEVER inferred from arrivals. Inferring it would make a
    broken feed look correct by redefining normal around its own failure."""
    _record(fake_db, "tides", ago=dt.timedelta(days=400))
    _put(client, fake_db, "ridership", headway_sources=["tides"])

    row = _only(client, fake_db)
    assert row["arrival_state"] == "no_cadence"
    assert row["expected_interval_seconds"] is None
    assert "cannot say whether they are late" in row["arrival_note"]


def test_overdue_names_both_numbers(client, fake_db):
    """The one state that means something is wrong. It has to say what was
    expected AND what happened, or the reader has to go and look."""
    _record(fake_db, "tides", ago=dt.timedelta(days=9))
    _put(
        client, fake_db, "ridership",
        headway_sources=["tides"], expected_interval_seconds=86400,
    )

    row = _only(client, fake_db)
    assert row["arrival_state"] == "overdue"
    assert "9 days ago" in row["arrival_note"]
    assert "24 hours" in row["arrival_note"]


def test_arriving_within_the_declared_cadence_is_current(client, fake_db):
    _record(fake_db, "tides", ago=dt.timedelta(hours=2))
    _put(
        client, fake_db, "ridership",
        headway_sources=["tides"], expected_interval_seconds=86400,
    )
    assert _only(client, fake_db)["arrival_state"] == "current"


def test_the_freshest_source_decides_not_the_stalest(client, fake_db):
    """A dataset can name several sources. One arriving feed means the dataset
    is arriving — reporting the stalest would call a healthy dataset overdue
    because a second, optional feed is quiet."""
    _record(fake_db, "apc", ago=dt.timedelta(hours=1))
    _record(fake_db, "farebox", ago=dt.timedelta(days=30))
    _put(
        client, fake_db, "ridership",
        headway_sources=["apc", "farebox"], expected_interval_seconds=86400,
    )
    assert _only(client, fake_db)["arrival_state"] == "current"


def test_last_received_comes_from_the_records_never_from_the_registry(
    client, fake_db
):
    """The declared half and the observed half must not be able to drift: the
    observed side reads the same raw.records rows GET /sources/status does."""
    landed = dt.datetime.now(UTC) - dt.timedelta(hours=3)
    fake_db.add_raw_record(source="tides", landed_at=landed)
    _put(client, fake_db, "ridership", headway_sources=["tides"])

    row = _only(client, fake_db)
    assert row["last_received_at"].startswith(landed.isoformat()[:16])


def test_recording_a_dataset_is_audited(client, fake_db):
    """This registry says who is accountable for a federal figure's inputs.
    That is not a note anyone should be able to change unattributed."""
    _put(
        client, fake_db, "revenue_miles",
        display_name="Revenue Miles", owner="CAD/AVL",
        system_of_record="TripSpark Streets", ntd_forms=["S-10"],
    )
    event = [
        e for e in fake_db.audit_events
        if e["action"] == "reported_dataset_recorded"
    ][-1]
    assert event["actor"] == "cora"
    assert event["subject_id"] == "revenue_miles"


def test_only_a_certifying_official_may_change_the_registry(client, fake_db):
    for user in ("vera", "stella", "petra"):
        r = client.put(
            "/datasets/ridership",
            json={
                "display_name": "Ridership",
                "owner": "Planning",
                "system_of_record": "APC",
            },
            headers=auth_header(fake_db, user),
        )
        assert r.status_code == 403, user
    assert fake_db.reported_datasets == {}


def test_removing_a_dataset_is_audited_and_a_missing_one_refuses(
    client, fake_db
):
    _put(client, fake_db, "ridership")
    assert client.delete(
        "/datasets/ridership", headers=auth_header(fake_db, "cora")
    ).status_code == 200
    assert fake_db.reported_datasets == {}
    assert any(
        e["action"] == "reported_dataset_removed" for e in fake_db.audit_events
    )

    missing = client.delete(
        "/datasets/nope", headers=auth_header(fake_db, "cora")
    )
    assert missing.status_code == 404
    assert "nothing to remove" in missing.json()["detail"]


def test_any_signed_in_role_can_read_it(client, fake_db):
    """Knowing what the agency reports and who owns it is orientation, not
    privilege."""
    _put(client, fake_db, "ridership")
    for user in ("vera", "stella", "petra", "cora"):
        r = client.get("/datasets", headers=auth_header(fake_db, user))
        assert r.status_code == 200, user
        assert len(r.json()["datasets"]) == 1
