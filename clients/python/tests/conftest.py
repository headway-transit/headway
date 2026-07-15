"""Test fixtures: a FAKE Headway API behind httpx.MockTransport.

No live dependency in unit tests (handoff 0018): the transport dispatches
on the exact paths, query parameters, and Authorization semantics the real
API implements (services/api routers — metrics, machine_read, public, dq,
auth), returning contract-shaped JSON. The one live smoke run happens in
the handoff evidence, never here.

The fake mirrors the API's credential rules precisely, so the client's
dispatch is tested against the same walls the live server enforces:

- /machine/metrics: machine key (hwk_) only.
- /metrics/values, /metrics/compare, /dq/*: human session token only.
- /metrics/values/{id}/lineage: either credential.
- /public/metrics/certified: no credential.
"""

from __future__ import annotations

import json

import httpx
import pytest

MACHINE_KEY = "hwk_test-key-000000000000000000000000000000"
SESSION_TOKEN = "session-token-for-tests"  # deliberately not hwk_-prefixed
RATE_LIMITED_KEY = "hwk_rate-limited-key-0000000000000000000000"

VRM_ID = "abad3473-5ebe-45d2-ae29-623b15f4c4f8"
UPT_ID = "2c9a4b1e-0000-4000-8000-000000000001"
OTP_ID = "2c9a4b1e-0000-4000-8000-000000000002"

METRIC_VALUES = [
    {
        "metric_value_id": VRM_ID,
        "metric": "vrm",
        "unit": "miles",
        "period_start": "2026-07-09",
        "period_end": "2026-07-11",
        "scope": "agency",
        "value": "12794.92",
        "calc_name": "vrm_v0",
        "calc_version": "0.2.0",
        "computed_at": "2026-07-09T17:49:14.104667Z",
        "certification_status": "certified",
        "detail": {
            "coverage": "0.9263",
            "coverage_threshold": "0.90",
            "excluded_groups": 202,
            "total_groups": 2742,
        },
        "category": "ntd",
    },
    {
        "metric_value_id": UPT_ID,
        "metric": "upt",
        "unit": "unlinked passenger trips",
        "period_start": "2026-07-09",
        "period_end": "2026-07-11",
        "scope": "agency",
        "value": "185321",
        "calc_name": "upt_v0",
        "calc_version": "0.4.0",
        "computed_at": "2026-07-10T09:00:00Z",
        "certification_status": "uncertified",
        "detail": {
            "source_mix": {"tides_simulated": 185321},
            "missing_share": "0.0150",
            "missing_trip_threshold": "0.02",
        },
        "category": "ntd",
    },
    {
        "metric_value_id": OTP_ID,
        "metric": "otp",
        "unit": "ratio",
        "period_start": "2026-07-09",
        "period_end": "2026-07-11",
        "scope": "agency",
        "value": "0.5410",
        "calc_name": "otp_v0",
        "calc_version": "0.1.0",
        "computed_at": "2026-07-12T12:00:00Z",
        "certification_status": "uncertified",
        "detail": {"passages_refused": 156000, "source_mix": {"gtfsrt": 2240000}},
        "category": "ops",
    },
]

LINEAGE_TREE = {
    "kind": "computed.metric_values",
    "id": VRM_ID,
    "transform_name": "vrm_v0",
    "transform_version": "0.2.0",
    "inputs": [
        {
            "kind": "canonical.vehicle_positions",
            "id": "vp-1",
            "transform_name": "normalize_gtfsrt",
            "transform_version": "0.3.0",
            "inputs": [
                {
                    "kind": "raw.records",
                    "id": "sha256-raw-a",
                    "transform_name": None,
                    "transform_version": None,
                    "inputs": [],
                }
            ],
        },
        {
            "kind": "canonical.vehicle_positions",
            "id": "vp-2",
            "transform_name": "normalize_gtfsrt",
            "transform_version": "0.3.0",
            "inputs": [
                {
                    "kind": "raw.records",
                    "id": "sha256-raw-a",
                    "transform_name": None,
                    "transform_version": None,
                    "inputs": [],
                },
                {
                    "kind": "raw.records",
                    "id": "sha256-raw-b",
                    "transform_name": None,
                    "transform_version": None,
                    "inputs": [],
                },
            ],
        },
    ],
}

