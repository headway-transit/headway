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
        self.requests: list[httpx.Request] = []
        self.deny_scope = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if self.deny_scope:
            return httpx.Response(403, json={"detail": SCOPE_DENIAL_DETAIL})
        if path == "/machine/metrics":
            return httpx.Response(200, json=self.metrics_rows)
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
