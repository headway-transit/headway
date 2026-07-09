"""CLI process boundary for the calc runner: ``python -m headway_calc.runner``.

This module — and ONLY this module — touches the process environment
(HEADWAY_DATABASE_URL), argv, and the database driver. It contains no
calculation logic and is exempt from the stdlib-purity guardrail test
(tests/test_purity.py) for exactly that reason; everything it calls
(headway_calc.runner and below) remains deterministic and stdlib-only.

The psycopg import is guarded: unit tests (and any environment without the
driver) can import this module freely; only an actual live run requires
``pip install 'headway-calc[persist]'``.
"""

from __future__ import annotations

import argparse
import os
from datetime import date
from decimal import Decimal

from headway_calc.runner import run_period


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m headway_calc.runner",
        description=(
            "Run vrm_v0/vrh_v0 over one half-open period [period-start, "
            "period-end) (UTC) against the database named by "
            "HEADWAY_DATABASE_URL, and print the RunReport as JSON."
        ),
    )
    parser.add_argument(
        "--period-start",
        type=date.fromisoformat,
        required=True,
        help="Period start DATE (inclusive), e.g. 2026-06-01.",
    )
    parser.add_argument(
        "--period-end",
        type=date.fromisoformat,
        required=True,
        help="Period end DATE (exclusive), e.g. 2026-07-01.",
    )
    parser.add_argument(
        "--gap-threshold-seconds",
        type=float,
        default=None,
        help=(
            "Override the telemetry-gap threshold (default: the library "
            "default, 300s). The value used is recorded in the RunReport."
        ),
    )
    parser.add_argument(
        "--coverage-threshold",
        type=Decimal,
        default=None,
        help=(
            "Override the coverage certifiability threshold (default: the "
            "library default, 0.95 — an engineering placeholder, not an FTA "
            "number; see REGULATORY_TRACKER.md). A run whose "
            "clean-group coverage falls below it is blocked (one "
            "coverage_below_threshold dq issue, nothing persisted). The "
            "value used is recorded in the RunReport."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    database_url = os.environ.get("HEADWAY_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "HEADWAY_DATABASE_URL is not set. Refusing to guess a connection "
            "string — set it to the agency database URL and re-run."
        )

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover — driver-less environments
        raise SystemExit(
            "The psycopg driver is required for a live run but is not "
            "installed. Install it with: pip install 'headway-calc[persist]'"
        ) from exc

    with psycopg.connect(database_url) as conn:
        report = run_period(
            conn,
            period_start=args.period_start,
            period_end=args.period_end,
            gap_threshold_seconds=args.gap_threshold_seconds,
            coverage_threshold=args.coverage_threshold,
        )

    print(report.to_json())
    return 0
