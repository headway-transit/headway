"""Static checks on db/migrations — no live database required.

Verifies the migration set against the schema contract v0
(docs/handoffs/0001-from-platform-architect-to-all-canonical-schema-v0.md).
"""

import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Every table named in the handoff contract (0001; canonical.passenger_events
# added by handoff 0005 / migration 0012).
CONTRACT_TABLES = [
    "raw.records",
    "canonical.routes",
    "canonical.trips",
    "canonical.vehicle_positions",
    "canonical.passenger_events",
    "computed.metric_values",
    "lineage.edges",
    "dq.issues",
    "audit.events",
    "cert.certifications",
]


def migration_files():
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert files, f"no migrations found in {MIGRATIONS_DIR}"
    return files


def all_sql():
    return "\n".join(f.read_text(encoding="utf-8") for f in migration_files())


def test_filenames_sequential_and_unique():
    files = migration_files()
    numbers = []
    for f in files:
        match = re.fullmatch(r"(\d{4})_[a-z0-9_]+\.sql", f.name)
        assert match, f"bad migration filename: {f.name}"
        numbers.append(int(match.group(1)))
    assert len(numbers) == len(set(numbers)), f"duplicate migration numbers: {numbers}"
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"migration numbers not sequential from 0001: {numbers}"
    )


def test_all_contract_tables_created():
    sql = all_sql()
    for table in CONTRACT_TABLES:
        assert re.search(
            rf"CREATE TABLE\s+{re.escape(table)}\b", sql
        ), f"contract table {table} not created by any migration"


def test_no_tenant_id():
    # ADR-0004: one database per agency, no tenant_id anywhere.
    for f in migration_files():
        assert "tenant_id" not in f.read_text(encoding="utf-8").lower(), (
            f"tenant_id found in {f.name} (forbidden by ADR-0004)"
        )


def test_no_drop_table():
    for f in migration_files():
        assert "drop table" not in f.read_text(encoding="utf-8").lower(), (
            f"DROP TABLE found in {f.name} (forbidden in v0 migrations)"
        )


def test_metric_value_is_numeric_not_float():
    sql = all_sql()
    match = re.search(r"value\s+NUMERIC\s+NOT NULL", sql)
    assert match, "computed.metric_values.value must be NUMERIC NOT NULL"


def test_metric_values_detail_jsonb_not_null_default_empty():
    # Handoff 0002 / migration 0010: calc-0.2.0 coverage detail column.
    sql = all_sql()
    assert re.search(
        r"ALTER TABLE\s+computed\.metric_values\s+"
        r"ADD COLUMN\s+detail\s+JSONB\s+NOT NULL\s+DEFAULT\s+'\{\}'::jsonb",
        sql,
    ), "computed.metric_values.detail must be added as JSONB NOT NULL DEFAULT '{}'::jsonb"


def test_trips_block_id_added_nullable_text():
    # Handoff 0003 / migration 0011: GTFS block_id for block-aware VRH (calc
    # v0.3). Nullable TEXT — block_id is optional per the GTFS spec, so no
    # NOT NULL and no default.
    sql = all_sql()
    match = re.search(
        r"ALTER TABLE\s+canonical\.trips\s+ADD COLUMN\s+block_id\s+TEXT\s*;",
        sql,
    )
    assert match, "canonical.trips.block_id must be added as nullable TEXT"
    assert not re.search(r"block_id\s+TEXT\s+NOT NULL", sql), (
        "canonical.trips.block_id must stay nullable (optional per GTFS)"
    )


def test_vehicle_positions_is_hypertable_with_unique_index():
    sql = all_sql()
    assert "create_hypertable('canonical.vehicle_positions', 'time')" in sql
    assert re.search(
        r"CREATE UNIQUE INDEX\s+\w+\s+ON canonical\.vehicle_positions\s*"
        r'\(vehicle_id, "time", source_record_id\)',
        sql,
    ), "unique index (vehicle_id, time, source_record_id) missing"


