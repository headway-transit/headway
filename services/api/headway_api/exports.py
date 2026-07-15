"""Tabular exports — CSV and XLSX from ONE row assembly (handoff 0017,
design point 5).

THE INVARIANT (pinned by test): for every export surface, the CSV and the
XLSX are generated from the same assembled grid, and every XLSX data cell is
written as a TEXT cell holding the byte-identical string the CSV holds.
Figures reach this module as the exact strings the API already serves
(NUMERIC → string; never float) and leave it untouched — this module applies
formatting (CSV quoting, workbook structure) and NEVER arithmetic, rounding,
or type coercion on a value. Text cells are the point: an Excel 'number'
cell is an IEEE double, which would silently corrupt an exact NUMERIC
figure; a text cell cannot.

Banner discipline: where the CSV leads with banner lines (NOT-REPORTABLE
banners, preview disclaimers, simulated-data warnings, caveats), the XLSX
carries the SAME lines as its FIRST sheet ("Read first"), one line per row,
ahead of the data sheet — a spreadsheet user meets the caveats before the
numbers, exactly like a CSV reader does.

openpyxl is MIT (ADR-0001 tier 1 permissive; recorded in pyproject.toml and
checked by scripts/license_gate.py like every dependency).
"""

from __future__ import annotations

import csv
import io
from typing import Iterable, Sequence

from fastapi import Response
from openpyxl import Workbook

#: The accepted values of every export endpoint's ``format`` query param.
FORMAT_PATTERN = "^(csv|xlsx)$"

#: Mirror of the web export's simulated cell (web/src/reports/csv.ts) — the
#: same words, so a simulated figure is equally unmissable in every format.
SIMULATED_CELL = "SIMULATED DATA - MUST NOT BE SUBMITTED"

#: Mirror of web/src/copy.ts copy.report.disclaimer — the Monthly Ridership
#: preview disclaimer the existing client-side CSV leads with.
METRICS_PREVIEW_DISCLAIMER = (
    "Preview only. The official NTD Monthly Ridership submission format has "
    "not yet been verified against FTA's reporting system documentation."
)

SIMULATED_BANNER = (
    "One or more rows below were computed from SIMULATED source data and "
    "are labeled in the simulated_data column. Simulated figures must never "
    "be submitted."
)

BANNER_SHEET_TITLE = "Read first"
DATA_SHEET_TITLE = "Data"

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"


class Grid:
    """One assembled export: banner lines + header + all-string rows."""

    def __init__(
        self,
        banner_lines: Sequence[str],
        header: Sequence[str],
        rows: Iterable[Sequence[str]],
    ):
        self.banner_lines = [str(line) for line in banner_lines]
        self.header = [str(h) for h in header]
        self.rows = [[self._cell(c) for c in row] for row in rows]
        for row in self.rows:
            if len(row) != len(self.header):
                raise ValueError(
                    f"Export row has {len(row)} cells but the header has "
                    f"{len(self.header)} — a ragged export would misalign "
                    f"values under the wrong columns."
                )

    @staticmethod
    def _cell(value) -> str:
        """Cells must already be strings (or None for an empty cell) —
        anything else is refused loudly rather than coerced, because
        coercion is where a figure could silently change."""
        if value is None:
            return ""
        if not isinstance(value, str):
            raise TypeError(
                f"Export cells must be strings (figures exactly as served); "
                f"got {type(value).__name__}: {value!r}"
            )
        return value


