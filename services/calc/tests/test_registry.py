"""The metric registry's direction metadata (handoff 0017, design point 1):
coverage — and ONLY coverage — registers a better/worse direction; every
reported metric is sign-neutral; unknown quantities are sign-neutral, never
guessed."""

from headway_calc.persist import _METRIC_BY_CALC_NAME
from headway_calc.registry import (
    HIGHER_IS_BETTER,
    QUANTITY_DIRECTIONS,
    direction_for,
)


def test_coverage_is_the_only_registered_direction():
    directed = {q for q, d in QUANTITY_DIRECTIONS.items() if d is not None}
    assert directed == {"coverage"}
    assert direction_for("coverage") == HIGHER_IS_BETTER


def test_every_persistable_metric_is_registered_sign_neutral():
    """Every metric the calc registry can persist has an explicit (None)
    registry row — expanding the metric set forces a deliberate direction
    decision here rather than an accidental omission."""
    for metric in set(_METRIC_BY_CALC_NAME.values()):
        assert metric in QUANTITY_DIRECTIONS
        assert direction_for(metric) is None


def test_unknown_quantity_is_sign_neutral():
    assert direction_for("something_new") is None