def test_passenger_events_hypertable_unique_key_and_columns():
    # Handoff 0005 / migration 0012: TIDES passenger events (slice 2 UPT).
    sql = all_sql()
    assert "create_hypertable('canonical.passenger_events', 'event_timestamp')" in sql
    assert re.search(
        r"CREATE UNIQUE INDEX\s+\w+\s+ON canonical\.passenger_events\s*"
        r"\(passenger_event_id, event_timestamp, source_record_id\)",
        sql,
    ), "unique index (passenger_event_id, event_timestamp, source_record_id) missing"
    # Column checks scoped to the 0012 file (raw.records also has a 'source'
    # column, so matching the concatenated SQL would prove nothing).
    sql_0012 = (MIGRATIONS_DIR / "0012_passenger_events.sql").read_text(
        encoding="utf-8"
    )
    assert re.search(r"source\s+TEXT NOT NULL", sql_0012), (
        "canonical.passenger_events.source must be TEXT NOT NULL (simulated "
        "data permanently distinguishable, handoff 0005)"
    )
    assert re.search(
        r"source_record_id\s+TEXT NOT NULL REFERENCES raw\.records",
        sql_0012,
    ), "canonical.passenger_events.source_record_id must reference raw.records"
    # event_count NULL preserved — never coalesced, so no NOT NULL, no default.
    assert re.search(r"event_count\s+INTEGER\s*,", sql_0012), (
        "canonical.passenger_events.event_count must be nullable INTEGER "
        "with no default (NULL preserved, never coalesced)"
    )
    assert not re.search(r"event_count\s+INTEGER\s+(NOT NULL|DEFAULT)", sql_0012), (
        "canonical.passenger_events.event_count must stay nullable with no default"
    )


def test_machine_api_keys_hashed_at_rest_and_soft_revoked():
    # Handoff 0006 / migration 0013: service-account keys. The key is stored
    # only as a SHA-256 hash (never plaintext), identified by a short prefix,
    # and revoked softly (never deleted — audit history).
    sql = all_sql()
    assert re.search(r"CREATE TABLE\s+auth\.api_keys\b", sql), (
        "auth.api_keys not created by any migration"
    )
    sql_0013 = (MIGRATIONS_DIR / "0013_machine_api.sql").read_text(encoding="utf-8")
    assert re.search(r"key_hash\s+TEXT NOT NULL UNIQUE", sql_0013), (
        "auth.api_keys.key_hash must be TEXT NOT NULL UNIQUE (hash-at-rest)"
    )
    assert re.search(r"key_prefix\s+TEXT NOT NULL", sql_0013)
    assert re.search(r"scopes\s+TEXT\[\] NOT NULL", sql_0013)
    assert re.search(r"revoked_at\s+TIMESTAMPTZ", sql_0013), (
        "auth.api_keys must soft-revoke via revoked_at (keys never deleted)"
    )
    assert "key_plaintext" not in sql_0013 and not re.search(
        r"\bkey\s+TEXT", sql_0013
    ), "auth.api_keys must never have a plaintext key column"


def test_machine_api_webhook_subscriptions_with_documented_secret_risk():
    # Handoff 0006 / migration 0013: webhook subscriptions. The HMAC secret is
    # plaintext BY DOCUMENTED DESIGN (it must be read back to sign) — the
    # migration must carry the risk note and the compensating control.
    sql = all_sql()
    assert re.search(r"CREATE TABLE\s+auth\.webhook_subscriptions\b", sql), (
        "auth.webhook_subscriptions not created by any migration"
    )
    sql_0013 = (MIGRATIONS_DIR / "0013_machine_api.sql").read_text(encoding="utf-8")
    assert re.search(r"secret\s+TEXT NOT NULL", sql_0013)
    assert re.search(r"event_types\s+TEXT\[\] NOT NULL", sql_0013)
    assert "DOCUMENTED RISK" in sql_0013 and "COMPENSATING CONTROL" in sql_0013, (
        "0013 must document the plaintext webhook-secret risk and its "
        "compensating control (handoff 0006, design point 7)"
    )


