"""MCP registration: the advertised toolset, schemas, and honest descriptions."""

from __future__ import annotations

import asyncio

from headway_mcp.server import INSTRUCTIONS, build_server

EXPECTED_TOOLS = {
    "metric_values",
    "explain_figure",
    "verify_claim",
    "certified_figures",
    "verify_certification",
}


def _list_tools(server):
    return asyncio.run(server.list_tools())


def test_exactly_the_read_only_toolset_is_registered(tools):
    server = build_server(tools)
    listed = _list_tools(server)
    assert {t.name for t in listed} == EXPECTED_TOOLS


def test_every_tool_has_a_description_and_schema(tools):
    server = build_server(tools)
    for tool in _list_tools(server):
        assert tool.description, f"{tool.name} has no description"
        assert tool.input_schema.get("type") == "object", tool.name


def test_tool_schemas_carry_the_expected_parameters(tools):
    server = build_server(tools)
    by_name = {t.name: t for t in _list_tools(server)}
    mv = by_name["metric_values"].input_schema["properties"]
    assert set(mv) == {"metric", "period_start", "period_end", "category"}
    vc = by_name["verify_claim"].input_schema
    assert set(vc["properties"]) == {
        "metric_value_id",
        "claimed_value",
        "claimed_period_start",
        "claimed_period_end",
    }
    assert set(vc.get("required", [])) == {"metric_value_id", "claimed_value"}
    assert by_name["explain_figure"].input_schema["required"] == ["metric_value_id"]


def test_descriptions_are_refusal_forward_and_honest(tools):
    server = build_server(tools)
    by_name = {t.name: t.description for t in _list_tools(server)}
    # Empty periods explain themselves — promised in the description.
    assert "never silently []" in by_name["metric_values"]
    # verify_claim advertises the tri-state, byte-compared.
    for verdict in ("match", "mismatch", "no_such_figure"):
        assert verdict in by_name["verify_claim"]
    # The certified surface shows simulated flags rather than hiding them.
    assert "never hidden" in by_name["certified_figures"]


def test_instructions_state_the_guarantee_boundary_and_absences():
    assert "Headway guarantees what these tools returned" in " ".join(INSTRUCTIONS.split())
    # Sensitivity per docs/data-classification.md: the highest-sensitivity
    # data and the employee-adjacent data are named as deliberately absent.
    assert "paratransit trip coordinates" in INSTRUCTIONS
    assert "operator-identified" in INSTRUCTIONS
    assert "audit trail" in INSTRUCTIONS
    # Honest scope: the session-only surfaces are named, not implied.
    assert "data-quality queue" in INSTRUCTIONS
    assert "Write actions do not exist here" in INSTRUCTIONS
