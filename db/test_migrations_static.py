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


def test_immutability_triggers_present():
    sql = all_sql()
    assert re.search(r"BEFORE UPDATE OR DELETE ON raw\.records", sql)
    assert re.search(r"BEFORE UPDATE OR DELETE ON audit\.events", sql)
    assert sql.count("RAISE EXCEPTION") >= 2
