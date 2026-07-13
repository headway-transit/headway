"""Sampling endpoints (handoff 0012): plan creation with calc-selector
sizes, seeded per-period draws (§63.03 recorded seed), append-only
measurement entry with supersede corrections, progress, and the §83 APTL
estimate with its undersampling refusal and estimation provenance.
"""

from __future__ import annotations

import json
from decimal import Decimal

from conftest import auth_header


def _last_audit_detail(fake_db) -> dict:
    return json.loads(fake_db.audit_events[-1]["detail"])

PLAN_BODY = {
    "report_year": 2026,
    "mode": "DR",
    "type_of_service": "DO",
    "unit": "vehicle_days",
    "efficiency_option": "aptl",
    "frequency": "quarterly",
}


def _make_plan(client, fake_db, **overrides):
    body = {**PLAN_BODY, **overrides}
    response = client.post(
        "/sampling/plans", json=body, headers=auth_header(fake_db, "stella")
    )
    assert response.status_code == 201, response.text
    return response.json()


def _draw(client, fake_db, plan_id, units, period="2026-Q1", **extra):
    response = client.post(
        f"/sampling/plans/{plan_id}/draws",
        json={"period_label": period, "service_units": units, **extra},
        headers=auth_header(fake_db, "stella"),
    )
    return response


# --- options + requirements ------------------------------------------------------


