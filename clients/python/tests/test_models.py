"""Pure model behavior — parsing and the honesty story's presence."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import headway_client
from headway_client import models
from conftest import METRIC_VALUES


def test_metric_value_parses_dates_and_keeps_value_verbatim():
    v = models.MetricValue.from_json(METRIC_VALUES[0])
    assert v.period_start == dt.date(2026, 7, 9)
    assert v.period_end == dt.date(2026, 7, 11)
    assert v.computed_at.tzinfo is not None  # Z suffix parsed as UTC-aware
    assert v.value == "12794.92"
    assert v.value_decimal == Decimal("12794.92")


def test_null_detail_becomes_empty_dict_never_invented():
    raw = dict(METRIC_VALUES[0], detail=None)
    v = models.MetricValue.from_json(raw)
    assert v.detail == {}
    assert v.source_mix is None
    assert v.simulated is False


def test_simulated_rule_is_case_insensitive_substring():
    raw = dict(
        METRIC_VALUES[0], detail={"source_mix": {"DR_Simulated": 95, "dr": 5}}
    )
    assert models.MetricValue.from_json(raw).simulated is True


def test_honesty_story_verbatim_in_library_docstrings():
    """The honesty story must read identically everywhere it appears
    (handoff 0018): the constant IS the canonical text, and the package,
    client, models, and frames docstrings carry it verbatim."""
    story = headway_client.HONESTY_STORY
    assert story.startswith("Explore and compute freely:")
    assert "structural database CHECKs, not policy" in story

    from headway_client import client, frames

    def normalized(docstring: str) -> str:
        return " ".join(docstring.split())

    for module in (headway_client, client, models, frames):
        assert story in normalized(module.__doc__), (
            f"{module.__name__} docstring must carry the honesty story verbatim"
        )
    assert story in normalized(client.HeadwayClient.__doc__)
