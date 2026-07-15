"""upt_v0 0.2.0 — the statistician-attestation factor-up path (handoff 0019)
and its regression pins.

The binding rules under test:

- WITHOUT an applicable attestation, the >2% refusal stands BYTE-FOR-BYTE
  as 0.1.0's (value None, identical finding, identical detail JSON) — the
  retained compute_upt_v0_1_0 is the oracle.
- WITH one, the figure is factored deterministically (the SAME arithmetic
  as the ≤2% branch), carries the attestation provenance in the detail
  permanently, and one info finding quotes p. 146 verbatim and names the
  attestation.
- The ≤2% branch ignores attestations entirely (byte-identical output).
- Hard limit 2: simulated-source flags stand on an attested run.
- Hard limit 3 at the calc boundary: a non-'upt' attestation raises;
  revoked attestations never govern.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from headway_calc.attestation import (
    P146_ATTESTATION_BASIS,
    AttestationContext,
)
from headway_calc.types import PassengerEvent
from headway_calc.upt import (
    BOARDING_EVENT_TYPE,
    compute_upt,
    compute_upt_v0_1_0,
)

T0 = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
SERVICE_DATE = date(2026, 7, 9)


def boarding(pe_id, trip, count, second, source="tides"):
    return PassengerEvent(
        event_timestamp=T0.replace(second=second % 60, minute=second // 60),
        service_date=SERVICE_DATE,
        passenger_event_id=pe_id,
        vehicle_id="veh-1",
        trip_id=trip,
        trip_stop_sequence=1,
        event_type=BOARDING_EVENT_TYPE,
        event_count=count,
        source=source,
        source_record_id=f"rec-{pe_id}",
    )


def attestation(**overrides) -> AttestationContext:
    base = dict(
        attestation_id="att-42",
        statistician_name="Dr. R. Fisher",
        statistician_credentials="PhD statistics; 12 years transit sampling",
        method_description="Route-stratified expansion factoring",
        document_reference="dms://approvals/2026/upt-factoring.pdf",
        metric="upt",
        scope_pattern="agency",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 8, 1),
        entered_by="certifier",
        entered_at=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
        revoked_at=None,
    )
    base.update(overrides)
    return AttestationContext(**base)


#: 10 boardings on ONE of TEN operated trips: 9/10 missing = share 0.9,
#: far beyond the 2% line — the refusal scenario.
EVENTS = [boarding("1", "trip-1", 10, 0)]
OPERATED = [f"trip-{i}" for i in range(1, 11)]


def test_without_attestation_refusal_is_byte_for_byte_0_1_0():
    new = compute_upt(EVENTS, OPERATED)
    old = compute_upt_v0_1_0(EVENTS, OPERATED)
    assert new.calc_version == "0.2.0"
    assert old.calc_version == "0.1.0"
    # Everything except the version string is byte-identical — the 0.2.0
    # change is strictly additive.
    assert dataclasses.replace(new, calc_version="x") == dataclasses.replace(
        old, calc_version="x"
    )
    assert new.value is None
    assert [f.issue_type for f in new.blocking_issues] == [
        "apc_missing_trips_above_fta_threshold"
    ]
    assert new.detail.to_dict() == old.detail.to_dict()
    assert "attestation" not in new.detail.to_dict()


def test_with_attestation_factors_up_with_provenance_and_info_finding():
    result = compute_upt(EVENTS, OPERATED, attestations=(attestation(),))
    # The SAME deterministic arithmetic as the ≤2% branch:
    # 10 counted × 10/(10−9) = 100 boardings.
    assert result.value == Decimal("100")
    assert result.blocking_issues == ()
    assert result.calc_version == "0.2.0"
    detail = result.detail.to_dict()
    assert detail["factor_applied"] == "10.000000"
    assert detail["missing_share"] == "0.9000"
    prov = detail["attestation"]
    assert prov["attestation_id"] == "att-42"
    assert prov["statistician_name"] == "Dr. R. Fisher"
    assert prov["method_description"] == "Route-stratified expansion factoring"
    assert prov["document_reference"] == "dms://approvals/2026/upt-factoring.pdf"
    assert prov["basis"] == P146_ATTESTATION_BASIS
    # ONE info finding: the receipt sentence + the p. 146 verbatim quote +
    # the attestation details.
    attested = [
        f
        for f in result.infos
        if f.issue_type == "apc_missing_trips_attested_factor_up"
    ]
    assert len(attested) == 1
    finding = attested[0]
    assert finding.severity == "info"
    assert (
        "Factored beyond the 2% threshold under a statistician-approved "
        "method — attestation #att-42" in finding.title
    )
    assert P146_ATTESTATION_BASIS in finding.description
    assert "Dr. R. Fisher" in finding.description


def test_revoked_attestation_never_governs_refusal_stands():
    revoked = attestation(
        revoked_at=datetime(2026, 7, 11, tzinfo=timezone.utc)
    )
    result = compute_upt(EVENTS, OPERATED, attestations=(revoked,))
    baseline = compute_upt(EVENTS, OPERATED)
    assert result == baseline
    assert result.value is None


def test_wrong_metric_attestation_raises_never_silently_honored():
    with pytest.raises(ValueError, match="never applies outside"):
        compute_upt(EVENTS, OPERATED, attestations=(attestation(metric="pmt"),))


def test_below_threshold_branch_ignores_attestations_byte_for_byte():
    # 50 operated, events for 49: share 1/50 = 0.02 ≤ threshold — the
    # ordinary factor-up; an attestation changes NOTHING here.
    events = [boarding(str(i), f"trip-{i}", 2, i) for i in range(1, 50)]
    operated = [f"trip-{i}" for i in range(1, 51)]
    with_att = compute_upt(events, operated, attestations=(attestation(),))
    without = compute_upt(events, operated)
    assert with_att == without
    assert with_att.value == Decimal("100")  # 98 × 50/49 = 100
    assert "attestation" not in with_att.detail.to_dict()


def test_hard_limit_simulated_flags_stand_on_attested_run():
    simulated = [boarding("1", "trip-1", 10, 0, source="tides_simulated")]
    result = compute_upt(simulated, OPERATED, attestations=(attestation(),))
    assert result.value == Decimal("100")  # factored — the attestation works
    flags = [f for f in result.infos if f.issue_type == "simulated_source_data"]
    assert len(flags) == 1  # ...but the simulated flag stands untouched
    assert result.detail.to_dict()["source_mix"] == {"tides_simulated": 1}


def test_earliest_entered_applicable_attestation_governs():
    early = attestation(
        attestation_id="att-early",
        entered_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )
    late = attestation(
        attestation_id="att-late",
        entered_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    result = compute_upt(EVENTS, OPERATED, attestations=(late, early))
    assert result.detail.to_dict()["attestation"]["attestation_id"] == "att-early"


def test_retained_0_1_0_never_factors_beyond_threshold():
    """compute_upt_v0_1_0 has no attestation surface at all — the retained
    version is the pre-0019 behavior forever."""
    import inspect

    assert "attestations" not in inspect.signature(
        compute_upt_v0_1_0
    ).parameters
    assert compute_upt_v0_1_0(EVENTS, OPERATED).value is None
