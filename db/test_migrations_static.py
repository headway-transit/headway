"""Static checks on db/migrations — no live database required.

Verifies the migration set against the schema contract v0
(docs/handoffs/0001-from-platform-architect-to-all-canonical-schema-v0.md).
"""

import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Every table named in the handoff contract.
CONTRACT_TABLES = [
    "raw.records",
    "canonical.routes",
    "canonical.trips",
    "canonical.vehicle_positions",
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


def test_vehicle_positions_is_hypertable_with_unique_index():
    sql = all_sql()
    assert "create_hypertable('canonical.vehicle_positions', 'time')" in sql
    assert re.search(
        r"CREATE UNIQUE INDEX\s+\w+\s+ON canonical\.vehicle_positions\s*"
        r'\(vehicle_id, "time", source_record_id\)',
        sql,
    ), "unique index (vehicle_id, time, source_record_id) missing"


def test_immutability_triggers_present():
    sql = all_sql()
    assert re.search(r"BEFORE UPDATE OR DELETE ON raw\.records", sql)
    assert re.search(r"BEFORE UPDATE OR DELETE ON audit\.events", sql)
    assert sql.count("RAISE EXCEPTION") >= 2