def test_app_settings_seeded_with_calc_policy_knobs():
    # Handoff 0002 open question / migration 0014: per-agency calc policy.
    # Keys are SEEDED (never client-creatable), values are TEXT typed by a
    # CHECK-constrained value_type, and every row carries a plain-language
    # description with the basis of its default.
    sql = all_sql()
    assert re.search(r"CREATE TABLE\s+app\.settings\b", sql), (
        "app.settings not created by any migration"
    )
    sql_0014 = (MIGRATIONS_DIR / "0014_app_settings.sql").read_text(encoding="utf-8")
    assert re.search(r"setting_key\s+TEXT PRIMARY KEY", sql_0014)
    assert re.search(r"setting_value\s+TEXT NOT NULL", sql_0014)
    assert re.search(
        r"value_type\s+TEXT NOT NULL CHECK \(value_type IN "
        r"\('decimal', 'integer', 'text'\)\)",
        sql_0014,
    ), "app.settings.value_type must be CHECK-constrained to decimal/integer/text"
    assert re.search(r"description\s+TEXT NOT NULL", sql_0014), (
        "every setting must carry a plain-language description"
    )
    assert re.search(r"updated_by\s+TEXT NOT NULL", sql_0014)
    # The four calc policy knobs, seeded with the calc library's defaults.
    for key, default in (
        ("coverage_threshold", "0.95"),
        ("gap_threshold_seconds", "300"),
        ("layover_max_seconds", "1800"),
        ("missing_trip_threshold", "0.02"),
    ):
        assert re.search(
            rf"'{key}',\s*'{re.escape(default)}',", sql_0014
        ), f"app.settings must seed {key} = {default}"
    # Basis citations: placeholders flagged as such, the FTA number cited.
    assert "ENGINEERING PLACEHOLDER" in sql_0014, (
        "coverage_threshold's description must flag the 0.95 placeholder"
    )
    assert "p. 146" in sql_0014, (
        "missing_trip_threshold's description must cite the FTA basis (p. 146)"
    )


def test_branding_settings_seeded_with_contrast_guardrail():
    # Handoff 0008 pillar C / migration 0015: agency branding keys. Seeded
    # (never client-creatable), all 'text', descriptions in plain language and
    # carrying the guardrail promise — colors that fail accessibility contrast
    # are refused, at the published WCAG AA line, on both app surfaces.
    sql_0015 = (MIGRATIONS_DIR / "0015_branding_settings.sql").read_text(
        encoding="utf-8"
    )
    for key, default in (
        ("agency_display_name", "Transit Agency"),
        ("brand_color_primary", "#1a5fb4"),
        ("brand_color_accent", "#0b57d0"),
        ("brand_logo_meta", "unset"),
    ):
        assert re.search(
            rf"'{key}',\s*'{re.escape(default)}',\s*'text',", sql_0015
        ), f"0015 must seed {key} = {default} as a 'text' setting"
    # The guardrail promise, the AA line, and both surfaces are documented.
    assert "colors that fail accessibility contrast are refused" in sql_0015, (
        "0015 must carry the guardrail promise in plain language"
    )
    assert "4.5:1" in sql_0015 and "WCAG" in sql_0015, (
        "0015 must cite the WCAG AA 4.5:1 line the guardrail enforces"
    )
    assert "#ffffff" in sql_0015 and "#f6f8fa" in sql_0015, (
        "0015 must name both app surfaces the guardrail checks against"
    )
    # brand_logo_meta is system-maintained, and the description says so.
    assert "POST /branding/logo" in sql_0015


