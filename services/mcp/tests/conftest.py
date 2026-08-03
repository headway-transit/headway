"""Test fixtures: a fake Headway API behind httpx.MockTransport.

The MCP server is an API client and nothing else, so the entire service is
testable by faking the API's HTTP responses — no database, no network, no
live stack. The canned rows mirror the real response shapes byte-for-byte
(value as an exact string, detail verbatim, category present).
"""

from __future__ import annotations

import json

import httpx
import pytest

from headway_mcp.client import HeadwayClient
from headway_mcp.tools import HeadwayTools

FIGURE_ROW = {
    "metric_value_id": "11111111-1111-1111-1111-111111111111",
    "metric": "vrm",
    "unit": "vehicle_miles",
    "period_start": "2026-07-01",
    "period_end": "2026-08-01",
    "scope": "agency",
    "value": "9524.63",
    "calc_name": "vrm_v0",
    "calc_version": "0.2.0",
    "computed_at": "2026-07-29T00:00:00Z",
    "certification_status": "uncertified",
    "detail": {"simulated_source_data": True, "trip_coverage": "0.9126"},
    "category": "ntd",
}

LINEAGE_TREE = {
    "kind": "metric_value",
    "id": FIGURE_ROW["metric_value_id"],
    "transform_name": "vrm_v0",
    "transform_version": "0.2.0",
    "inputs": [
        {
            "kind": "raw_record",
            "id": "574af469deadbeef",
            "transform_name": None,
            "transform_version": None,
            "inputs": [],
        }
    ],
}

CERTIFIED_ROW = {
    **FIGURE_ROW,
    "metric_value_id": "22222222-2222-2222-2222-222222222222",
    "certification_status": "certified",
    "certification": {
        "certification_id": "33333333-3333-3333-3333-333333333333",
        "certified_at": "2026-07-15T00:00:00Z",
        "key_fingerprint": "ed25519:abcd",
    },
}

VERIFY_RESULT = {
    "certification_id": "33333333-3333-3333-3333-333333333333",
    "status": "verified",
    "algorithm": "Ed25519",
    "key_fingerprint": "ed25519:abcd",
    "certified_at": "2026-07-15T00:00:00Z",
}

# -- data-quality queue rows (handoff 0039). A finding is NOT a figure: it
# carries no value/receipt fields — it leads with what it is ABOUT in the
# agency's vocabulary. The list row (queue) omits source_record_ids, exactly
# as the API does; the detail row carries the full untruncated array.
DQ_ISSUE_ID = "44444444-4444-4444-4444-444444444444"
DQ_SUMMARY_ROW = {
    "issue_id": DQ_ISSUE_ID,
    "issue_type": "apc_missing_trips_above_fta_threshold",
    "severity": "blocking",
    "status": "open",
    "owner": None,
    "title": "APC coverage below the 2% line for route 1 on 2026-07-09",
    "description": (
        "9,123 operated trips, 91 with missing APC data (>2%): a certifiable "
        "PMT figure is refused until a statistician attests the factoring."
    ),
    "created_at": "2026-07-15T22:56:06Z",
    "resolved_at": None,
    "resolution": None,
    "resolution_minutes": None,
    "subject_context": {
        "version": 1,
        "blocks": [
            {"block_id": "b-17", "routes": ["1"], "span": "05:12–23:40", "trips": 42}
        ],
    },
}
DQ_ISSUE_DETAIL = {
    **DQ_SUMMARY_ROW,
    "source_record_ids": ["rec-aaa", "rec-bbb", "rec-ccc"],
}
DQ_PAGE = {
    "issues": [DQ_SUMMARY_ROW],
    "total": 1,
    "limit": 50,
    "next_cursor": None,
    "has_more": False,
}
DQ_COUNTS = {
    "total": 3,
    "by_severity": {"blocking": 1, "warning": 1, "info": 1},
    "by_status": {"open": 2, "owned": 0, "resolved": 1, "attested": 0},
    "resolution_minutes_total": 45,
}