DQ_ISSUES = [
    {
        "issue_id": "11111111-0000-4000-8000-000000000001",
        "issue_type": "missing_trips_above_threshold",
        "severity": "blocking",
        "status": "open",
        "owner": "dsteward",
        "title": "Missing trips above the 2% line",
        "description": "36.6% of operated trips have no passenger events.",
        "source_record_ids": ["sha256-raw-a", "sha256-raw-b"],
        "created_at": "2026-07-10T10:00:00Z",
        "resolved_at": None,
        "resolution": None,
        "resolution_minutes": None,
    },
    {
        "issue_id": "11111111-0000-4000-8000-000000000002",
        "issue_type": "apc_imbalance",
        "severity": "warning",
        "status": "resolved",
        "owner": "dsteward",
        "title": "Boarding/alighting imbalance on route 39",
        "description": "Ons exceed offs by 12% on 2026-07-09.",
        "source_record_ids": None,
        "created_at": "2026-07-09T08:00:00Z",
        "resolved_at": "2026-07-09T09:30:00Z",
        "resolution": "APC unit recalibrated; counts re-ingested.",
        "resolution_minutes": 12,
    },
]

COMPARE_RESPONSE = {
    "metric": "vrh",
    "unit": "hours",
    "comparands": [
        {
            "key": "2026-07-01..2026-08-01",
            "period_start": "2026-07-01",
            "period_end": "2026-08-01",
            "calc_name": None,
            "calc_version": None,
            "baseline": True,
        },
        {
            "key": "2026-06-01..2026-07-01",
            "period_start": "2026-06-01",
            "period_end": "2026-07-01",
            "calc_name": None,
            "calc_version": None,
            "baseline": False,
        },
    ],
    "scopes": ["agency", "mode:bus"],
    "rows": [
        {
            "scope": "agency",
            "cells": [
                {
                    "comparand_index": 0,
                    "value": {
                        "metric_value_id": "33333333-0000-4000-8000-000000000001",
                        "metric": "vrh",
                        "unit": "hours",
                        "period_start": "2026-07-01",
                        "period_end": "2026-08-01",
                        "scope": "agency",
                        "value": "1260.85",
                        "calc_name": "vrh_v0",
                        "calc_version": "0.3.0",
                        "computed_at": "2026-07-12T12:00:00Z",
                        "certification_status": "certified",
                        "detail": {},
                        "category": "ntd",
                    },
                    "missing_reason": None,
                    "delta_vs_baseline": None,
                    "delta_vs_previous": None,
                },
                {
                    "comparand_index": 1,
                    "value": {
                        "metric_value_id": "33333333-0000-4000-8000-000000000002",
                        "metric": "vrh",
                        "unit": "hours",
                        "period_start": "2026-06-01",
                        "period_end": "2026-07-01",
                        "scope": "agency",
                        "value": "1190.10",
                        "calc_name": "vrh_v0",
                        "calc_version": "0.3.0",
                        "computed_at": "2026-07-12T12:00:00Z",
                        "certification_status": "uncertified",
                        "detail": {},
                        "category": "ntd",
                    },
                    "missing_reason": None,
                    "delta_vs_baseline": "-70.75",
                    "delta_vs_previous": "-70.75",
                },
            ],
        },
        {
            "scope": "mode:bus",
            "cells": [
                {
                    "comparand_index": 0,
                    "value": None,
                    "missing_reason": (
                        "No vrh figure exists for scope 'mode:bus' computed "
                        "for the period [2026-07-01, 2026-08-01). A missing "
                        "figure is shown as missing, never invented."
                    ),
                    "delta_vs_baseline": None,
                    "delta_vs_previous": None,
                },
                {
                    "comparand_index": 1,
                    "value": None,
                    "missing_reason": (
                        "No vrh figure exists for scope 'mode:bus' computed "
                        "for the period [2026-06-01, 2026-07-01). A missing "
                        "figure is shown as missing, never invented."
                    ),
                    "delta_vs_baseline": None,
                    "delta_vs_previous": None,
                },
            ],
        },
    ],
    "directions": {"vrh": None, "coverage": "higher_is_better"},
    "direction_note": "Direction metadata comes from the calc registry.",
    "delta_note": "Deltas are comparison affordances, not reported figures.",
    "mixed_certification": True,
    "mixed_certification_note": (
        "This comparison mixes certified and uncertified figures."
    ),
}