def test_dq_resolution_minutes_nullable_nonnegative_no_default():
    # Migration 0016: optional resolution effort on dq.issues. Nullable
    # INTEGER (recording effort is optional; existing resolutions have no
    # measurement — never invented), CHECK >= 0, and NO default (an
    # unmeasured resolution must read as NULL, not as zero minutes).
    sql_0016 = (MIGRATIONS_DIR / "0016_dq_effort.sql").read_text(encoding="utf-8")
    assert re.search(
        r"ALTER TABLE\s+dq\.issues\s+"
        r"ADD COLUMN\s+resolution_minutes\s+INTEGER",
        sql_0016,
    ), "dq.issues.resolution_minutes must be added as INTEGER"
    assert re.search(r"CHECK \(resolution_minutes >= 0\)", sql_0016), (
        "dq.issues.resolution_minutes must carry CHECK (resolution_minutes >= 0)"
    )
    statements = "\n".join(
        line for line in sql_0016.splitlines() if not line.lstrip().startswith("--")
    )
    assert "NOT NULL" not in statements, (
        "dq.issues.resolution_minutes must stay nullable (effort is optional)"
    )
    assert "DEFAULT" not in statements.upper(), (
        "dq.issues.resolution_minutes must have no default (unmeasured is "
        "NULL, never zero)"
    )


def test_stops_and_stop_times_preserve_nulls():
    # Handoff 0011 / migration 0019: GTFS stop geometry for PMT distances.
    # stops.latitude/longitude nullable (GTFS requires coordinates only for
    # location_type 0/1/2); stop_times.shape_dist_traveled NULLABLE and
    # preserved — a feed that omits it stays NULL, a distance is never
    # fabricated; GTFS-native identity (trip_id, stop_sequence).
    sql = all_sql()
    assert re.search(r"CREATE TABLE\s+canonical\.stops\b", sql), (
        "canonical.stops not created by any migration"
    )
    assert re.search(r"CREATE TABLE\s+canonical\.stop_times\b", sql), (
        "canonical.stop_times not created by any migration"
    )
    sql_0019 = (MIGRATIONS_DIR / "0019_stops_stop_times.sql").read_text(
        encoding="utf-8"
    )
    statements = "\n".join(
        line
        for line in sql_0019.splitlines()
        if not line.lstrip().startswith("--")
    )
    # Nullable coordinates: DOUBLE PRECISION with no NOT NULL, no default.
    assert re.search(r"latitude\s+DOUBLE PRECISION\s*,", statements)
    assert re.search(r"longitude\s+DOUBLE PRECISION\s*$", statements, re.M)
    assert not re.search(
        r"(latitude|longitude)\s+DOUBLE PRECISION\s+(NOT NULL|DEFAULT)",
        statements,
    ), "canonical.stops coordinates must stay nullable with no default"
    # shape_dist_traveled: nullable, no default — NULL preserved, never
    # fabricated (handoff 0011, binding).
    assert re.search(
        r"shape_dist_traveled\s+DOUBLE PRECISION\s*,", statements
    ), "canonical.stop_times.shape_dist_traveled must be DOUBLE PRECISION"
    assert not re.search(
        r"shape_dist_traveled\s+DOUBLE PRECISION\s+(NOT NULL|DEFAULT)",
        statements,
    ), "shape_dist_traveled must stay nullable with no default"
    assert re.search(
        r"PRIMARY KEY \(trip_id, stop_sequence\)", statements
    ), "canonical.stop_times identity must be (trip_id, stop_sequence)"
    # The design rationale must be carried in the migration itself.
    assert "NEVER fabricated" in sql_0019 or "never fabricated" in sql_0019
    assert "haversine" in sql_0019, (
        "0019 must document the pmt_v0 haversine fallback the NULL feeds"
    )


def test_immutability_triggers_present():
    sql = all_sql()
    assert re.search(r"BEFORE UPDATE OR DELETE ON raw\.records", sql)
    assert re.search(r"BEFORE UPDATE OR DELETE ON audit\.events", sql)
    assert sql.count("RAISE EXCEPTION") >= 2


