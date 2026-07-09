"""Core value types for the calculation library.

All types are frozen (immutable) dataclasses: calculations are pure functions
over immutable inputs and produce immutable results. Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class VehiclePosition:
    """One canonical vehicle position (read contract: canonical.vehicle_positions).

    ``time`` MUST be timezone-aware UTC event time (the vehicle timestamp from
    the feed, never ingest time). ``trip_id`` is None when the position is
    unassigned — v0 calculations treat trip assignment as the revenue-service
    proxy and simply exclude unassigned positions (documented approximation).
    ``source_record_id`` is the content-addressed raw record id this position
    derives from; it feeds the lineage graph (ADR-0007).
    """

    time: datetime
    vehicle_id: str
    trip_id: str | None
    latitude: float
    longitude: float
    source_record_id: str

    def __post_init__(self) -> None:
        if self.time.tzinfo is None or self.time.utcoffset() is None:
            raise ValueError(
                f"VehiclePosition.time must be timezone-aware UTC; got naive "
                f"datetime {self.time!r} (source_record_id={self.source_record_id!r})"
            )
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(
                f"latitude {self.latitude!r} out of range [-90, 90] "
                f"(source_record_id={self.source_record_id!r})"
            )
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValueError(
                f"longitude {self.longitude!r} out of range [-180, 180] "
                f"(source_record_id={self.source_record_id!r})"
            )


@dataclass(frozen=True)
class BlockingIssue:
    """A blocking data-quality issue.

    The presence of any BlockingIssue on a CalcResult means the calculation
    REFUSED to emit a value (value is None). Maps onto dq.issues with
    severity='blocking'. ``source_record_ids`` identifies the raw records
    bounding/causing the issue.
    """

    issue_type: str
    title: str
    description: str
    source_record_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CalcResult:
    """The output of one calculation run.

    ``value`` is a Decimal (never float) — or None when ``blocking_issues`` is
    non-empty: a calculation never emits a certifiable value over an unresolved
    gap. ``input_record_ids`` lists the source_record_ids actually consumed,
    in deterministic order — these feed lineage.edges (one edge per id).
    """

    value: Decimal | None
    unit: str
    calc_name: str
    calc_version: str
    input_record_ids: tuple[str, ...]
    blocking_issues: tuple[BlockingIssue, ...]

    def __post_init__(self) -> None:
        if self.blocking_issues and self.value is not None:
            raise ValueError(
                "CalcResult invariant violated: a result with blocking issues "
                "must have value=None (never a guessed number)"
            )
        if self.value is not None and not isinstance(self.value, Decimal):
            raise TypeError(
                f"CalcResult.value must be Decimal or None, got {type(self.value).__name__}"
            )