def test_options_carry_vocabulary_guidance_and_retention_note(client, fake_db):
    response = client.get(
        "/sampling/options", headers=auth_header(fake_db, "vera")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["units_by_mode"]["MB"] == ["one_way_trips", "round_trips"]
    assert body["units_by_mode"]["DR"] == ["vehicle_days"]
    assert body["creatable_options"] == ["aptl", "base"]
    assert any("mandatory sampling year" in g for g in body["eligibility_guidance"])
    assert "3 years" in body["retention_note"]
    assert "p. 150" in body["retention_note"]


def test_requirements_lookup_verbatim_cell_with_citation(client, fake_db):
    response = client.get(
        "/sampling/requirements",
        params={
            "mode": "MB",
            "unit": "one_way_trips",
            "efficiency_option": "base",
            "frequency": "weekly",
        },
        headers=auth_header(fake_db, "vera"),
    )
    assert response.status_code == 200
    body = response.json()
    # Table 43.03 column (3), weekly: 11 per week / 572 per year.
    assert body["required_per_period"] == 11
    assert body["required_annual"] == 572
    assert "Table 43.03" in body["table"]
    assert "FTA NTD Sampling Manual, March 31, 2009" in body["citation"]


def test_requirements_rejects_bad_combination_in_plain_language(client, fake_db):
    response = client.get(
        "/sampling/requirements",
        params={
            "mode": "DR",
            "unit": "one_way_trips",
            "efficiency_option": "aptl",
            "frequency": "weekly",
        },
        headers=auth_header(fake_db, "vera"),
    )
    assert response.status_code == 422
    assert "Table 41.01" in response.json()["detail"]


# --- plan creation ----------------------------------------------------------------


def test_create_plan_requires_data_steward(client, fake_db):
    denied = client.post(
        "/sampling/plans", json=PLAN_BODY, headers=auth_header(fake_db, "vera")
    )
    assert denied.status_code == 403
    assert fake_db.sampling_plans == {}


def test_create_plan_records_selector_sizes_citation_and_audit(client, fake_db):
    body = _make_plan(client, fake_db)
    plan = body["plan"]
    assert plan["required_per_period"] == 12  # Table 43.01, DR APTL quarterly
    assert plan["required_annual"] == 48
    assert plan["selector_version"] == "sampling_v0 0.1.0"
    assert plan["status"] == "created"
    assert "Table 43.01" in plan["table_citation"]
    assert any("New Mode" in g for g in body["guidance"])
    assert "3 years" in body["retention_note"]
    # Audited, and the row landed.
    assert fake_db.sampling_plans[plan["plan_id"]]["required_annual"] == 48
    audit = fake_db.audit_events[-1]
    assert audit["action"] == "sampling_plan_create"
    assert audit["subject_id"] == plan["plan_id"]


def test_create_plan_refuses_grouped_option_with_guidance(client, fake_db):
    response = client.post(
        "/sampling/plans",
        json={**PLAN_BODY, "mode": "MB", "unit": "one_way_trips",
              "efficiency_option": "aptl_grouped"},
        headers=auth_header(fake_db, "stella"),
    )
    assert response.status_code == 422
    assert "§43.05(a)" in response.json()["detail"]
    assert fake_db.sampling_plans == {}


def test_create_plan_refuses_invalid_cell_via_selector(client, fake_db):
    response = client.post(
        "/sampling/plans",
        json={**PLAN_BODY, "unit": "round_trips"},
        headers=auth_header(fake_db, "stella"),
    )
    assert response.status_code == 422
    assert "Table 41.01" in response.json()["detail"]


def test_list_and_get_plans(client, fake_db):
    created = _make_plan(client, fake_db)["plan"]
    listed = client.get(
        "/sampling/plans", headers=auth_header(fake_db, "vera")
    )
    assert listed.status_code == 200
    assert [p["plan_id"] for p in listed.json()] == [created["plan_id"]]
    fetched = client.get(
        f"/sampling/plans/{created['plan_id']}",
        headers=auth_header(fake_db, "vera"),
    )
    assert fetched.status_code == 200
    assert fetched.json()["required_annual"] == 48
    missing = client.get(
        f"/sampling/plans/{created['plan_id'][:-4]}beef",
        headers=auth_header(fake_db, "vera"),
    )
    assert missing.status_code == 404


# --- draws ------------------------------------------------------------------------


def test_draw_selects_required_size_records_seed_and_activates_plan(
    client, fake_db
):
    plan = _make_plan(client, fake_db)["plan"]
    units = [f"2026-Q1/day-{i:03d}" for i in range(1, 61)]
    response = _draw(client, fake_db, plan["plan_id"], units)
    assert response.status_code == 201, response.text
    body = response.json()
    draw = body["draw"]
    assert len(draw["selected_units"]) == 12  # required_per_period
    assert set(draw["selected_units"]) <= set(units)
    assert len(set(draw["selected_units"])) == 12  # without replacement
    assert draw["seed"]  # generated and RECORDED
    assert draw["drawer_version"] == "sampling_v0 0.1.0"
    assert "§63.03" in body["method"]
    assert body["oversampling_note"] is None
    # The plan moved to active.
    assert fake_db.sampling_plans[plan["plan_id"]]["status"] == "active"
    assert fake_db.audit_events[-1]["action"] == "sampling_draw_create"
    assert _last_audit_detail(fake_db)["seed"] == draw["seed"]


def test_draw_with_explicit_seed_is_reproducible_and_deterministic(
    client, fake_db
):
    plan = _make_plan(client, fake_db)["plan"]
    plan2 = _make_plan(client, fake_db)["plan"]
    units = [f"2026-Q1/day-{i:03d}" for i in range(1, 41)]
    first = _draw(client, fake_db, plan["plan_id"], units, seed="a-recorded-seed-1")
    second = _draw(
        client, fake_db, plan2["plan_id"], list(reversed(units)),
        seed="a-recorded-seed-1",
    )
    assert first.status_code == second.status_code == 201
    assert (
        first.json()["draw"]["selected_units"]
        == second.json()["draw"]["selected_units"]
    )


def test_draw_oversample_is_flagged_random(client, fake_db):
    plan = _make_plan(client, fake_db)["plan"]
    units = [f"2026-Q1/day-{i:03d}" for i in range(1, 41)]
    response = _draw(
        client, fake_db, plan["plan_id"], units, oversample_units=3
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["draw"]["selected_units"]) == 15  # 12 + 3
    assert body["draw"]["oversample_units"] == 3
    assert "only when the extra units are selected randomly" in body["oversampling_note"]


def test_generated_seed_draw_records_seed_source_generated(client, fake_db):
    """Seed provenance (hardening pass 2026-07-13, migration 0022): a draw
    whose seed Headway generated records seed_source='generated' — on the
    row, in the audit detail, and in the method text's provenance note."""
    plan = _make_plan(client, fake_db)["plan"]
    units = [f"2026-Q1/day-{i:03d}" for i in range(1, 41)]
    body = _draw(client, fake_db, plan["plan_id"], units).json()

    assert body["draw"]["seed_source"] == "generated"
    (row,) = fake_db.sampling_draws
    assert row["seed_source"] == "generated"
    assert _last_audit_detail(fake_db)["seed_source"] == "generated"
    assert "seed_source='generated'" in body["method"]
    assert "cryptographic randomness source" in body["method"]
    # ...and the recorded draw serves it back on the list endpoint.
    (listed,) = client.get(
        f"/sampling/plans/{plan['plan_id']}/draws",
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert listed["seed_source"] == "generated"


def test_client_seed_draw_records_seed_source_client(client, fake_db):
    """A caller-supplied seed records seed_source='client', and the method
    text no longer asserts cryptographic randomness for it — the randomness
    claim is explicitly the caller's to evidence."""
    plan = _make_plan(client, fake_db)["plan"]
    units = [f"2026-Q1/day-{i:03d}" for i in range(1, 41)]
    body = _draw(
        client, fake_db, plan["plan_id"], units, seed="caller-chosen-seed-1"
    ).json()

    assert body["draw"]["seed_source"] == "client"
    assert body["draw"]["seed"] == "caller-chosen-seed-1"
    (row,) = fake_db.sampling_draws
    assert row["seed_source"] == "client"
    assert _last_audit_detail(fake_db)["seed_source"] == "client"
    assert "seed_source='client'" in body["method"]
    assert "SUPPLIED BY THE CALLER" in body["method"]
    assert "cannot vouch" in body["method"]
    assert "rests on how the caller produced the seed" in body["method"]


def test_draw_free_text_fields_have_plain_language_bounds(client, fake_db):
    """Hardening pass 2026-07-13: TEXT-bound draw fields get sane caps."""
    plan = _make_plan(client, fake_db)["plan"]
    units = [f"2026-Q1/day-{i:03d}" for i in range(1, 41)]

    long_label = _draw(
        client, fake_db, plan["plan_id"], units, period="P" * 101
    )
    assert long_label.status_code == 422
    assert "at most 100" in str(long_label.json())

    long_seed = _draw(
        client, fake_db, plan["plan_id"], units, seed="s" * 201
    )
    assert long_seed.status_code == 422
    assert "at most 200" in str(long_seed.json())

    long_unit = _draw(
        client, fake_db, plan["plan_id"], units + ["u" * 501]
    )
    assert long_unit.status_code == 422
    assert "at most 500" in str(long_unit.json())
    assert fake_db.sampling_draws == []


def test_draw_refuses_second_draw_for_same_period(client, fake_db):
    plan = _make_plan(client, fake_db)["plan"]
    units = [f"2026-Q1/day-{i:03d}" for i in range(1, 41)]
    assert _draw(client, fake_db, plan["plan_id"], units).status_code == 201
    again = _draw(
        client, fake_db, plan["plan_id"],
        [f"2026-Q1b/day-{i}" for i in range(1, 41)],
    )
    assert again.status_code == 409
    assert "already drawn" in again.json()["detail"]


def test_draw_refuses_unit_ids_reused_across_periods(client, fake_db):
    plan = _make_plan(client, fake_db)["plan"]
    units = [f"day-{i:03d}" for i in range(1, 41)]  # NOT period-qualified
    assert _draw(client, fake_db, plan["plan_id"], units).status_code == 201
    reused = _draw(client, fake_db, plan["plan_id"], units, period="2026-Q2")
    assert reused.status_code == 422
    assert "already listed in an earlier period" in reused.json()["detail"]


def test_draw_refuses_undersized_frame_and_duplicates(client, fake_db):
    plan = _make_plan(client, fake_db)["plan"]
    too_small = _draw(client, fake_db, plan["plan_id"], ["u1", "u2"])
    assert too_small.status_code == 422
    assert "without replacement" in too_small.json()["detail"]
    dupes = _draw(
        client, fake_db, plan["plan_id"],
        ["u1", "u1"] + [f"u{i}" for i in range(2, 20)],
    )
    assert dupes.status_code == 422
    assert "duplicate" in dupes.json()["detail"]
    assert fake_db.sampling_draws == []


# --- measurements -----------------------------------------------------------------


def _plan_with_draw(client, fake_db, n_units=60, **plan_overrides):
    plan = _make_plan(client, fake_db, **plan_overrides)["plan"]
    units = [f"2026-Q1/day-{i:03d}" for i in range(1, n_units + 1)]
    draw = _draw(client, fake_db, plan["plan_id"], units).json()["draw"]
    return plan, draw


def test_measurement_entry_for_drawn_unit_audited_with_caveat(client, fake_db):
    plan, draw = _plan_with_draw(client, fake_db)
    unit = draw["selected_units"][0]
    response = client.post(
        f"/sampling/plans/{plan['plan_id']}/measurements",
        json={"unit_id": unit, "observed_upt": 14, "observed_pmt": "52.4",
              "service_day_type": "Weekday"},
        headers=auth_header(fake_db, "stella"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["measurement"]["observed_pmt"] == "52.4"  # string, not float
    assert body["measurement"]["data_source"] == "manual_ride_check"
    assert "MANUALLY ENTERED" in body["source_caveat"]
    assert fake_db.audit_events[-1]["action"] == "sampling_measurement_create"


def test_measurement_refused_for_unselected_unit(client, fake_db):
    plan, draw = _plan_with_draw(client, fake_db)
    unselected = next(
        u for u in (f"2026-Q1/day-{i:03d}" for i in range(1, 61))
        if u not in draw["selected_units"]
    )
    response = client.post(
        f"/sampling/plans/{plan['plan_id']}/measurements",
        json={"unit_id": unselected, "observed_upt": 5, "observed_pmt": "10"},
        headers=auth_header(fake_db, "stella"),
    )
    assert response.status_code == 422
    assert "not in this plan's drawn sample" in response.json()["detail"]
    assert fake_db.sampling_measurements == {}


def test_measurement_refused_before_any_draw(client, fake_db):
    plan = _make_plan(client, fake_db)["plan"]
    response = client.post(
        f"/sampling/plans/{plan['plan_id']}/measurements",
        json={"unit_id": "u1", "observed_upt": 5, "observed_pmt": "10"},
        headers=auth_header(fake_db, "stella"),
    )
    assert response.status_code == 422
    assert "no drawn sample yet" in response.json()["detail"]


def test_duplicate_measurement_conflicts_and_supersede_corrects(client, fake_db):
    plan, draw = _plan_with_draw(client, fake_db)
    unit = draw["selected_units"][0]
    first = client.post(
        f"/sampling/plans/{plan['plan_id']}/measurements",
        json={"unit_id": unit, "observed_upt": 14, "observed_pmt": "52.4"},
        headers=auth_header(fake_db, "stella"),
    ).json()
    duplicate = client.post(
        f"/sampling/plans/{plan['plan_id']}/measurements",
        json={"unit_id": unit, "observed_upt": 15, "observed_pmt": "60"},
        headers=auth_header(fake_db, "stella"),
    )
    assert duplicate.status_code == 409
    assert "supersede" in duplicate.json()["detail"]

    measurement_id = first["measurement"]["measurement_id"]
    corrected = client.post(
        f"/sampling/measurements/{measurement_id}/supersede",
        json={"unit_id": unit, "observed_upt": 15, "observed_pmt": "60.0",
              "reason": "Checker transposed the boarding tallies."},
        headers=auth_header(fake_db, "stella"),
    )
    assert corrected.status_code == 201, corrected.text
    body = corrected.json()
    assert body["original_measurement_id"] == measurement_id
    replacement_id = body["replacement"]["measurement_id"]
    # Original links to the replacement; original values untouched.
    original_row = fake_db.sampling_measurements[measurement_id]
    assert original_row["superseded_by"] == replacement_id
    assert original_row["observed_upt"] == 14
    assert fake_db.audit_events[-1]["action"] == "sampling_measurement_supersede"
    assert _last_audit_detail(fake_db)["reason"].startswith("Checker")

    # A second correction of the SAME original conflicts.
    again = client.post(
        f"/sampling/measurements/{measurement_id}/supersede",
        json={"unit_id": unit, "observed_upt": 16, "observed_pmt": "61",
              "reason": "again"},
        headers=auth_header(fake_db, "stella"),
    )
    assert again.status_code == 409

    # Active list shows only the correction; include_superseded shows both.
    active = client.get(
        f"/sampling/plans/{plan['plan_id']}/measurements",
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert [m["measurement_id"] for m in active] == [replacement_id]
    everything = client.get(
        f"/sampling/plans/{plan['plan_id']}/measurements",
        params={"include_superseded": "true"},
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert len(everything) == 2


def test_supersede_cannot_switch_units(client, fake_db):
    plan, draw = _plan_with_draw(client, fake_db)
    unit = draw["selected_units"][0]
    other = draw["selected_units"][1]
    first = client.post(
        f"/sampling/plans/{plan['plan_id']}/measurements",
        json={"unit_id": unit, "observed_upt": 14, "observed_pmt": "52.4"},
        headers=auth_header(fake_db, "stella"),
    ).json()
    response = client.post(
        f"/sampling/measurements/{first['measurement']['measurement_id']}/supersede",
        json={"unit_id": other, "observed_upt": 1, "observed_pmt": "2",
              "reason": "wrong unit"},
        headers=auth_header(fake_db, "stella"),
    )
    assert response.status_code == 422
    assert "same service unit" in response.json()["detail"]


# --- progress ---------------------------------------------------------------------


def test_progress_counts_measured_vs_required_with_worksheet(client, fake_db):
    plan, draw = _plan_with_draw(client, fake_db)
    for unit in draw["selected_units"][:5]:
        client.post(
            f"/sampling/plans/{plan['plan_id']}/measurements",
            json={"unit_id": unit, "observed_upt": 10, "observed_pmt": "35"},
            headers=auth_header(fake_db, "stella"),
        )
    response = client.get(
        f"/sampling/plans/{plan['plan_id']}/progress",
        headers=auth_header(fake_db, "vera"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["required_annual"] == 48
    assert body["units_selected"] == 12
    assert body["units_measured"] == 5
    assert body["units_unmeasured"] == draw["selected_units"][5:]
    assert body["undersampled"] is True
    assert "follow the sampling technique exactly" in body["undersampling_citation"]
    assert body["draws"][0]["period_label"] == "2026-Q1"
    assert body["draws"][0]["measured"] == 5


# --- the §83 estimate --------------------------------------------------------------


def _measured_plan(client, fake_db):
    """A weekly DR APTL plan (1/week, 52/year — Table 43.01) fully measured
    across 52 period draws: the smallest fully-sampled fixture."""
    plan = _make_plan(client, fake_db, frequency="weekly")["plan"]
    assert plan["required_annual"] == 52
    units = []
    for week in range(1, 53):
        frame = [f"2026-W{week:02d}/day-{i}" for i in range(1, 8)]
        draw = _draw(
            client, fake_db, plan["plan_id"], frame,
            period=f"2026-W{week:02d}", seed="a-recorded-seed-x",
        )
        assert draw.status_code == 201
        units.extend(draw.json()["draw"]["selected_units"])
    day_types = ["Weekday", "Saturday", "Sunday"]
    for i, unit in enumerate(units):
        response = client.post(
            f"/sampling/plans/{plan['plan_id']}/measurements",
            json={
                "unit_id": unit,
                "observed_upt": 10 + (i % 3),
                "observed_pmt": str(Decimal("41.5") + i),
                "service_day_type": day_types[i % 3],
            },
            headers=auth_header(fake_db, "stella"),
        )
        assert response.status_code == 201
    return plan, units


def test_estimate_requires_report_preparer(client, fake_db):
    plan, _ = _plan_with_draw(client, fake_db)
    denied = client.post(
        f"/sampling/plans/{plan['plan_id']}/estimate",
        json={"annual_upt_100pct": "250000"},
        headers=auth_header(fake_db, "stella"),
    )
    assert denied.status_code == 403


def test_estimate_refuses_undersampled_plan_with_citation(client, fake_db):
    plan, draw = _plan_with_draw(client, fake_db)
    for unit in draw["selected_units"]:  # 12 of the 48 required
        client.post(
            f"/sampling/plans/{plan['plan_id']}/measurements",
            json={"unit_id": unit, "observed_upt": 10, "observed_pmt": "35"},
            headers=auth_header(fake_db, "petra"),
        )
    response = client.post(
        f"/sampling/plans/{plan['plan_id']}/estimate",
        json={"annual_upt_100pct": "250000"},
        headers=auth_header(fake_db, "petra"),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "requires 48 measured" in detail
    assert "only 12" in detail
    assert "follow the sampling technique exactly" in detail
    # The refusal generated no audit event and no estimate.
    assert all(
        e["action"] != "sampling_estimate_generate"
        for e in fake_db.audit_events
    )


def test_estimate_refuses_base_option_plan(client, fake_db):
    plan = _make_plan(client, fake_db, efficiency_option="base")["plan"]
    response = client.post(
        f"/sampling/plans/{plan['plan_id']}/estimate",
        json={"annual_upt_100pct": "250000"},
        headers=auth_header(fake_db, "petra"),
    )
    assert response.status_code == 422
    assert "Section 70" in response.json()["detail"]


def test_estimate_ratio_of_totals_with_provenance_and_by_day_variant(
    client, fake_db
):
    plan, units = _measured_plan(client, fake_db)
    response = client.post(
        f"/sampling/plans/{plan['plan_id']}/estimate",
        json={
            "annual_upt_100pct": "250000",
            "upt_100pct_by_day_type": {
                "Weekday": "180000", "Saturday": "40000", "Sunday": "30000",
            },
        },
        headers=auth_header(fake_db, "petra"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    estimate = body["estimate"]
    # Ratio of totals, computed by hand from the fixture: UPT 10+(i%3)
    # (18 zeros, 17 ones, 17 twos → 520 + 51 = 571), PMT 41.5+i over
    # i=0..51 (52 × 41.5 + 1326 = 3484.0) → APTL 3484/571 = 6.1015… → 6.10;
    # estimate 250,000 × 6.10 = 1,525,000.
    assert estimate["sample_size"] == 52
    assert estimate["sample_total_upt"] == 571
    assert estimate["sample_total_pmt"] == "3484.0"
    assert estimate["sample_aptl"] == "6.10"
    assert estimate["estimated_pmt"] == "1525000"
    assert "estimated — sampled average passenger trip length" in estimate["method"]
    # Never conflated with computed PMT; metric_values untouched.
    assert any("computed.metric_values is untouched" in c for c in body["caveats"])
    assert fake_db.metric_values == {}
    # The §83.05(b) ban travels on the receipt, verbatim.
    assert any(
        "You must not determine the sample APTL as the average of the APTL"
        in c
        for c in body["citations"]
    )
    # By-day-type blocks present, each a ratio of that day's totals.
    scopes = [b["scope"] for b in body["by_service_day"]]
    assert scopes == ["Weekday", "Saturday", "Sunday"]
    assert body["oversampled_by"] == 0
    assert fake_db.audit_events[-1]["action"] == "sampling_estimate_generate"
    assert _last_audit_detail(fake_db)["estimated_pmt"] == estimate["estimated_pmt"]


def test_estimate_by_day_refuses_missing_day_expansion_factor(client, fake_db):
    plan, _ = _measured_plan(client, fake_db)
    response = client.post(
        f"/sampling/plans/{plan['plan_id']}/estimate",
        json={
            "annual_upt_100pct": "250000",
            "upt_100pct_by_day_type": {"Weekday": "180000"},
        },
        headers=auth_header(fake_db, "petra"),
    )
    assert response.status_code == 422
    assert "never guessed" in response.json()["detail"]