def test_safety_events_append_only_with_supersede_link():
    # Handoff 0010 / migration 0017: Safety & Security events. Corrections
    # are append-only — a corrected event points at its replacement via
    # superseded_by; originals are never deleted (structural trigger, not
    # policy prose). Counts have sane bounds; damage stays nullable (a
    # missing figure is never coalesced to $0).
    sql = all_sql()
    assert re.search(r"CREATE TABLE\s+safety\.events\b", sql), (
        "safety.events not created by any migration"
    )
    sql_0017 = (MIGRATIONS_DIR / "0017_safety_events.sql").read_text(
        encoding="utf-8"
    )
    assert re.search(r"CREATE SCHEMA IF NOT EXISTS safety", sql_0017)
    assert re.search(r"occurred_at\s+TIMESTAMPTZ NOT NULL", sql_0017)
    assert re.search(r"mode\s+TEXT NOT NULL", sql_0017)
    assert re.search(r"narrative\s+TEXT NOT NULL", sql_0017)
    # The manual's event vocabulary, CHECK-constrained.
    for category in (
        "collision", "derailment", "fire", "evacuation", "security",
        "assault", "cyber", "other",
    ):
        assert f"'{category}'" in sql_0017, (
            f"event_category CHECK must include {category!r}"
        )
    assert re.search(r"CHECK \(fatalities >= 0\)", sql_0017)
    assert re.search(r"CHECK \(injuries >= 0\)", sql_0017)
    # Damage nullable NUMERIC (never float, never defaulted to 0).
    assert re.search(
        r"property_damage_usd\s+NUMERIC CHECK \(property_damage_usd >= 0\)",
        sql_0017,
    ), "property_damage_usd must be nullable NUMERIC with a >= 0 CHECK"
    assert re.search(
        r"superseded_by\s+UUID REFERENCES safety\.events", sql_0017
    ), "superseded_by must reference safety.events (append-only correction)"
    assert re.search(r"BEFORE UPDATE OR DELETE ON safety\.events", sql_0017), (
        "safety.events needs the append-only trigger"
    )
    assert re.search(r"superseded_by <> event_id", sql_0017), (
        "an event must never supersede itself"
    )


def test_safety_event_classifications_append_only_classifier_written():
    # Handoff 0010 / migration 0017: classifications are written ONLY by the
    # deterministic classifier (sscls_v0) and are append-only history —
    # 'major' exactly when >= 1 threshold met (one report per event, p. 14).
    sql_0017 = (MIGRATIONS_DIR / "0017_safety_events.sql").read_text(
        encoding="utf-8"
    )
    assert re.search(r"CREATE TABLE\s+safety\.event_classifications\b", sql_0017)
    assert re.search(
        r"classification\s+TEXT NOT NULL CHECK \(classification IN\s*"
        r"\('major', 'non_major', 'not_reportable'\)\)",
        sql_0017,
    )
    assert re.search(r"thresholds_met\s+TEXT\[\] NOT NULL", sql_0017)
    assert re.search(r"classifier_version\s+TEXT NOT NULL", sql_0017)
    assert re.search(
        r"\(classification = 'major'\) = \(cardinality\(thresholds_met\) > 0\)",
        sql_0017,
    ), "major must hold exactly when at least one threshold was met"
    assert re.search(
        r"BEFORE UPDATE OR DELETE ON safety\.event_classifications", sql_0017
    ), "safety.event_classifications needs the append-only trigger"
    assert "written ONLY by the deterministic classifier" in sql_0017, (
        "0017 must document the only-writer rule for classifications"
    )


def test_safety_events_runaway_and_row_evacuation_fields():
    # Handoff 0010 correction round / migration 0018: the p. 17 runaway-
    # train and evacuation-to-controlled-ROW rules (tracker S&S addendum)
    # need capture fields. Booleans, NOT NULL DEFAULT false (explicit
    # yes/no questions at entry; honest backfill), and the migration must
    # note that the 0017 to_jsonb append-only trigger covers new columns
    # automatically.
    sql_0018 = (
        MIGRATIONS_DIR / "0018_safety_runaway_evacuation.sql"
    ).read_text(encoding="utf-8")
    assert re.search(
        r"ADD COLUMN\s+runaway_train\s+BOOLEAN NOT NULL DEFAULT false",
        sql_0018,
    ), "safety.events.runaway_train must be BOOLEAN NOT NULL DEFAULT false"
    assert re.search(
        r"ADD COLUMN\s+evacuation_to_rail_row\s+BOOLEAN NOT NULL DEFAULT false",
        sql_0018,
    ), (
        "safety.events.evacuation_to_rail_row must be BOOLEAN NOT NULL "
        "DEFAULT false"
    )
    assert "uncommanded, uncontrolled, or unmanned" in sql_0018, (
        "0018 must carry the p. 17 runaway-train quote basis"
    )
    assert "controlled rail right-of-way" in sql_0018, (
        "0018 must carry the p. 17 rail-evacuation quote basis"
    )
    assert "append-only trigger" in sql_0018, (
        "0018 must note the 0017 trigger covers the new columns"
    )


