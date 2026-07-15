"""The lineage walk — the trail from a figure to its raw records."""

from __future__ import annotations

import pytest

from headway_client import HeadwayClient
from conftest import MACHINE_KEY, SESSION_TOKEN, VRM_ID


@pytest.fixture(params=[MACHINE_KEY, SESSION_TOKEN], ids=["machine", "session"])
def client(request, transport):
    """The lineage endpoint is dual-credential; walk it with both."""
    with HeadwayClient("http://fake", token=request.param, transport=transport) as hw:
        yield hw


def test_walk_lineage_reaches_raw_records(client):
    trail = client.walk_lineage(VRM_ID)
    assert trail.root.kind == "computed.metric_values"
    assert trail.root.id == VRM_ID
    assert trail.root.transform_name == "vrm_v0"
    # The trail bottoms out at content-addressed raw records, de-duplicated
    # in first-encountered order.
    assert trail.raw_record_ids() == ["sha256-raw-a", "sha256-raw-b"]


def test_nodes_flattened_depth_first_with_parents(client):
    trail = client.walk_lineage(VRM_ID)
    nodes = trail.nodes()
    depths = [depth for depth, _, _ in nodes]
    kinds = [node.kind for _, _, node in nodes]
    assert depths == [0, 1, 2, 1, 2, 2]
    assert kinds == [
        "computed.metric_values",
        "canonical.vehicle_positions",
        "raw.records",
        "canonical.vehicle_positions",
        "raw.records",
        "raw.records",
    ]
    root_depth, root_parent, root = nodes[0]
    assert root_parent is None and root is trail.root
    # Every non-root node's parent is the node it is an input OF.
    for depth, parent, node in nodes[1:]:
        assert parent is not None
        assert node in parent.inputs
        assert depth >= 1


def test_leaves_carry_no_transform(client):
    trail = client.walk_lineage(VRM_ID)
    for _, _, node in trail.nodes():
        if node.kind == "raw.records":
            assert node.transform_name is None
            assert node.transform_version is None
            assert node.inputs == ()
