"""GET /metrics/compare (handoff 0017, design point 1): composition of the
one metric-values reader — cells are FULL verbatim rows (receipt affordance
intact), missing cells carry explicit reasons, deltas are exact Decimal
strings (pinned against hand-worked differences), direction metadata comes
from the calc registry (coverage only), latest-row picking follows the mr20
discipline, and certified-vs-uncertified mixes are flagged."""

import datetime as dt
from decimal import Decimal

from conftest import auth_header

UTC = dt.timezone.utc

JULY = (dt.date(2026, 7, 1), dt.date(2026, 8, 1))
JUNE = (dt.date(2026, 6, 1), dt.date(2026, 7, 1))

JULY_KEY = "2026-07-01..2026-08-01"
JUNE_KEY = "2026-06-01..2026-07-01"


def _seed_versions(fake_db):
    """vrh for the SAME period under two calc versions + one June row."""
    v3 = fake_db.add_metric_value(
        metric="vrh", unit="hours", period_start=JULY[0], period_end=JULY[1],
        value=Decimal("1300.00"), calc_name="vrh_v0", calc_version="0.3.0",
        computed_at=dt.datetime(2026, 8, 2, 10, 0, tzinfo=UTC),
    )
    v4 = fake_db.add_metric_value(
        metric="vrh", unit="hours", period_start=JULY[0], period_end=JULY[1],
        value=Decimal("1260.85"), calc_name="vrh_v0", calc_version="0.4.0",
        computed_at=dt.datetime(2026, 8, 2, 11, 0, tzinfo=UTC),
    )
    june = fake_db.add_metric_value(
        metric="vrh", unit="hours", period_start=JUNE[0], period_end=JUNE[1],
        value=Decimal("1190.10"), calc_name="vrh_v0", calc_version="0.4.0",
        computed_at=dt.datetime(2026, 7, 2, 11, 0, tzinfo=UTC),
    )
    return v3, v4, june


def _compare(client, fake_db, params):
    return client.get(
        "/metrics/compare", params=params, headers=auth_header(fake_db, "vera")
    )