def test_sampling_plans_draws_measurements_append_only():
    # Handoff 0012 / migration 0020: NTD sampling plan support. Plans,
    # draws (seed + frame recorded for reproducibility, §63.03), and
    # measurements (append-only supersede corrections, the 0017 pattern).
    # Required sample sizes come from the versioned calc selector — the
    # migration must document that no regulatory number originates here.
    sql = all_sql()
    for table in ("sampling.plans", "sampling.draws", "sampling.measurements"):
        assert re.search(
            rf"CREATE TABLE\s+{re.escape(table)}\b", sql
        ), f"{table} not created by any migration"
    sql_0020 = (MIGRATIONS_DIR / "0020_sampling_plans.sql").read_text(
        encoding="utf-8"
    )
    assert re.search(r"CREATE SCHEMA IF NOT EXISTS sampling", sql_0020)
    # Plans: the ready-to-use vocabulary, CHECK-constrained; both required
    # sizes present; selector version recorded.
    for mode in ("DR", "VP", "MB", "TB", "CR", "LR", "HR", "MR", "AG"):
        assert f"'{mode}'" in sql_0020, f"plans.mode CHECK must include {mode!r}"
    for unit in (
        "vehicle_days", "one_way_trips", "round_trips",
        "one_way_car_trips", "one_way_train_trips",
    ):
        assert f"'{unit}'" in sql_0020, f"plans.unit CHECK must include {unit!r}"
    assert re.search(
        r"required_per_period INTEGER NOT NULL CHECK \(required_per_period > 0\)",
        sql_0020,
    )
    assert re.search(
        r"required_annual\s+INTEGER NOT NULL CHECK \(required_annual > 0\)",
        sql_0020,
    )
    assert re.search(r"selector_version\s+TEXT NOT NULL", sql_0020)
    assert re.search(
        r"No\s+(-- )?regulatory number originates in the API or in this schema",
        sql_0020,
    ), "0020 must document that no regulatory number originates here"
    assert re.search(r"BEFORE UPDATE OR DELETE ON sampling\.plans", sql_0020), (
        "sampling.plans needs the append-only trigger"
    )
    # Draws: seed + frame + selection recorded, strictly append-only, one
    # draw per plan period, oversample flagged.
    assert re.search(r"service_units\s+TEXT\[\] NOT NULL", sql_0020)
    assert re.search(r"selected_units\s+TEXT\[\] NOT NULL", sql_0020)
    assert re.search(r"seed\s+TEXT NOT NULL CHECK \(length\(seed\) > 0\)", sql_0020)
    assert re.search(
        r"oversample_units INTEGER NOT NULL DEFAULT 0 CHECK \(oversample_units >= 0\)",
        sql_0020,
    )
    assert re.search(r"UNIQUE \(plan_id, period_label\)", sql_0020)
    assert re.search(r"BEFORE UPDATE OR DELETE ON sampling\.draws", sql_0020), (
        "sampling.draws needs the append-only trigger"
    )
    # Measurements: NUMERIC PMT (never float), supersede pattern, one active
    # observation per unit.
    assert re.search(
        r"observed_pmt\s+NUMERIC NOT NULL CHECK \(observed_pmt >= 0\)", sql_0020
    ), "observed_pmt must be NUMERIC (never float) with a >= 0 CHECK"
    assert re.search(
        r"observed_upt\s+INTEGER NOT NULL CHECK \(observed_upt >= 0\)", sql_0020
    )
    assert re.search(
        r"superseded_by\s+UUID REFERENCES sampling\.measurements", sql_0020
    ), "superseded_by must reference sampling.measurements (append-only correction)"
    assert re.search(
        r"REFERENCES sampling\.measurements \(measurement_id\)\s+"
        r"DEFERRABLE INITIALLY DEFERRED",
        sql_0020,
    ), (
        "superseded_by FK must be DEFERRABLE (link-then-insert under the "
        "one-active-per-unit index — 2026-07-12 live-walkthrough finding)"
    )
    assert re.search(r"superseded_by <> measurement_id", sql_0020), (
        "a measurement must never supersede itself"
    )
    assert re.search(
        r"CREATE UNIQUE INDEX\s+measurements_one_active_per_unit\s+"
        r"ON sampling\.measurements \(plan_id, unit_id\)\s+"
        r"WHERE superseded_by IS NULL",
        sql_0020,
    ), "exactly one active measurement per (plan, unit)"
    assert re.search(
        r"BEFORE UPDATE OR DELETE ON sampling\.measurements", sql_0020
    ), "sampling.measurements needs the append-only trigger"
    # Retention basis surfaced in the schema documentation.
    assert "p. 150" in sql_0020 and "3 years" in sql_0020, (
        "0020 must carry the documentation-retention basis"
    )