# -- operations snapshot (handoff 0039): verbatim OpsVehiclesLatest, `truncated`
# and staleness note intact.
OPS_SNAPSHOT = {
    "as_of": "2026-07-30T12:00:00Z",
    "max_age_seconds": 300,
    "category": "ops",
    "ops_note": (
        "Operations data — not an NTD reported figure. Live vehicle "
        "positions are never certifiable."
    ),
    "vehicles": [
        {
            "vehicle_id": "bus-1701",
            "latitude": 42.3601,
            "longitude": -71.0589,
            "recorded_at": "2026-07-30T11:59:30Z",
            "age_seconds": 30,
            "bearing": None,
            "speed_mps": None,
            "trip_id": None,
            "route_id": "1",
            "source_record_id": "a" * 64,
            "source": "gtfs_rt_vehicle_positions",
            "simulated": False,
        }
    ],
    "vehicle_count": 1,
    "total_in_window": 1,
    "cap": 5000,
    "truncated": False,
    "newest_position_at": "2026-07-30T11:59:30Z",
    "note": None,
}

DQ_SCOPE_DENIAL_DETAIL = (
    "This machine API key ('test') does not have the 'read:dq' permission "
    "it needs for this endpoint."
)
DQ_ISSUE_404_DETAIL = "No data-quality issue with that id exists."

LINEAGE_404_DETAIL = (
    "No metric value with that id exists, so there is no number to explain."
)
SCOPE_DENIAL_DETAIL = (
    "This machine API key ('test') does not have the 'read:metrics' "
    "permission it needs for this endpoint."
)


class FakeApi:
    """Route table + call log for the fake Headway API."""

    def __init__(self):
        self.metrics_rows: list[dict] = [FIGURE_ROW]
        self.dq_page: dict = DQ_PAGE
        self.dq_counts: dict = DQ_COUNTS
        self.ops_snapshot: dict = OPS_SNAPSHOT
        self.requests: list[httpx.Request] = []
        self.deny_scope = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if self.deny_scope:
            return httpx.Response(403, json={"detail": SCOPE_DENIAL_DETAIL})
        if path == "/machine/metrics":
            return httpx.Response(200, json=self.metrics_rows)
        if path == "/machine/dq/issues/counts":
            return httpx.Response(200, json=self.dq_counts)
        if path == "/machine/dq/issues":
            return httpx.Response(200, json=self.dq_page)
        if path.startswith("/machine/dq/issues/"):
            issue_id = path.split("/")[4]
            if issue_id == DQ_ISSUE_ID:
                return httpx.Response(200, json=DQ_ISSUE_DETAIL)
            return httpx.Response(404, json={"detail": DQ_ISSUE_404_DETAIL})
        if path == "/machine/ops/vehicles/latest":
            return httpx.Response(200, json=self.ops_snapshot)
        if path.startswith("/metrics/values/") and path.endswith("/lineage"):
            metric_value_id = path.split("/")[3]
            if metric_value_id == FIGURE_ROW["metric_value_id"]:
                return httpx.Response(200, json=LINEAGE_TREE)
            return httpx.Response(404, json={"detail": LINEAGE_404_DETAIL})
        if path == "/public/metrics/certified":
            return httpx.Response(200, json=[CERTIFIED_ROW])
        if path.startswith("/public/certifications/"):
            certification_id = path.split("/")[3]
            if certification_id == VERIFY_RESULT["certification_id"]:
                return httpx.Response(200, json=VERIFY_RESULT)
            return httpx.Response(
                404, json={"detail": "No certification with that id exists."}
            )
        return httpx.Response(404, json={"detail": f"unrouted test path {path}"})


@pytest.fixture
def fake_api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def client(fake_api: FakeApi) -> HeadwayClient:
    return HeadwayClient(
        "http://headway-api.test",
        "hwk_test-key-0000",
        transport=httpx.MockTransport(fake_api.handler),
    )


@pytest.fixture
def tools(client: HeadwayClient) -> HeadwayTools:
    return HeadwayTools(client)