def grid_to_csv(grid: Grid) -> bytes:
    """CSV: banner lines first (one single-cell line each), then header,
    then rows. CRLF line endings and minimal quoting — the web export's
    conventions (web/src/reports/csv.ts)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    for line in grid.banner_lines:
        writer.writerow([line])
    writer.writerow(grid.header)
    for row in grid.rows:
        writer.writerow(row)
    return out.getvalue().encode("utf-8")


def grid_to_xlsx(grid: Grid) -> bytes:
    """XLSX: banner lines as the FIRST sheet (when any), data second. EVERY
    cell is a text cell — figures stay the exact strings the API serves."""
    wb = Workbook()
    data_sheet = wb.active
    if grid.banner_lines:
        data_sheet.title = BANNER_SHEET_TITLE
        for line in grid.banner_lines:
            data_sheet.append([line])
        data_sheet = wb.create_sheet(DATA_SHEET_TITLE)
    else:
        data_sheet.title = DATA_SHEET_TITLE
    data_sheet.append(grid.header)
    for row in grid.rows:
        # Empty string cells append as None in openpyxl; both read back as
        # "no content" — the CSV equality test normalizes both to "".
        data_sheet.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def export_response(grid: Grid, fmt: str, filename_stem: str) -> Response:
    """The one download response builder: same grid, either format, an
    attachment filename naming the surface and period."""
    if fmt == "csv":
        return Response(
            content=grid_to_csv(grid),
            media_type=CSV_MEDIA_TYPE,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename_stem}.csv"'
                )
            },
        )
    return Response(
        content=grid_to_xlsx(grid),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename_stem}.xlsx"'
            )
        },
    )


def is_simulated_detail(detail: dict) -> bool:
    """Mirror of web/src/detail.ts isSimulated: any source_mix key naming a
    simulated source marks the figure."""
    mix = detail.get("source_mix") if isinstance(detail, dict) else None
    if not isinstance(mix, dict):
        return False
    return any("simulated" in str(source).lower() for source in mix)


# ---------------------------------------------------------------------------
# Grid assemblies — one per export surface. Inputs are the EXACT objects the
# existing JSON surfaces serve (MetricValue models, the mr20/ss50 packages,
# the sampling progress payload); nothing is re-queried or re-derived here.
# ---------------------------------------------------------------------------

METRICS_VALUES_HEADER = (
    "metric",
    "unit",
    "period_start",
    "period_end",
    "scope",
    "value",
    "calc_name",
    "calc_version",
    "certification_status",
    "category",
    "simulated_data",
    "metric_value_id",
)


def metrics_values_grid(values) -> Grid:
    """GET /metrics/values as a grid: the web export's columns (web/src/
    reports/csv.ts CSV_HEADER) plus scope, category (the migration-0024
    honesty boundary) and metric_value_id (the provenance path — every
    exported figure names the row 'explain this number' starts from)."""
    any_simulated = any(is_simulated_detail(v.detail) for v in values)
    banner = [METRICS_PREVIEW_DISCLAIMER]
    if any_simulated:
        banner.append(SIMULATED_BANNER)
    rows = [
        [
            v.metric,
            v.unit,
            v.period_start.isoformat(),
            v.period_end.isoformat(),
            v.scope,
            v.value,  # VERBATIM — the exact string the API serves
            v.calc_name,
            v.calc_version,
            v.certification_status,
            v.category,
            SIMULATED_CELL if is_simulated_detail(v.detail) else "no",
            v.metric_value_id,
        ]
        for v in values
    ]
    return Grid(banner, METRICS_VALUES_HEADER, rows)


MR20_HEADER = (
    "scope",
    "metric",
    "value",
    "unit",
    "calc_name",
    "calc_version",
    "certification_status",
    "flags",
    "coverage",
    "non_reportable_pending_d2",
    "metric_value_id",
    "missing_reason",
)


def _mr20_rows_for_scope(scope_label: str, cells: dict, pending_d2: str):
    for metric in ("upt", "vrh", "vrm", "voms"):
        cell = cells.get(metric)
        if cell is None:
            continue
        if cell.get("value") is None:
            yield [
                scope_label, metric, "", "", "", "", "", "", "",
                pending_d2, "", cell.get("reason", ""),
            ]
        else:
            yield [
                scope_label,
                metric,
                cell["value"],  # VERBATIM package string
                cell.get("unit", ""),
                cell.get("calc_name", ""),
                cell.get("calc_version", ""),
                cell.get("certification_status", ""),
                "; ".join(cell.get("flags", [])),
                cell.get("coverage") or "",
                pending_d2,
                cell.get("metric_value_id", ""),
                "",
            ]


def mr20_grid(package: dict) -> Grid:
    """The headway_calc.mr20 package as a grid: its NOT-REPORTABLE banner
    and every programmatically enumerated caveat lead (banner lines / first
    sheet), then one row per (scope, metric) cell, values verbatim."""
    banner = [
        package["banner"],
        f"Form {package['form']} preview for {package['month']} "
        f"(period [{package['period_start']}, {package['period_end']}), "
        f"{package['period_convention']}).",
        f"Citation: {package['citation']}",
        f"Generated by {package['generator']['name']} "
        f"{package['generator']['version']}.",
    ]
    banner.extend(
        f"Caveat [{c['id']}, {c['status']}]: {c['text']}"
        for c in package["caveats"]
    )
    rows = list(_mr20_rows_for_scope("fleet", package["fleet"], ""))
    for mode in sorted(package["modes"]):
        entry = package["modes"][mode]
        pending = "yes" if entry.get("non_reportable_pending_d2") else "no"
        rows.extend(_mr20_rows_for_scope(f"mode:{mode}", entry, pending))
    return Grid(banner, MR20_HEADER, rows)


SS50_HEADER = (
    "mode",
    "type_of_service",
    "zero_event",
    "injury_events",
    "people_injured",
    "injury_event_ids",
    "non_major_fires",
    "fire_event_ids",
    "assaults_on_worker",
    "assaults_without_injury",
    "assault_event_ids",
)


def ss50_grid(package: dict) -> Grid:
    """The headway_calc.ss50 package as a grid: banner + citations + caveats
    + the excluded-event accounting lead; then one row per (mode, TOS) cell
    including the explicit zero rows."""
    banner = [
        package["banner"],
        f"Form {package['form']} preview for {package['month']} "
        f"(period [{package['period_start']}, {package['period_end']}), "
        f"{package['period_convention']}). Due date: {package['due_date']}.",
        f"Generated by {package['generator']['name']} "
        f"{package['generator']['version']}.",
    ]
    banner.extend(
        f"Citation [{c['id']}]: {c['text']} ({c['source']})"
        for c in package["citations"]
    )
    banner.extend(
        f"Caveat [{c['id']}]: {c['text']}" for c in package["caveats"]
    )
    excluded = package["excluded"]
    for label, key in (
        ("major (S&S-40, not counted here)", "major_event_ids"),
        ("not reportable", "not_reportable_event_ids"),
        ("superseded (replacement carries the truth)", "superseded_event_ids"),
        ("unclassified (classify and regenerate)", "unclassified_event_ids"),
    ):
        ids = excluded.get(key, [])
        if ids:
            banner.append(
                f"Excluded events — {label}: {', '.join(ids)}"
            )
    rows = []
    for cell in package["cells"]:
        counts = cell["counts"]
        rows.append(
            [
                cell["mode"],
                cell["type_of_service"],
                "yes" if cell["zero_event"] else "no",
                str(counts["injury_events"]["count"]),
                str(counts["injury_events"]["people_injured"]),
                "; ".join(counts["injury_events"]["event_ids"]),
                str(counts["non_major_fires"]["count"]),
                "; ".join(counts["non_major_fires"]["event_ids"]),
                str(counts["assaults_on_worker"]["count"]),
                str(counts["assaults_on_worker"]["without_injury"]),
                "; ".join(counts["assaults_on_worker"]["event_ids"]),
            ]
        )
    return Grid(banner, SS50_HEADER, rows)


SAMPLING_WORKSHEET_HEADER = (
    "period_label",
    "unit_id",
    "measured",
    "draw_oversample_units",
)


def sampling_worksheet_grid(
    plan, draws: list[dict], measured_unit_ids: set[str], retention_note: str
) -> Grid:
    """The sampling plan's measurement worksheet as a grid: one row per
    selected unit per draw (the same draw records GET /sampling/plans/{id}/
    progress summarizes), measured state from the plan's ACTIVE
    measurements; the plan's requirement, the undersampled/estimate-ready
    state and the retention note lead as banner lines."""
    measured_overall = len(measured_unit_ids)
    undersampled = measured_overall < plan.required_annual
    banner = [
        f"Sampling worksheet — plan {plan.plan_id}: report year "
        f"{plan.report_year}, mode {plan.mode}, TOS {plan.type_of_service}, "
        f"unit {plan.unit}, {plan.efficiency_option} option, "
        f"{plan.frequency} draws.",
        f"Required: {plan.required_per_period} per period, "
        f"{plan.required_annual} for the year ({plan.table_citation})",
        f"Measured so far: {measured_overall} of "
        f"{plan.required_annual} required — "
        + (
            "UNDERSAMPLED: the estimate is refused until every required "
            "unit is measured."
            if undersampled
            else "requirement met; the plan is estimate-ready."
        ),
        retention_note,
    ]
    rows = []
    for draw in draws:
        for unit in draw["selected_units"]:
            rows.append(
                [
                    draw["period_label"],
                    unit,
                    "yes" if unit in measured_unit_ids else "no",
                    str(draw["oversample_units"]),
                ]
            )
    return Grid(banner, SAMPLING_WORKSHEET_HEADER, rows)