def test_dr_trips_hypertable_nulls_preserved_and_structural_checks():
    # Handoff 0013 / migration 0021: demand-response trips. Hypertable on
    # pickup_timestamp with the replay-idempotent unique key; NUMERIC (never
    # float) distances that stay NULLABLE with no default (unmeasured is
    # unmeasured, never coalesced); the wire contract's structural rules as
    # CHECKs (TOS enum, dropoff >= pickup, sponsor iff sponsored, no-show has
    # zero boardings); source column for the simulated-data rule.
    sql = all_sql()
    assert "create_hypertable('canonical.dr_trips', 'pickup_timestamp')" in sql
    assert re.search(
        r"CREATE UNIQUE INDEX\s+\w+\s+ON canonical\.dr_trips\s*"
        r"\(dr_trip_id, pickup_timestamp, source_record_id\)",
        sql,
    ), "unique index (dr_trip_id, pickup_timestamp, source_record_id) missing"
    sql_0021 = (MIGRATIONS_DIR / "0021_dr_trips.sql").read_text(encoding="utf-8")
    assert re.search(
        r"tos\s+TEXT NOT NULL CHECK \(tos IN \('DO', 'PT', 'TX', 'TN'\)\)",
        sql_0021,
    ), "canonical.dr_trips.tos must be CHECK-constrained to DO/PT/TX/TN"
    # Distances: NUMERIC, nullable, no default — NULL preserved, never 0.
    assert re.search(r"onboard_miles\s+NUMERIC CHECK", sql_0021)
    assert not re.search(r"onboard_miles\s+NUMERIC[^,]*(NOT NULL|DEFAULT)", sql_0021), (
        "onboard_miles must stay nullable with no default (unmeasured is a "
        "flagged gap, never a fabricated 0)"
    )
    assert not re.search(
        r"(onboard_miles|odometer_miles)\s+(REAL|FLOAT|DOUBLE)", sql_0021
    ), "distances must be NUMERIC, never float (repo non-negotiable)"
    # Structural contract rules.
    assert re.search(r"dropoff_timestamp >= pickup_timestamp", sql_0021)
    assert re.search(r"NOT no_show OR \(riders = 0 AND attendants_companions = 0\)", sql_0021), (
        "a no-show must carry zero boardings (revenue time yes, UPT no)"
    )
    assert "dr_trips_sponsor_iff_sponsored" in sql_0021
    assert re.search(
        r"interruption_after\s+TEXT NOT NULL DEFAULT 'none' CHECK", sql_0021
    ), "interruption_after must default 'none' with a CHECK enum"
    assert re.search(r"source\s+TEXT NOT NULL", sql_0021), (
        "canonical.dr_trips.source must be TEXT NOT NULL (simulated data "
        "permanently distinguishable)"
    )
    assert re.search(
        r"source_record_id\s+TEXT NOT NULL REFERENCES raw\.records", sql_0021
    ), "canonical.dr_trips.source_record_id must reference raw.records"
