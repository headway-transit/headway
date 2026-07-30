"""The Headway MCP server: your data, your box, your assistant — with receipts.

Registers the read-only toolset (headway_mcp.tools) on the official MCP
Python SDK server and speaks stdio — the local-first transport a desktop
assistant (Claude Desktop, Claude Code, or a local Ollama-class client)
launches as a subprocess. The server binds nothing to the network itself;
connecting it to a cloud assistant is the agency's explicit act (see
docs/mcp.md, "Where your data goes").

Startup is deny-by-default: without a Headway machine key in
HEADWAY_MCP_API_KEY the process refuses to start with a plain-language
explanation. There is no anonymous mode and no database fallback.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__
from .client import KEY_PREFIX, ConfigError, HeadwayClient
from .tools import HeadwayTools

DEFAULT_API_URL = "http://127.0.0.1:8000"

INSTRUCTIONS = """\
This server exposes a Headway installation's READ surface: computed transit
metrics with their receipts, provenance walks to raw records, and the
certified public figures with signature verification.

The guarantee boundary, stated plainly: Headway guarantees what these tools
returned — exact value strings, certification status, calculation
name+version, verbatim calculation detail (including simulated-data flags),
and lineage. Headway cannot guarantee what an assistant writes ABOUT those
results. Every figure you restate can be checked with verify_claim; prefer
quoting values verbatim and naming their certification status.

Rules of this surface:
- No tool computes, estimates, or rounds a number. Figures originate only
  in Headway's deterministic, versioned calculation library.
- An empty period is not zero. When no figure exists you get an explanation
  (the calculation never ran, or it refused over a data-quality gap) — do
  not fill the gap yourself.
- Refusals from Headway are passed through verbatim. They are the product
  working, not an error to route around.

Deliberately absent from this surface: paratransit trip coordinates (rider
home addresses), operator-identified telematics, user accounts, and the
audit trail — sensitive per Headway's data classification. Also absent for
now: the data-quality queue, sources status, operations summaries, and
calc-run status, which today require a signed-in human session (a recorded
open question, not an oversight). Write actions do not exist here at all.
"""


def build_server(tools: HeadwayTools) -> MCPServer:
    server = MCPServer(
        name="headway",
        title="Headway (transit data, with receipts)",
        version=__version__,
        instructions=INSTRUCTIONS,
    )

    @server.tool(
        name="metric_values",
        description=(
            "Computed transit metrics from Headway's calculation library, "
            "each with its receipt: exact value string, certification "
            "status, calc name+version, verbatim calculation detail "
            "(including simulated-data flags), and a metric_value_id for "
            "the provenance walk. Filters: metric (e.g. 'vrm', 'vrh', "
            "'upt', 'pmt'), period_start/period_end (YYYY-MM-DD), category "
            "('ntd' regulatory figures or 'ops' operations metrics — 'ops' "
            "figures are never NTD-reportable). An empty result explains "
            "itself; it is never silently []."
        ),
    )
    def metric_values(
        metric: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        return tools.metric_values(metric, period_start, period_end, category)

    @server.tool(
        name="explain_figure",
        description=(
            "Headway's 'explain this number' walk: the full provenance tree "
            "for one figure, from the computed value through every "
            "transform (name + version) down to the content-addressed raw "
            "source records. Input: the figure's metric_value_id (from "
            "metric_values or certified_figures). Unknown ids return "
            "Headway's own refusal text verbatim."
        ),
    )
    def explain_figure(metric_value_id: str) -> dict[str, Any]:
        return tools.explain_figure(metric_value_id)

    @server.tool(
        name="verify_claim",
        description=(
            "Check a claimed figure against Headway's store, byte-compared. "
            "Give the metric_value_id, the claimed value exactly as stated "
            "(e.g. '9524.63'), and optionally the claimed period dates. "
            "Answers exactly one of: 'match' (byte-identical to the store), "
            "'mismatch' (with the stored figure and its receipt), or "
            "'no_such_figure' (the id does not exist — the citation is "
            "unresolved). Use this to make any restatement of a Headway "
            "number checkable."
        ),
    )
    def verify_claim(
        metric_value_id: str,
        claimed_value: str,
        claimed_period_start: str | None = None,
        claimed_period_end: str | None = None,
    ) -> dict[str, Any]:
        return tools.verify_claim(
            metric_value_id, claimed_value, claimed_period_start, claimed_period_end
        )

    @server.tool(
        name="certified_figures",
        description=(
            "The figures this agency has CERTIFIED — the human-signed "
            "public record, from Headway's open-data endpoint. Each row "
            "carries its certification reference (certification_id + "
            "signing-key fingerprint) alongside the same receipt fields as "
            "metric_values; simulated-data flags are shown, never hidden. "
            "Feed a certification_id to verify_certification to check the "
            "signature."
        ),
    )
    def certified_figures() -> dict[str, Any]:
        return tools.certified_figures()

    @server.tool(
        name="verify_certification",
        description=(
            "Tamper-evidence check for one certification: Headway "
            "re-verifies the stored certificate bytes against the stored "
            "Ed25519 signature server-side and returns the verdict, "
            "algorithm, key fingerprint, and timestamp — never the "
            "certifier's personal details. 'verified' means the certified "
            "record is exactly what was signed."
        ),
    )
    def verify_certification(certification_id: str) -> dict[str, Any]:
        return tools.verify_certification(certification_id)

    return server


def load_config(env: dict[str, str] | None = None) -> tuple[str, str]:
    """Resolve (api_url, api_key) from the environment — refusing to start,
    in plain language, when the machine key is absent or malformed."""
    env = os.environ if env is None else env
    api_url = env.get("HEADWAY_API_URL", DEFAULT_API_URL)
    api_key = env.get("HEADWAY_MCP_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(
            "No Headway machine API key is configured, so this MCP server "
            "refuses to start — it has no database access and no anonymous "
            "mode; the Headway API (and its audit trail) is the only door. "
            "Ask a Headway administrator to issue a key with the "
            "'read:metrics' permission (POST /machine/keys) and set it as "
            "HEADWAY_MCP_API_KEY."
        )
    if not api_key.startswith(KEY_PREFIX):
        raise ConfigError(
            "HEADWAY_MCP_API_KEY is set but does not look like a Headway "
            f"machine key (machine keys start with '{KEY_PREFIX}'). A human "
            "session token will not work here — machine access is "
            "deliberately separate so every MCP tool call is audited under "
            "its own key identity."
        )
    return api_url, api_key


def main() -> None:
    try:
        api_url, api_key = load_config()
        client = HeadwayClient(api_url, api_key)
    except ConfigError as exc:
        print(f"headway-mcp: {exc}", file=sys.stderr)
        raise SystemExit(2)
    server = build_server(HeadwayTools(client))
    server.run("stdio")


if __name__ == "__main__":
    main()
