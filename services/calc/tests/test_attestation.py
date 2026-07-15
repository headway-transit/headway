"""headway_calc.attestation — scope matching, governing selection, and the
handoff-0019 HARD LIMITS in their structural form.

The hard limits (handoff 0019, design point A.3):

1. An attestation can never unblock sampling undersampling — the manual is
   explicit: "However, agencies must not collect a smaller sample than the
   chosen sampling plan prescribes." (2026 NTD Policy Manual, Full
   Reporting, p. 149 — quoted in REGULATORY_TRACKER.md, "Verified —
   statistician attestations"). Pinned here structurally: NOTHING in the
   sampling module accepts an attestation.
2. Never touches simulated flags — pinned in test_upt_attestation.py /
   test_pmt_attestation.py (the flag stands on an attested run).
3. Never applies outside its declared scope — pinned here
   (applicable_attestations) and at the calc boundary (wrong metric raises).
4. Never affects ops metrics — pinned here structurally: nothing in the ops
   module or the ops runner accepts an attestation.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timezone

import pytest

from headway_calc.attestation import (
    ATTESTABLE_METRICS,
    P146_ATTESTATION_BASIS,
    P149_NO_SMALLER_SAMPLE,
    AttestationContext,
    applicable_attestations,
    governing_attestation,
)


def _att(**overrides) -> AttestationContext:
    base = dict(
        attestation_id="att-1",
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


# --- the verbatim quotes the feature stands on -------------------------------


def test_p146_basis_is_the_verbatim_statistician_sentence():
    assert P146_ATTESTATION_BASIS == (
        "However, if the vehicle trips with missing data exceed 2 percent "
        "of total trips, agencies must have a qualified statistician "
        "approve the factoring method used to account for the missing "
        "percentage."
    )


def test_p149_hard_limit_quote_is_verbatim():
    assert P149_NO_SMALLER_SAMPLE == (
        "However, agencies must not collect a smaller sample than the "
        "chosen sampling plan prescribes."
    )


# --- context validation -------------------------------------------------------


def test_metric_vocabulary_is_upt_and_pmt_only():
    assert ATTESTABLE_METRICS == ("upt", "pmt")
    with pytest.raises(ValueError, match="must be one of"):
        _att(metric="vrm")
    with pytest.raises(ValueError, match="must be one of"):
        _att(metric="otp")  # an ops metric can never even be constructed


def test_empty_or_inverted_period_refused():
    with pytest.raises(ValueError, match="half-open"):
        _att(period_start=date(2026, 7, 2), period_end=date(2026, 7, 2))
    with pytest.raises(ValueError, match="half-open"):
        _att(period_start=date(2026, 7, 2), period_end=date(2026, 7, 1))


def test_provenance_dict_is_json_safe_and_carries_the_basis():
    prov = _att().to_provenance_dict()
    assert prov["attestation_id"] == "att-1"
    assert prov["basis"] == P146_ATTESTATION_BASIS
    assert prov["period_start"] == "2026-07-01"
    assert all(isinstance(v, str) for v in prov.values())


# --- scope matching (hard limit 3) --------------------------------------------


def test_scope_pattern_matches_exact_and_fnmatch():
    assert _att(scope_pattern="agency").matches_scope("agency")
    assert not _att(scope_pattern="agency").matches_scope("mode:bus")
    assert _att(scope_pattern="mode:bus").matches_scope("mode:bus")
    assert _att(scope_pattern="mode:DR:tos:*").matches_scope("mode:DR:tos:TX")
    assert not _att(scope_pattern="mode:DR:tos:*").matches_scope("mode:DR")
    assert _att(scope_pattern="*").matches_scope("agency")
    # Case-sensitive: 'mode:dr' is not 'mode:DR' (the scope namespaces are
    # deliberately case-distinct — runner.py SCOPE_MODE_DR).
    assert not _att(scope_pattern="mode:dr").matches_scope("mode:DR")


def test_period_must_cover_the_whole_run_period():
    att = _att()  # covers [2026-07-01, 2026-08-01)
    assert att.covers_period(date(2026, 7, 9), date(2026, 7, 10))
    assert att.covers_period(date(2026, 7, 1), date(2026, 8, 1))
    # Partial cover is no cover.
    assert not att.covers_period(date(2026, 6, 30), date(2026, 7, 2))
    assert not att.covers_period(date(2026, 7, 31), date(2026, 8, 2))


def test_applicable_attestations_filters_metric_scope_period_revocation():
    run = dict(
        metric="upt",
        scope="agency",
        period_start=date(2026, 7, 9),
        period_end=date(2026, 7, 10),
    )
    good = _att()
    wrong_metric = _att(attestation_id="att-pmt", metric="pmt")
    wrong_scope = _att(attestation_id="att-bus", scope_pattern="mode:bus")
    wrong_period = _att(
        attestation_id="att-old",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
    )
    revoked = _att(
        attestation_id="att-revoked",
        revoked_at=datetime(2026, 7, 11, tzinfo=timezone.utc),
    )
    selected = applicable_attestations(
        [wrong_metric, wrong_scope, wrong_period, revoked, good], **run
    )
    assert selected == (good,)


def test_applicable_attestations_orders_by_entered_at_then_id():
    later = _att(
        attestation_id="att-a",
        entered_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    earlier = _att(
        attestation_id="att-z",
        entered_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
    )
    tie = _att(
        attestation_id="att-b",
        entered_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    selected = applicable_attestations(
        [later, earlier, tie],
        "upt",
        "agency",
        date(2026, 7, 9),
        date(2026, 7, 10),
    )
    assert [a.attestation_id for a in selected] == ["att-z", "att-a", "att-b"]


# --- governing selection (the calc boundary) ----------------------------------


def test_governing_attestation_earliest_entered_wins_and_revoked_skipped():
    a = _att(
        attestation_id="a", entered_at=datetime(2026, 7, 12, tzinfo=timezone.utc)
    )
    b = _att(
        attestation_id="b", entered_at=datetime(2026, 7, 9, tzinfo=timezone.utc)
    )
    r = _att(
        attestation_id="r",
        entered_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        revoked_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )
    assert governing_attestation([a, b, r], "upt").attestation_id == "b"
    assert governing_attestation([r], "upt") is None
    assert governing_attestation([], "upt") is None


def test_governing_attestation_wrong_metric_raises():
    with pytest.raises(ValueError, match="never applies outside"):
        governing_attestation([_att(metric="pmt")], "upt")


# --- HARD LIMITS 1 and 4, structural form --------------------------------------


def test_hard_limit_no_attestation_input_anywhere_in_sampling():
    """p. 149: 'agencies must not collect a smaller sample than the chosen
    sampling plan prescribes.' — there is no statistician cure for
    undersampling, so NO callable in headway_calc.sampling accepts an
    attestation in any spelling."""
    import headway_calc.sampling as sampling

    for name in dir(sampling):
        obj = getattr(sampling, name)
        if callable(obj) and not inspect.isclass(obj):
            try:
                params = inspect.signature(obj).parameters
            except (TypeError, ValueError):
                continue
            assert not any("attest" in p.lower() for p in params), (
                f"headway_calc.sampling.{name} accepts an attestation "
                f"parameter — the p. 149 hard limit forbids any "
                f"statistician cure for undersampling"
            )


def test_hard_limit_no_attestation_input_in_ops_calcs_or_ops_runner():
    """Hard limit 4: operations metrics never see an attestation."""
    import headway_calc.ops as ops
    from headway_calc.runner import run_ops_period

    assert not any(
        "attest" in p.lower()
        for p in inspect.signature(run_ops_period).parameters
    )
    for name in dir(ops):
        obj = getattr(ops, name)
        if callable(obj) and not inspect.isclass(obj):
            try:
                params = inspect.signature(obj).parameters
            except (TypeError, ValueError):
                continue
            assert not any("attest" in p.lower() for p in params), (
                f"headway_calc.ops.{name} accepts an attestation parameter"
            )


def test_hard_limit_no_attestation_input_in_vrm_vrh_voms_dr():
    """The p. 146 rule is a UPT/PMT 100%-count rule: no other NTD calc
    accepts an attestation either."""
    import headway_calc.dr as dr
    import headway_calc.voms as voms
    import headway_calc.vrh as vrh
    import headway_calc.vrm as vrm

    for module in (vrm, vrh, voms, dr):
        for name in dir(module):
            obj = getattr(module, name)
            if callable(obj) and not inspect.isclass(obj):
                try:
                    params = inspect.signature(obj).parameters
                except (TypeError, ValueError):
                    continue
                assert not any("attest" in p.lower() for p in params), (
                    f"{module.__name__}.{name} accepts an attestation "
                    f"parameter"
                )
