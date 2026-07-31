#!/usr/bin/env python3
"""Live-verification harness: drive the Headway MCP server as a real MCP
client over stdio and print the full transcript.

This is the client an assistant would be: it spawns ``headway-mcp`` as a
subprocess (stdio transport), performs the MCP initialize handshake, lists
the tools, and calls every one against the live Headway API. Used to
produce the evidence transcript for handoff 0034.

Usage:
    HEADWAY_MCP_API_KEY=hwk_... python scripts/mcp_transcript.py \
        [--figure-id UUID] [--certification-id UUID] [--truncate N]

The key is passed to the server through its environment, exactly as a
Claude Desktop / Claude Code config would.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TRUNCATE = 4000


def show(step: str, payload: object) -> None:
    text = json.dumps(payload, indent=1, default=str)
    if TRUNCATE and len(text) > TRUNCATE:
        text = text[:TRUNCATE] + f"\n ... [truncated at {TRUNCATE} chars for the transcript]"
    print(f"\n=== {step} ===\n{text}")


def result_payload(result) -> object:
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    return [getattr(block, "text", str(block)) for block in result.content]


async def run(figure_id: str, certification_id: str, issue_id: str = "") -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "headway_mcp"],
        env={
            "HEADWAY_API_URL": os.environ.get(
                "HEADWAY_API_URL", "http://127.0.0.1:8000"
            ),
            "HEADWAY_MCP_API_KEY": os.environ["HEADWAY_MCP_API_KEY"],
            "PATH": os.environ.get("PATH", ""),
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            show(
                "initialize",
                {
                    "protocolVersion": init.protocol_version,
                    "serverInfo": init.server_info.model_dump(),
                    "instructions_first_line": (init.instructions or "").splitlines()[0],
                },
            )

            tools = await session.list_tools()
            show(
                "tools/list",
                [
                    {"name": t.name, "required": t.input_schema.get("required", [])}
                    for t in tools.tools
                ],
            )

            async def call(step: str, name: str, args: dict | None = None):
                result = await session.call_tool(name, args or {})
                show(f"tools/call {name} — {step}", result_payload(result))
                return result

            await call(
                "computed figures for a period (receipts on every row)",
                "metric_values",
                {"metric": "pmt", "period_start": "2026-07-01"},
            )
            await call(
                "EMPTY PERIOD — refusal text, never a bare []",
                "metric_values",
                {"metric": "vrm", "period_start": "2031-01-01"},
            )
            await call(
                "the lineage walk on a real figure",
                "explain_figure",
                {"metric_value_id": figure_id},
            )
            await call(
                "LIVE REFUSAL — unknown id, API refusal passed through verbatim",
                "explain_figure",
                {"metric_value_id": "00000000-0000-0000-0000-000000000000"},
            )
            await call(
                "verify_claim → match (byte-identical)",
                "verify_claim",
                {"metric_value_id": figure_id, "claimed_value": CLAIM_MATCH},
            )
            await call(
                "verify_claim → MISMATCH (a rounded restatement is not the figure)",
                "verify_claim",
                {"metric_value_id": figure_id, "claimed_value": CLAIM_MISMATCH},
            )
            await call(
                "verify_claim → no_such_figure",
                "verify_claim",
                {
                    "metric_value_id": "99999999-9999-9999-9999-999999999999",
                    "claimed_value": "1.00",
                },
            )
            await call("the certified public record", "certified_figures")
            await call(
                "Ed25519 signature verification of a certification",
                "verify_certification",
                {"certification_id": certification_id},
            )

            # -- handoff 0039: the read:dq / read:ops tools ------------------
            await call(
                "DQ queue summary in agency vocabulary (counts + headlines)",
                "dq_summary",
            )
            await call(
                "DQ blocking-for-period — what a calc run refuses over",
                "dq_blocking_for_period",
            )
            if issue_id:
                await call(
                    "DQ issue detail — full description + raw-record provenance",
                    "dq_issue",
                    {"issue_id": issue_id},
                )
            await call(
                "DQ issue detail — LIVE REFUSAL, unknown id passed through verbatim",
                "dq_issue",
                {"issue_id": "00000000-0000-0000-0000-000000000000"},
            )
            await call(
                "ops snapshot — live vehicles with last-seen staleness framing",
                "ops_snapshot",
                {"max_age_seconds": 300},
            )
            await call(
                "ops snapshot — a 1s window, staleness note not an empty fleet",
                "ops_snapshot",
                {"max_age_seconds": 1},
            )


CLAIM_MATCH = "221996.24"
CLAIM_MISMATCH = "221996"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--figure-id", default="82f8c972-f50c-4657-b3ff-3d3de50bbf71")
    parser.add_argument(
        "--certification-id", default="a3f4c2f4-3700-488f-8dc7-cdc4ca90f196"
    )
    # A real dq.issues id for the detail call (handoff 0039). Empty = skip the
    # real-id call and show only the live-refusal (unknown-id) one.
    parser.add_argument("--issue-id", default="")
    parser.add_argument("--claim-match", default=CLAIM_MATCH)
    parser.add_argument("--claim-mismatch", default=CLAIM_MISMATCH)
    parser.add_argument("--truncate", type=int, default=TRUNCATE)
    ns = parser.parse_args()
    TRUNCATE = ns.truncate
    CLAIM_MATCH = ns.claim_match
    CLAIM_MISMATCH = ns.claim_mismatch
    asyncio.run(run(ns.figure_id, ns.certification_id, ns.issue_id))
