"""The HTTP client behind headway-client.

Explore and compute freely: nothing computed outside Headway's calculation
library (services/calc) can ever become a reported figure. Only the
calculation library writes computed.metric_values, and the walls are
structural database CHECKs, not policy.

Credentials, honestly
---------------------
The Headway API accepts two kinds of Bearer credential, and this client
carries whichever you give it in the one ``token`` slot:

- A **machine API key** (``hwk_…``, issued by an administrator with the
  ``read:metrics`` scope — see docs/analyst-access.md). This is the analyst
  default. It reaches machine metrics reads and the lineage walk. Machine
  reads are rate-limited per key and audit-logged by the server.
- A **session token** from the API's own login (``headway_client.login``).
  Two endpoints — metric comparison and data-quality issues — currently
  accept ONLY a signed-in human session; their methods say so and raise the
  server's plain-language 401 rather than papering over it.
- **No credential at all** reaches exactly one endpoint: the public
  certified open-data feed (``public_certified``).

``metric_values`` dispatches on the credential's shape: a machine key calls
``GET /machine/metrics``, a session token calls ``GET /metrics/values``.
The API guarantees the two serve the same rows, filters, and shape (the
machine endpoint delegates to the same query function — they can never
drift), so the dispatch changes the door, never the data.

Failures fail loudly: every non-2xx response raises
:class:`HeadwayApiError` carrying the server's plain-language ``detail``
(and ``Retry-After`` for rate limits). Nothing is retried silently.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional, Sequence

import httpx

from .models import (
    CompareResponse,
    DqIssue,
    DqIssueCounts,
    LineageNode,
    LineageTrail,
    MetricValue,
)

MACHINE_KEY_PREFIX = "hwk_"

_NO_CREDENTIAL_HELP = (
    "This endpoint needs a credential and the client was built without one. "
    "Pass token=<a machine API key ('hwk_…') or a session token from "
    "headway_client.login()>. Only public_certified() works unauthenticated."
)


class HeadwayApiError(Exception):
    """A non-2xx answer from the Headway API, relayed loudly and verbatim.

    ``detail`` is the server's own plain-language explanation (Headway's
    errors are written for a transit operations manager, so they are worth
    reading). ``retry_after_seconds`` is set for 429 rate-limit answers.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        retry_after_seconds: Optional[int] = None,
    ):
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds


def _raise_for_response(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    if not isinstance(detail, str):
        detail = str(detail)
    retry_after: Optional[int] = None
    if response.status_code == 429:
        raw = response.headers.get("Retry-After")
        if raw is not None and raw.isdigit():
            retry_after = int(raw)
    raise HeadwayApiError(
        response.status_code, detail, retry_after_seconds=retry_after
    )


def login(
    base_url: str,
    username: str,
    password: str,
    *,
    timeout: float = 30.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> str:
    """Sign in with a Headway account and return a short-lived session token.

    Wraps the API's own ``POST /auth/login`` — this client never invents an
    auth scheme. The token expires server-side (30 minutes by default);
    treat it like a password: read credentials from the environment or a
    prompt, never write them into a notebook or script.

    Needed only for the two endpoints that do not yet take a machine key
    (metric comparison, data-quality issues). Everything else prefers a
    ``read:metrics`` machine key.
    """
    with httpx.Client(
        base_url=base_url, timeout=timeout, transport=transport
    ) as http:
        response = http.post(
            "/auth/login", json={"username": username, "password": password}
        )
        _raise_for_response(response)
        return response.json()["access_token"]


class HeadwayClient:
    """A read-only client for one Headway deployment.

    Explore and compute freely: nothing computed outside Headway's
    calculation library (services/calc) can ever become a reported figure.
    Only the calculation library writes computed.metric_values, and the
    walls are structural database CHECKs, not policy.

    Every figure crosses this client as an exact decimal string; the models
    expose :class:`~decimal.Decimal` accessors and the DataFrame helpers
    (``headway_client.frames``) keep provenance columns always present.

    Usage::

        from headway_client import HeadwayClient

        with HeadwayClient("http://127.0.0.1:8000", token=key) as hw:
            values = hw.metric_values(metric="vrm")
            trail = hw.walk_lineage(values[0].metric_value_id)

    ``token`` is a machine API key (``hwk_…``) or a session token — see the
    module docstring for which endpoints accept which. ``transport`` exists
    for tests (httpx.MockTransport); leave it unset to talk to a live API.
    """

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        *,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self._token = token
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "HeadwayClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def uses_machine_key(self) -> bool:
        """True when the configured token is a machine API key (``hwk_…``)."""
        return bool(self._token) and self._token.startswith(MACHINE_KEY_PREFIX)

    # -- internals ---------------------------------------------------------

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        response = self._http.get(path, params=clean)
        _raise_for_response(response)
        return response.json()

    @staticmethod
    def _metric_params(
        metric: Optional[str],
        period_start: Optional[_dt.date],
        period_end: Optional[_dt.date],
        category: Optional[str],
    ) -> dict[str, Any]:
        return {
            "metric": metric,
            "period_start": period_start.isoformat() if period_start else None,
            "period_end": period_end.isoformat() if period_end else None,
            "category": category,
        }

    # -- computed figures ----------------------------------------------------

    def metric_values(
        self,
        metric: Optional[str] = None,
        period_start: Optional[_dt.date] = None,
        period_end: Optional[_dt.date] = None,
        category: Optional[str] = None,
    ) -> list[MetricValue]:
        """Computed figures, exactly as the calc library persisted them.

        Dispatches on the credential: a machine key reads
        ``GET /machine/metrics``, a session token reads
        ``GET /metrics/values`` — the API serves the identical rows and
        shape on both (one shared query function server-side). Raises with
        plain-language help when the client has no credential; the public
        certified feed is :meth:`public_certified`.

        ``category`` filters on the honesty boundary: ``'ntd'`` for
        regulatory-pipeline figures, ``'ops'`` for operations metrics
        (on-time performance, headway adherence — never certifiable, never
        NTD-reported). Every returned row carries its category either way.
        """
        if not self._token:
            raise HeadwayApiError(401, _NO_CREDENTIAL_HELP)
        path = "/machine/metrics" if self.uses_machine_key else "/metrics/values"
        raw = self._get(
            path, self._metric_params(metric, period_start, period_end, category)
        )
        return [MetricValue.from_json(r) for r in raw]

    def machine_metrics(
        self,
        metric: Optional[str] = None,
        period_start: Optional[_dt.date] = None,
        period_end: Optional[_dt.date] = None,
        category: Optional[str] = None,
    ) -> list[MetricValue]:
        """``GET /machine/metrics`` explicitly (machine key, scope
        ``read:metrics``). Same rows and shape as ``GET /metrics/values``;
        rate-limited per key and audit-logged server-side."""
        raw = self._get(
            "/machine/metrics",
            self._metric_params(metric, period_start, period_end, category),
        )
        return [MetricValue.from_json(r) for r in raw]

    def public_certified(self) -> list[MetricValue]:
        """The public open-data feed: certified figures only, no credential
        needed. Serves only rows a certifying official has legally attested
        (and structurally never an operations figure); ``detail`` arrives
        verbatim, simulated flags included — transparency shows the flags,
        it never hides the figures. Rate-limited per client IP."""
        raw = self._get("/public/metrics/certified")
        return [MetricValue.from_json(r) for r in raw]

    def compare(
        self,
        metric: str,
        comparands: Sequence[str],
        scopes: Optional[Sequence[str]] = None,
    ) -> CompareResponse:
        """Compare one metric across 2–4 periods/calc versions per scope
        (``GET /metrics/compare``).

        Each comparand is ``'<period_start>..<period_end>'`` (ISO dates,
        half-open) optionally followed by ``'@<calc_name>:<calc_version>'``;
        the first is the baseline. Deltas in the response are exact decimal
        differences of served figures — comparison affordances, never
        reported figures.

        HONEST LIMIT: this endpoint currently accepts only a signed-in
        human session token (``headway_client.login``). A machine key gets
        the server's 401 — relayed, not disguised.
        """
        if not self._token:
            raise HeadwayApiError(401, _NO_CREDENTIAL_HELP)
        params: list[tuple[str, str]] = [("metric", metric)]
        params += [("comparand", c) for c in comparands]
        params += [("scope", s) for s in (scopes or [])]
        response = self._http.get("/metrics/compare", params=params)
        _raise_for_response(response)
        return CompareResponse.from_json(response.json())

    # -- lineage ("explain this number") ------------------------------------

    def lineage(self, metric_value_id: str) -> LineageNode:
        """The provenance tree for one figure
        (``GET /metrics/values/{id}/lineage``): from the reported value down
        to the content-addressed raw records that produced it. Accepts a
        ``read:metrics`` machine key or a session token. The server fails
        loudly (500) on a figure with no recorded lineage — an unexplained
        number must never look fine."""
        raw = self._get(f"/metrics/values/{metric_value_id}/lineage")
        return LineageNode.from_json(raw)

    def walk_lineage(self, metric_value_id: str) -> LineageTrail:
        """The full "explain this number" trail as a
        :class:`~headway_client.models.LineageTrail`: the tree plus flat
        depth-annotated nodes and the raw-record ids at the bottom. This is
        the differentiator — every figure this client hands you can prove
        itself, and this method is the proof."""
        return LineageTrail(root=self.lineage(metric_value_id))

    # -- data quality --------------------------------------------------------

    def dq_issues(self, status: Optional[str] = None) -> list[DqIssue]:
        """Data-quality issues (``GET /dq/issues``), optionally filtered by
        status ('open', 'owned', 'resolved'). Gaps, conflicts, and
        validation failures live here with an owner and a resolution trail
        — an unexplained gap becomes a finding in an FTA triennial review.

        HONEST LIMIT: currently a signed-in human session token only
        (``headway_client.login``); a machine key gets the server's 401.
        """
        if not self._token:
            raise HeadwayApiError(401, _NO_CREDENTIAL_HELP)
        raw = self._get("/dq/issues", {"status": status})
        return [DqIssue.from_json(r) for r in raw]

    def dq_issue_counts(self, status: Optional[str] = None) -> DqIssueCounts:
        """Severity/status counts over exactly the rows :meth:`dq_issues`
        serves under the same filter (``GET /dq/issues/counts``) — a
        summary can never disagree with the table. Session token only, like
        :meth:`dq_issues`."""
        if not self._token:
            raise HeadwayApiError(401, _NO_CREDENTIAL_HELP)
        raw = self._get("/dq/issues/counts", {"status": status})
        return DqIssueCounts.from_json(raw)
