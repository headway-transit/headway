"""Shared test helpers: golden fixture loading."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from headway_calc.types import VehiclePosition

# services/calc/tests/conftest.py -> repo root is parents[3]
GOLDEN_DIR = Path(__file__).resolve().parents[3] / "tests" / "golden" / "vrm_vrh_v0"


def load_positions(raw: dict) -> list[VehiclePosition]:
    return [
        VehiclePosition(
            time=datetime.fromisoformat(p["time"]),
            vehicle_id=p["vehicle_id"],
            trip_id=p["trip_id"],
            latitude=p["latitude"],
            longitude=p["longitude"],
            source_record_id=p["source_record_id"],
        )
        for p in raw["positions"]
    ]


@pytest.fixture(scope="session")
def golden_fixture() -> dict:
    return json.loads((GOLDEN_DIR / "fixture.json").read_text())


@pytest.fixture(scope="session")
def golden_expected() -> dict:
    return json.loads((GOLDEN_DIR / "expected.json").read_text())