DQ_COUNTS = {
    "total": 2,
    "by_severity": {"blocking": 1, "warning": 1, "info": 0},
    "by_status": {"open": 1, "owned": 0, "resolved": 1},
}


def _json_response(status_code: int, payload, headers=None) -> httpx.Response:
    return httpx.Response(
        status_code, content=json.dumps(payload), headers={
            "content-type": "application/json", **(headers or {})
        },
    )


def _error(status_code: int, detail: str, headers=None) -> httpx.Response:
    return _json_response(status_code, {"detail": detail}, headers)


def _filter_values(request: httpx.Request) -> list[dict]:
    params = request.url.params
    rows = METRIC_VALUES
    if params.get("metric"):
        rows = [r for r in rows if r["metric"] == params["metric"]]
    if params.get("category"):
        rows = [r for r in rows if r["category"] == params["category"]]
    if params.get("period_start"):
        rows = [r for r in rows if r["period_start"] >= params["period_start"]]
    if params.get("period_end"):
        rows = [r for r in rows if r["period_end"] <= params["period_end"]]
    return rows


def _credential(request: httpx.Request) -> tuple[str, str]:
    """('machine'|'session'|'none', token) per the API's dispatch rule."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return "none", ""
    return ("machine" if token.startswith("hwk_") else "session"), token


def fake_api_handler(request: httpx.Request) -> httpx.Response:
    kind, token = _credential(request)
    path = request.url.path

    if path == "/auth/login" and request.method == "POST":
        body = json.loads(request.content)
        if body == {"username": "vera", "password": "viewer-pass-1"}:
            return _json_response(200, {
                "access_token": SESSION_TOKEN,
                "token_type": "bearer",
                "expires_in": 1800,
                "username": "vera",
                "role": "viewer",
            })
        return _error(
            401, "That username and password combination was not recognized."
        )

    if path == "/public/metrics/certified":
        rows = [
            r for r in METRIC_VALUES
            if r["certification_status"] == "certified" and r["category"] == "ntd"
        ]
        return _json_response(200, rows)

    if path == "/machine/metrics":
        if kind != "machine" or token == RATE_LIMITED_KEY:
            if token == RATE_LIMITED_KEY:
                return _error(
                    429,
                    "This client is sending requests faster than its rate "
                    "limit allows. Please wait 7 second(s) and try again.",
                    {"Retry-After": "7"},
                )
            return _error(
                401,
                "This endpoint requires a Headway machine API key, sent as "
                "'Authorization: Bearer hwk_...'. No valid key was provided.",
            )
        return _json_response(200, _filter_values(request))

    if path == "/metrics/values":
        if kind != "session":
            return _error(
                401, "You are not signed in. Please sign in to use Headway."
            )
        return _json_response(200, _filter_values(request))

    if path == "/metrics/compare":
        if kind != "session":
            return _error(
                401, "You are not signed in. Please sign in to use Headway."
            )
        return _json_response(200, COMPARE_RESPONSE)

    if path.startswith("/metrics/values/") and path.endswith("/lineage"):
        if kind == "none":
            return _error(
                401,
                "This request could not be authenticated. The credential is "
                "missing, invalid, expired, or revoked.",
            )
        metric_value_id = path.removeprefix("/metrics/values/").removesuffix(
            "/lineage"
        )
        if metric_value_id != VRM_ID:
            return _error(404, "No reported figure with that id exists.")
        return _json_response(200, LINEAGE_TREE)

    if path == "/dq/issues":
        if kind != "session":
            return _error(
                401, "You are not signed in. Please sign in to use Headway."
            )
        status = request.url.params.get("status")
        if status is not None and status not in ("open", "owned", "resolved"):
            return _error(
                422,
                f"'{status}' is not a data-quality status Headway knows. "
                "Valid statuses are: open, owned, resolved.",
            )
        rows = DQ_ISSUES
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return _json_response(200, rows)

    if path == "/dq/issues/counts":
        if kind != "session":
            return _error(
                401, "You are not signed in. Please sign in to use Headway."
            )
        return _json_response(200, DQ_COUNTS)

    return _error(404, f"Not Found: {path}")


@pytest.fixture()
def transport() -> httpx.MockTransport:
    return httpx.MockTransport(fake_api_handler)
