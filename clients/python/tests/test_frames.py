"""DataFrame helpers: provenance columns ALWAYS present, figures exact."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from headway_client import HeadwayClient, frames
from conftest import MACHINE_KEY, SESSION_TOKEN, VRM_ID


@pytest.fixture()
def values(transport):
    with HeadwayClient("http://fake", token=MACHINE_KEY, transport=transport) as hw:
        return hw.metric_values()


def test_metric_values_frame_always_carries_provenance(values):
    df = frames.metric_values_frame(values)
    # THE binding rule (handoff 0018): provenance columns are not opt-in.
    for column in frames.PROVENANCE_COLUMNS:
        assert column in df.columns, f"provenance column {column} missing"
    assert list(df["metric_value_id"])[0] == VRM_ID


def test_metric_values_frame_has_no_kwarg_to_drop_provenance():
    import inspect

    signature = inspect.signature(frames.metric_values_frame)
    assert list(signature.parameters) == ["values"], (
        "metric_values_frame must take no option that omits provenance — "
        "dropping provenance is the caller's explicit act"
    )


def test_values_are_exact_decimals_never_float(values):
    df = frames.metric_values_frame(values)
    vrm_value = df.loc[df["metric"] == "vrm", "value"].iloc[0]
    assert isinstance(vrm_value, Decimal)
    assert vrm_value == Decimal("12794.92")
    # Decimal arithmetic on the column stays exact.
    total = df.loc[df["category"] == "ntd", "value"].sum()
    assert total == Decimal("12794.92") + Decimal("185321")


def test_simulated_and_source_mix_columns(values):
    df = frames.metric_values_frame(values).set_index("metric")
    assert bool(df.loc["upt", "simulated"]) is True
    assert df.loc["upt", "source_mix"] == {"tides_simulated": 185321}
    assert bool(df.loc["vrm", "simulated"]) is False
    assert df.loc["vrm", "source_mix"] is None


def test_empty_input_still_yields_provenance_columns():
    df = frames.metric_values_frame([])
    assert df.empty
    for column in frames.PROVENANCE_COLUMNS:
        assert column in df.columns


def test_dq_issues_frame_nullable_minutes(transport):
    with HeadwayClient("http://fake", token=SESSION_TOKEN, transport=transport) as hw:
        issues = hw.dq_issues()
    df = frames.dq_issues_frame(issues)
    assert str(df["resolution_minutes"].dtype) == "Int64"
    assert pd.isna(df["resolution_minutes"].iloc[0])  # unmeasured stays <NA>
    assert df["resolution_minutes"].iloc[1] == 12  # measured stays integer


def test_lineage_frame_one_row_per_node(transport):
    with HeadwayClient("http://fake", token=MACHINE_KEY, transport=transport) as hw:
        trail = hw.walk_lineage(VRM_ID)
    df = frames.lineage_frame(trail)
    assert len(df) == 6
    assert list(df.columns) == [
        "depth", "kind", "id", "transform_name", "transform_version",
        "parent_kind", "parent_id",
    ]
    assert df.iloc[0]["depth"] == 0
    assert df.iloc[0]["kind"] == "computed.metric_values"
    assert (df[df["kind"] == "raw.records"]["transform_name"].isna()).all()


def test_lineage_frame_rejects_non_trail_input():
    with pytest.raises(TypeError) as excinfo:
        frames.lineage_frame("not a trail")
    assert "walk its lineage first" in str(excinfo.value)


def test_compare_frame_provenance_and_missing_reasons(transport):
    with HeadwayClient("http://fake", token=SESSION_TOKEN, transport=transport) as hw:
        cmp = hw.compare(
            "vrh",
            ["2026-07-01..2026-08-01", "2026-06-01..2026-07-01"],
            scopes=["agency", "mode:bus"],
        )
    df = frames.compare_frame(cmp)
    for column in frames.PROVENANCE_COLUMNS:
        assert column in df.columns
    assert len(df) == 4  # 2 scopes x 2 comparands
    agency = df[df["scope"] == "agency"]
    assert agency["value"].iloc[0] == Decimal("1260.85")
    assert agency["delta_vs_baseline"].iloc[1] == Decimal("-70.75")
    bus = df[df["scope"] == "mode:bus"]
    assert bus["value"].isna().all()
    assert bus["missing_reason"].str.contains("never invented").all()
