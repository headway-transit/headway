"""Per-agency settings (migration 0014): any signed-in role reads, only the
certifying official writes, values validated against value_type (Decimal —
never float), old→new in the audit detail, unknown key 404 (seeded, never
client-creatable)."""

import json

from conftest import auth_header

SEEDED = {
    # (value, value_type, seeding migration)
    "coverage_threshold": ("0.95", "decimal", "migration:0014"),
    "gap_threshold_seconds": ("300", "integer", "migration:0014"),
    "layover_max_seconds": ("1800", "integer", "migration:0014"),
    "missing_trip_threshold": ("0.02", "decimal", "migration:0014"),
    # Branding keys (migration 0015, handoff 0008 pillar C).
    "agency_display_name": ("Transit Agency", "text", "migration:0015"),
    "brand_color_primary": ("#1a5fb4", "text", "migration:0015"),
    "brand_color_accent": ("#0b57d0", "text", "migration:0015"),
    "brand_logo_meta": ("unset", "text", "migration:0015"),
    # Themed chrome keys (migration 0027, handoff 0017 design point 7).
    "brand_chrome_header_bg": ("unset", "text", "migration:0027"),
    "brand_chrome_header_fg": ("unset", "text", "migration:0027"),
    "brand_chrome_accent": ("unset", "text", "migration:0027"),
}


def test_any_signed_in_role_reads_the_seeded_settings(client, fake_db):
    r = client.get("/settings", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    rows = {s["setting_key"]: s for s in r.json()}
    assert set(rows) == set(SEEDED)
    for key, (value, value_type, seeded_by) in SEEDED.items():
        assert rows[key]["setting_value"] == value
        assert isinstance(rows[key]["setting_value"], str)  # never a JSON number
        assert rows[key]["value_type"] == value_type
        assert rows[key]["description"]  # plain-language basis, never empty
        assert rows[key]["updated_by"] == seeded_by
    # The placeholder is flagged as such; the FTA basis is cited.
    assert "PLACEHOLDER" in rows["coverage_threshold"]["description"]
    assert "p. 146" in rows["missing_trip_threshold"]["description"]


def test_unauthenticated_read_is_401(client):
    assert client.get("/settings").status_code == 401


def test_update_requires_certifying_official(client, fake_db):
    for username in ("vera", "stella", "petra"):
        r = client.put(
            "/settings/coverage_threshold",
            json={"value": "0.90"},
            headers=auth_header(fake_db, username),
        )
        assert r.status_code == 403, username
    # Nothing changed, nothing audited.
    assert fake_db.settings["coverage_threshold"]["setting_value"] == "0.95"
    assert fake_db.audit_events == []


def test_certifying_official_updates_and_old_new_is_audited(client, fake_db):
    r = client.put(
        "/settings/coverage_threshold",
        json={"value": "0.90"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["setting_value"] == "0.90"
    assert body["updated_by"] == "cora"
    assert body["audit_event_id"] == 1
    assert fake_db.settings["coverage_threshold"]["setting_value"] == "0.90"
    events = [e for e in fake_db.audit_events if e["action"] == "setting_updated"]
    assert len(events) == 1
    assert events[0]["actor"] == "cora"
    assert events[0]["subject_kind"] == "app.settings"
    assert events[0]["subject_id"] == "coverage_threshold"
    detail = json.loads(events[0]["detail"])
    assert detail == {
        "old_value": "0.95",
        "new_value": "0.90",
        "value_type": "decimal",
    }
    # The change is visible on the next read.
    read = client.get("/settings", headers=auth_header(fake_db, "vera"))
    rows = {s["setting_key"]: s for s in read.json()}
    assert rows["coverage_threshold"]["setting_value"] == "0.90"
    assert rows["coverage_threshold"]["updated_by"] == "cora"


def test_decimal_setting_rejects_non_decimal_with_plain_language_422(
    client, fake_db
):
    for bad in ("not-a-number", "0.9O", "NaN", "Infinity"):
        r = client.put(
            "/settings/coverage_threshold",
            json={"value": bad},
            headers=auth_header(fake_db, "cora"),
        )
        assert r.status_code == 422, bad
        assert "not a decimal number" in r.json()["detail"]
        assert "coverage_threshold" in r.json()["detail"]
    assert fake_db.settings["coverage_threshold"]["setting_value"] == "0.95"
    assert fake_db.audit_events == []  # a refused change leaves no trace to audit


def test_integer_setting_rejects_non_integer_with_plain_language_422(
    client, fake_db
):
    for bad in ("300.5", "five minutes"):
        r = client.put(
            "/settings/gap_threshold_seconds",
            json={"value": bad},
            headers=auth_header(fake_db, "cora"),
        )
        assert r.status_code == 422, bad
        assert "not a whole number" in r.json()["detail"]
    assert fake_db.settings["gap_threshold_seconds"]["setting_value"] == "300"


def test_unknown_key_is_404_settings_are_not_client_creatable(client, fake_db):
    r = client.put(
        "/settings/brand_new_knob",
        json={"value": "1"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 404
    assert "cannot be created" in r.json()["detail"]
    assert "brand_new_knob" not in fake_db.settings
