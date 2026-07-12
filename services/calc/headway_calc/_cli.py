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
            "Run vrm_v0/vrh_v0/upt_v0 over one half-open period "
            "[period-start, period-end) (UTC) against the database named by "
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
    parser.add_argument(
        "--layover-max-seconds",
        type=float,
        default=None,
        help=(
            "Override the maximum inter-trip interval counted as layover "
            "within a block for vrh_v0 0.4.0 (default: the library default, "
            "1800s — data-informed and exhibit-aligned per the measured "
            "inter-trip interval distribution and Exhibit 35's "
            "out-of-service exclusion; per-agency configurable; see "
            "REGULATORY_TRACKER.md). An over-cap interval "
            "is not counted and raises a layover_exceeds_max warning dq "
            "issue. The value used is recorded in the RunReport."
        ),
    )
    parser.add_argument(
        "--missing-trip-threshold",
        type=Decimal,
        default=None,
        help=(
            "Override the upt_v0 missing-trip share above which the run is "
            "blocked (default: the library default, 0.02 — the REAL FTA "
            "threshold, 2026 NTD Policy Manual p. 146: missing trips at 2 "
            "percent or less of the total are factored up deterministically; "
            "above it a qualified statistician must approve the factoring, so "
            "the calc refuses with one apc_missing_trips_above_fta_threshold "
            "dq issue). The value used is recorded in the RunReport."
        ),
    )
    parser.add_argument(
        "--imbalance-threshold",
        type=Decimal,
        default=None,
        help=(
            "Override the upt_v0 per-trip boarding/alighting imbalance share "
            "flagged as apc_count_imbalance (default: the library default, "
            "0.10 — the 2026 NTD Policy Manual p. 151 APC validation "
            "example: difference between boardings and alightings greater "
            "than 10 percent). The value used is recorded in the RunReport."
        ),
    )
    parser.add_argument(
        "--per-mode",
        action="store_true",
        help=(
            "Additionally compute voms_v0 and one mode-scoped result per "
            "metric per mode (computed.metric_values scope 'mode:<mode>', "
            "handoff 0009), alongside the unchanged fleet-wide 'agency' "
            "rows. Default OFF (the pre-0009 behavior); the MR-20 package "
            "path (python -m headway_calc.mr20 --run) turns it on — the "
            "MR-20 form requires the four data points per mode."
        ),
    )
    parser.add_argument(
        "--ignore-settings",
        action="store_true",
        help=(
            "Do NOT read app.settings (migration 0014): thresholds come from "
            "the explicit flags above, falling back to the calc library's "
            "code defaults (every threshold's source is recorded in the "
            "RunReport as 'explicit' or 'default', never 'settings'). For "
            "reproducing historical runs: per REGULATORY_TRACKER.md's rule "
            "('shipped versions are never deleted or rewritten'), a "
            "historical reproduction uses the PINNED calc versions plus the "
            "EXPLICIT thresholds recorded in the original RunReport — never "
            "whatever app.settings holds today. Without this flag, an "
            "app.settings row governs any threshold not given explicitly "
            "(explicit flag > settings row > code default)."
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
            layover_max_seconds=args.layover_max_seconds,
            missing_trip_threshold=args.missing_trip_threshold,
            imbalance_threshold=args.imbalance_threshold,
            read_settings=not args.ignore_settings,
            per_mode=args.per_mode,
        )

    print(report.to_json())
    return 0


def _parse_mr20_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m headway_calc.mr20",
        description=(
            "Assemble the NOT-REPORTABLE MR-20 preview package for one "
            "calendar month from computed.metric_values (latest row per "
            "metric+scope for the month's half-open period) and print it as "
            "JSON. The package mirrors the four MR-20 data points (UPT, "
            "VRH, VRM, VOMS) per mode plus fleet totals, every cell "
            "carrying provenance; missing cells are explicit nulls with a "
            "reason, never invented."
        ),
    )
    parser.add_argument(
        "--month",
        required=True,
        help="Calendar month YYYY-MM, e.g. 2026-07 (period [2026-07-01, 2026-08-01)).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help=(
            "First execute run_period over the month WITH per-mode scoping "
            "(the runner's --per-mode path: fleet + mode-scoped rows + "
            "voms_v0), then assemble the package from the freshly persisted "
            "rows. Thresholds resolve as in a plain run (app.settings row > "
            "code default). Without this flag the package is assembled from "
            "whatever computed.metric_values already holds."
        ),
    )
    return parser.parse_args(argv)


def mr20_main(argv: list[str] | None = None) -> int:
    """Process boundary for ``python -m headway_calc.mr20``."""
    import json

    from headway_calc.mr20 import build_mr20_package, month_period

    args = _parse_mr20_args(argv)

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
        if args.run:
            period_start, period_end = month_period(args.month)
            run_period(
                conn,
                period_start=period_start,
                period_end=period_end,
                per_mode=True,
            )
        package = build_mr20_package(conn, args.month)

    print(json.dumps(package, indent=2))
    return 0


def _parse_ss50_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m headway_calc.ss50",
        description=(
            "Assemble the NOT-REPORTABLE S&S-50 Non-Major Monthly Summary "
            "preview for one calendar month from safety.events + the latest "
            "sscls_v0 classification per event, and print it as JSON: "
            "per-mode/per-TOS non-major counts (injury-threshold events, "
            "non-major fires, assaults on transit workers including "
            "no-injury assaults) with per-cell provenance (event_ids), plus "
            "EXPLICIT ZERO ROWS for operated modes with no events (the "
            "manual's 'even if no event occurs' rule). With --ss40-event, "
            "print the S&S-40 detail export for one event instead (every "
            "met threshold's supporting fields; due date = occurred_at + "
            "30 days)."
        ),
    )
    parser.add_argument(
        "--month",
        help=(
            "Calendar month YYYY-MM, e.g. 2026-06 (period "
            "[2026-06-01, 2026-07-01), UTC, on occurred_at). Required "
            "unless --ss40-event is given."
        ),
    )
    parser.add_argument(
        "--ss40-event",
        metavar="EVENT_ID",
        help=(
            "Print the S&S-40 detail export for this safety.events id "
            "instead of the monthly S&S-50 package."
        ),
    )
    args = parser.parse_args(argv)
    if bool(args.month) == bool(args.ss40_event):
        parser.error(
            "give exactly one of --month YYYY-MM (S&S-50 package) or "
            "--ss40-event EVENT_ID (S&S-40 detail export)"
        )
    return args


def ss50_main(argv: list[str] | None = None) -> int:
    """Process boundary for ``python -m headway_calc.ss50``."""
    import json

    from headway_calc.ss50 import build_ss40_export, build_ss50_package

    args = _parse_ss50_args(argv)

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
        if args.ss40_event:
            package = build_ss40_export(conn, args.ss40_event)
        else:
            package = build_ss50_package(conn, args.month)

    print(json.dumps(package, indent=2))
    return 0
