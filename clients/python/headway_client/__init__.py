"""headway-client — the analyst's door into a Headway deployment.

Explore and compute freely: nothing computed outside Headway's calculation
library (services/calc) can ever become a reported figure. Only the
calculation library writes computed.metric_values, and the walls are
structural database CHECKs, not policy.

That sentence is the whole trust model, so it bears repeating precisely:
this client (and any notebook, script, or BI tool built on it) is a
READ-ONLY consumer. You can slice, aggregate, model, and chart to your
heart's content — and none of it can flow back into what the agency
reports, because the reporting pipeline's only writer is the deterministic,
versioned calc library and the database itself refuses everything else
(e.g. a certified operations figure is structurally unrepresentable —
migration 0024's CHECK).

What the client gives you that a bare HTTP call does not:

- Typed models mirroring the API contracts (``MetricValue``, ``LineageNode``,
  ``DqIssue``, ``CompareResponse``…), with figures kept as exact decimal
  STRINGS end to end — floating point never touches a reported value.
- DataFrame helpers (``headway_client.frames``, the ``[pandas]`` extra) in
  which provenance columns — metric_value_id, calc_name, calc_version,
  category, certification_status, simulated, source_mix — are ALWAYS
  present. They are not opt-in kwargs; dropping provenance is the caller's
  explicit act, never this library's default.
- ``walk_lineage(metric_value_id)``: the full "explain this number" trail
  from a reported figure down to the content-addressed raw records that
  produced it.

Authentication: a Headway machine API key (``hwk_…``, scope
``read:metrics``) for machine reads and lineage; no credential at all for
the public certified open-data endpoint. Two endpoints (metric comparison
and data-quality issues) currently accept only a signed-in human session —
``headway_client.login()`` wraps the API's own login to get one; each
method's docstring says honestly which credential it needs.
"""

from __future__ import annotations

from .client import HeadwayClient, HeadwayApiError, login
from .models import (
    Comparand,
    CompareCell,
    CompareResponse,
    CompareRow,
    DqIssue,
    DqIssueCounts,
    LineageNode,
    LineageTrail,
    MetricValue,
)

#: The honesty story, verbatim — the same wording appears in
#: docs/analyst-access.md, the README's "For analysts" subsection, and the
#: opening cell of every example notebook. If you quote it, quote all of it.
HONESTY_STORY = (
    "Explore and compute freely: nothing computed outside Headway's "
    "calculation library (services/calc) can ever become a reported figure. "
    "Only the calculation library writes computed.metric_values, and the "
    "walls are structural database CHECKs, not policy."
)

__version__ = "0.1.0"

__all__ = [
    "HONESTY_STORY",
    "HeadwayApiError",
    "HeadwayClient",
    "login",
    "Comparand",
    "CompareCell",
    "CompareResponse",
    "CompareRow",
    "DqIssue",
    "DqIssueCounts",
    "LineageNode",
    "LineageTrail",
    "MetricValue",
]
