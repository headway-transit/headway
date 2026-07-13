"""Hypothesis property tests for sampling_v0 0.1.0 (handoff 0012).

Drawer invariants (§63.03):

- REPRODUCIBILITY: the same (seed, frame, size) always yields the same
  selection in the same order;
- WITHOUT REPLACEMENT: the selection never contains a unit twice and is a
  subset of the frame — for every seed, frame, and size;
- FRAME-ORDER INDEPENDENCE: shuffling the frame changes nothing (the
  ordering is keyed by content, not position);
- SIZE: exactly ``sample_size`` units are selected;
- PREFIX CONSISTENCY: a smaller draw from the same seed+frame is a prefix
  of a larger one (the draw order is a total order over the frame) — this
  is what makes RANDOM OVERSAMPLING sound: extending a draw keeps every
  earlier selection and stays random.

Estimator invariants (§83.05(a) ratio of totals):

- PERMUTATION INVARIANCE: observation order never matters;
- MERGE INVARIANCE: splitting one unit's observation into two units with
  the same totals never changes the APTL — true of a ratio of TOTALS and
  provably FALSE of the §83.05(b)-banned average of ratios, so this
  property is the ban expressed as algebra;
- SCALE: estimated PMT == quantize(expansion x aptl) by definition.

Hypothesis is test-only — the library itself contains no randomness.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from headway_calc.sampling import (
    UnitObservation,
    draw_sample,
    estimate_annual_pmt,
    sample_aptl,
)

unit_ids = st.lists(
    st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126),
        min_size=1,
        max_size=12,
    ),
    min_size=1,
    max_size=40,
    unique=True,
)
seeds = st.text(min_size=1, max_size=32)


@st.composite
def frames_with_size(draw):
    frame = draw(unit_ids)
    size = draw(st.integers(min_value=1, max_value=len(frame)))
    return frame, size


@given(frames_with_size(), seeds)
@settings(max_examples=200)
def test_draw_reproducible_and_without_replacement(frame_size, seed):
    frame, size = frame_size
    first = draw_sample(frame, size, seed)
    second = draw_sample(frame, size, seed)
    assert first.selected_units == second.selected_units
    assert len(first.selected_units) == size
    # WITHOUT REPLACEMENT: no unit twice; every unit from the frame.
    assert len(set(first.selected_units)) == size
    assert set(first.selected_units) <= set(frame)


@given(frames_with_size(), seeds, st.randoms(use_true_random=False))
@settings(max_examples=100)
def test_draw_ignores_frame_order(frame_size, seed, rng):
    frame, size = frame_size
    shuffled = list(frame)
    rng.shuffle(shuffled)
    assert (
        draw_sample(frame, size, seed).selected_units
        == draw_sample(shuffled, size, seed).selected_units
    )


@given(frames_with_size(), seeds)
@settings(max_examples=100)
def test_smaller_draw_is_prefix_of_larger_draw(frame_size, seed):
    """The random-oversampling soundness property: drawing k then extending
    to k+m keeps the first k selections and their order."""
    frame, size = frame_size
    smaller = draw_sample(frame, size, seed)
    full = draw_sample(frame, len(frame), seed)
    assert full.selected_units[:size] == smaller.selected_units


observations = st.lists(
    st.builds(
        UnitObservation,
        unit_id=st.text(min_size=1, max_size=8),
        observed_upt=st.integers(min_value=0, max_value=500),
        observed_pmt=st.decimals(
            min_value=0, max_value=10_000, places=2, allow_nan=False
        ),
    ),
    min_size=1,
    max_size=30,
).filter(lambda obs: sum(o.observed_upt for o in obs) > 0)


@given(observations, st.randoms(use_true_random=False))
@settings(max_examples=100)
def test_aptl_is_permutation_invariant(obs, rng):
    shuffled = list(obs)
    rng.shuffle(shuffled)
    assert sample_aptl(obs) == sample_aptl(shuffled)


@given(observations, st.integers(min_value=0, max_value=len("x") * 20))
@settings(max_examples=100)
def test_aptl_is_merge_invariant_the_ban_as_algebra(obs, split_index):
    """Splitting any observation into two units with the same totals cannot
    change a ratio of TOTALS (§83.05(a)); it generally DOES change the
    banned average of per-unit ratios (§83.05(b)). Holding under arbitrary
    splits is therefore structural proof the estimator computes the former."""
    index = split_index % len(obs)
    target = obs[index]
    upt_half = target.observed_upt // 2
    pmt_half = (target.observed_pmt / 2).quantize(Decimal("0.01"))
    split = (
        obs[:index]
        + [
            UnitObservation(
                target.unit_id + "-a", upt_half, pmt_half
            ),
            UnitObservation(
                target.unit_id + "-b",
                target.observed_upt - upt_half,
                target.observed_pmt - pmt_half,
            ),
        ]
        + obs[index + 1 :]
    )
    assert sample_aptl(obs) == sample_aptl(split)


@given(
    observations,
    st.decimals(min_value="0.01", max_value=10_000_000, places=0, allow_nan=False),
)
@settings(max_examples=100)
def test_estimate_is_expansion_times_aptl_exactly(obs, upt_100):
    estimate = estimate_annual_pmt(obs, upt_100)
    assert estimate.sample_aptl == sample_aptl(obs)
    assert estimate.estimated_pmt == (upt_100 * estimate.sample_aptl).quantize(
        Decimal("1"), rounding=ROUND_HALF_EVEN
    )
    assert estimate.estimated_pmt >= 0