def test_version_comparison_exact_deltas_and_verbatim_cells(client, fake_db):
    v3, v4, _ = _seed_versions(fake_db)
    r = _compare(
        client,
        fake_db,
        {
            "metric": "vrh",
            "comparand": [
                f"{JULY_KEY}@vrh_v0:0.3.0",
                f"{JULY_KEY}@vrh_v0:0.4.0",
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["metric"] == "vrh"
    assert body["unit"] == "hours"
    assert [c["baseline"] for c in body["comparands"]] == [True, False]
    assert body["comparands"][0]["calc_version"] == "0.3.0"
    (row,) = body["rows"]
    assert row["scope"] == "agency"
    base_cell, other_cell = row["cells"]
    # The cell is the FULL verbatim metric-value row: the receipt affordance
    # (metric_value_id) and provenance fields all travel.
    assert base_cell["value"]["metric_value_id"] == v3["metric_value_id"]
    assert base_cell["value"]["value"] == "1300.00"
    assert other_cell["value"]["metric_value_id"] == v4["metric_value_id"]
    # Hand-worked: 1260.85 - 1300.00 = -39.15, exactly.
    assert other_cell["delta_vs_baseline"] == "-39.15"
    assert other_cell["delta_vs_previous"] == "-39.15"
    assert base_cell["delta_vs_baseline"] is None  # the baseline itself
    # No direction is registered for vrh; coverage's registered direction
    # travels for the detail subline (calc registry, not per-view).
    assert body["directions"] == {
        "vrh": None,
        "coverage": "higher_is_better",
    }
    assert "sign-neutral" in body["direction_note"]
    assert "not reported figures" in body["delta_note"]


def test_period_comparison_with_missing_cell_reason(client, fake_db):
    _seed_versions(fake_db)
    r = _compare(
        client,
        fake_db,
        {
            "metric": "vrh",
            "comparand": [
                JUNE_KEY,
                JULY_KEY,
                "2026-05-01..2026-06-01",  # no May figure exists
            ],
        },
    )
    assert r.status_code == 200
    (row,) = r.json()["rows"]
    june_cell, july_cell, may_cell = row["cells"]
    assert june_cell["value"]["value"] == "1190.10"
    # July unpinned picks the LATEST row (0.4.0, computed later) — the mr20
    # latest-per-cell discipline.
    assert july_cell["value"]["calc_version"] == "0.4.0"
    # Hand-worked: 1260.85 - 1190.10 = 70.75.
    assert july_cell["delta_vs_baseline"] == "70.75"
    assert may_cell["value"] is None
    assert may_cell["delta_vs_baseline"] is None
    assert "never invented" in may_cell["missing_reason"]
    assert "2026-05-01" in may_cell["missing_reason"]


def test_scope_rows_default_to_scopes_present_agency_first(client, fake_db):
    _seed_versions(fake_db)
    fake_db.add_metric_value(
        metric="vrh", unit="hours", period_start=JULY[0], period_end=JULY[1],
        value=Decimal("900.00"), calc_name="vrh_v0", calc_version="0.4.0",
        scope="mode:bus",
        computed_at=dt.datetime(2026, 8, 2, 11, 0, tzinfo=UTC),
    )
    r = _compare(
        client,
        fake_db,
        {"metric": "vrh", "comparand": [JUNE_KEY, JULY_KEY]},
    )
    assert [row["scope"] for row in r.json()["rows"]] == ["agency", "mode:bus"]
    # Explicit scope selection narrows the rows.
    r = _compare(
        client,
        fake_db,
        {
            "metric": "vrh",
            "comparand": [JUNE_KEY, JULY_KEY],
            "scope": ["mode:bus"],
        },
    )
    assert [row["scope"] for row in r.json()["rows"]] == ["mode:bus"]


def test_mixed_certification_is_flagged_both_sides_labeled(client, fake_db):
    fake_db.add_metric_value(
        metric="vrm", unit="miles", period_start=JUNE[0], period_end=JUNE[1],
        value=Decimal("100.00"), certification_status="certified",
    )
    fake_db.add_metric_value(
        metric="vrm", unit="miles", period_start=JULY[0], period_end=JULY[1],
        value=Decimal("120.00"), certification_status="uncertified",
    )
    r = _compare(
        client, fake_db, {"metric": "vrm", "comparand": [JUNE_KEY, JULY_KEY]}
    )
    body = r.json()
    assert body["mixed_certification"] is True
    assert "label both" in body["mixed_certification_note"]
    statuses = [
        c["value"]["certification_status"] for c in body["rows"][0]["cells"]
    ]
    assert statuses == ["certified", "uncertified"]


def test_ops_rows_compare_with_category_carried(client, fake_db):
    fake_db.add_metric_value(
        metric="otp", unit="percent", period_start=JUNE[0], period_end=JUNE[1],
        value=Decimal("52.10"), calc_name="otp_v0", calc_version="0.1.0",
        category="ops",
    )
    fake_db.add_metric_value(
        metric="otp", unit="percent", period_start=JULY[0], period_end=JULY[1],
        value=Decimal("54.10"), calc_name="otp_v0", calc_version="0.1.0",
        category="ops",
    )
    r = _compare(
        client, fake_db, {"metric": "otp", "comparand": [JUNE_KEY, JULY_KEY]}
    )
    body = r.json()
    (row,) = body["rows"]
    assert all(c["value"]["category"] == "ops" for c in row["cells"])
    assert row["cells"][1]["delta_vs_baseline"] == "2.00"
    assert body["directions"]["otp"] is None  # deliberately unregistered


def test_comparand_count_bounds(client, fake_db):
    _seed_versions(fake_db)
    r = _compare(client, fake_db, {"metric": "vrh", "comparand": [JULY_KEY]})
    assert r.status_code == 422
    assert "between 2 and 4" in r.json()["detail"]
    five = [f"2026-0{m}-01..2026-0{m + 1}-01" for m in range(1, 6)]
    r = _compare(client, fake_db, {"metric": "vrh", "comparand": five})
    assert r.status_code == 422


def test_comparand_syntax_refusals_are_plain_language(client, fake_db):
    cases = [
        ("2026-07-01", "no '..'"),
        ("2026-07-01..not-a-date", "ISO dates"),
        ("2026-08-01..2026-07-01", "half-open"),
        (f"{JULY_KEY}@vrh_v0", "calc_name"),
    ]
    for bad, fragment in cases:
        r = _compare(
            client, fake_db, {"metric": "vrh", "comparand": [bad, JUNE_KEY]}
        )
        assert r.status_code == 422, bad
        assert fragment in r.json()["detail"], (bad, r.json()["detail"])
    # Duplicate comparands refuse too.
    r = _compare(
        client, fake_db, {"metric": "vrh", "comparand": [JULY_KEY, JULY_KEY]}
    )
    assert r.status_code == 422
    assert "identical" in r.json()["detail"]


def test_compare_requires_authentication(client):
    assert (
        client.get(
            "/metrics/compare",
            params={"metric": "vrh", "comparand": [JUNE_KEY, JULY_KEY]},
        ).status_code
        == 401
    )


def test_latest_row_wins_within_a_cell(client, fake_db):
    """Two rows for the same (metric, scope, period, calc): the newer
    computed_at is the cell; history stays untouched underneath."""
    fake_db.add_metric_value(
        metric="upt", unit="trips", period_start=JULY[0], period_end=JULY[1],
        value=Decimal("100"), calc_name="upt_v0", calc_version="0.1.0",
        computed_at=dt.datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
    )
    newer = fake_db.add_metric_value(
        metric="upt", unit="trips", period_start=JULY[0], period_end=JULY[1],
        value=Decimal("101"), calc_name="upt_v0", calc_version="0.1.0",
        computed_at=dt.datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
    )
    fake_db.add_metric_value(
        metric="upt", unit="trips", period_start=JUNE[0], period_end=JUNE[1],
        value=Decimal("90"), calc_name="upt_v0", calc_version="0.1.0",
    )
    r = _compare(
        client, fake_db, {"metric": "upt", "comparand": [JUNE_KEY, JULY_KEY]}
    )
    cell = r.json()["rows"][0]["cells"][1]
    assert cell["value"]["metric_value_id"] == newer["metric_value_id"]
    assert cell["value"]["value"] == "101"
    assert cell["delta_vs_baseline"] == "11"
