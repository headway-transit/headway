"""The Headway API client — the ONLY way this service touches Headway data.

Design point 1 of handoff 0034, binding: the MCP server is an API client,
never a database client. The API is the authorization and audit boundary;
this client authenticates with a machine key (``hwk_``, read scopes only)
and holds no database credentials of any kind. Every request lands in
``audit.events`` under the key's identity (actor ``key:<key_prefix>``) —
that auditing is performed by the API, exactly as for any other machine
caller; nothing here can bypass it.

Refusals pass through. When the API answers with an error — a scope
denial, an unknown id, a rate limit — the API's plain-language ``detail``
text is carried verbatim in :class:`ApiRefusal` and surfaced to the
assistant unchanged. This client never rewrites, softens, or swallows a
refusal, and it never invents data to paper over one.
"""

from __future__ import annotations

from typing import Any

import httpx

#: Machine-key prefix per handoff 0006 — makes a leaked key grep-able and
#: distinguishes it from a session JWT. The server refuses to start with
#: anything else (see server.load_config).
KEY_PREFIX = "hwk_"


class ConfigError(Exception):
    """The server is misconfigured (missing/malformed key or URL). Raised at
    startup so the process refuses to start — never at tool-call time with a
    confusing half-working server."""


class ApiRefusal(Exception):
    """The Headway API refused or failed a request.

    ``message`` is the API's own plain-language explanation, verbatim.
    ``http_status`` is the status code. Tool code converts this into a
    structured refusal payload for the assistant — the text is never
    altered on the way through.
    """

    def __init__(self, http_status: int, message: str):
        self.http_status = http_status
        self.message = message
        super().__init__(f"HTTP {http_status}: {message}")


def _refusal_message(response: httpx.Response) -> str:
    """Extract the API's plain-language detail verbatim; fall back to the
    raw body text (still verbatim) when the body is not the FastAPI
    ``{"detail": ...}`` shape."""
    try:
        body = response.json()
    except ValueError:
        return response.text
    if isinstance(body, dict) and "detail" in body:
        detail = body["detail"]
        return detail if isinstance(detail, str) else str(detail)
    return response.text


class HeadwayClient:
    """Thin, read-only client over the machine-key-reachable API surface.

    The reachable surface is exactly what the read scopes and the
    unauthenticated public endpoints grant:

    - ``GET /machine/metrics`` — computed values (scope ``read:metrics``)
    - ``GET /metrics/values/{id}/lineage`` — the "explain this number"
      walk (dual-credential endpoint; the same key works there)
    - ``GET /machine/dq/issues`` — the data-quality queue page (scope
      ``read:dq``, handoff 0039)
    - ``GET /machine/dq/issues/counts`` — whole-queue counts (``read:dq``)
    - ``GET /machine/dq/issues/{id}`` — one issue with its provenance
      (``read:dq``)
    - ``GET /machine/ops/vehicles/latest`` — the live vehicle snapshot
      (scope ``read:ops``, handoff 0039)
    - ``GET /public/metrics/certified`` — the certified open-data list
    - ``GET /public/certifications/{id}/verify`` — Ed25519 signature
      verification of a certification

    Everything else in the API requires a signed-in human session and is
    therefore deliberately absent here (the write actions, user accounts,
    the audit trail, and the paratransit rider surfaces — recorded in
    handoff 0039's docs as deliberately absent, needing a future scope).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        if not api_key.startswith(KEY_PREFIX):
            raise ConfigError(
                "The configured API key does not look like a Headway machine "
                f"key (it must start with '{KEY_PREFIX}'). Set "
                "HEADWAY_MCP_API_KEY to a machine key issued by a Headway "
                "administrator via POST /machine/keys with the "
                "'read:metrics' permission."
            )
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        try:
            response = self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise ApiRefusal(
                0,
                "The Headway API could not be reached "
                f"({exc.__class__.__name__}: {exc}). The MCP server talks "
                "only to the Headway API — check that it is running and that "
                "HEADWAY_API_URL points at it.",
            ) from exc
        if response.status_code >= 400:
            raise ApiRefusal(response.status_code, _refusal_message(response))
        return response.json()

    # -- machine-key surface -------------------------------------------------

    def machine_metrics(
        self,
        metric: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {
            k: v
            for k, v in {
                "metric": metric,
                "period_start": period_start,
                "period_end": period_end,
                "category": category,
            }.items()
            if v is not None
        }
        return self._get("/machine/metrics", params or None)

    def lineage(self, metric_value_id: str) -> dict[str, Any]:
        return self._get(f"/metrics/values/{metric_value_id}/lineage")

    # -- data-quality queue (scope read:dq, handoff 0039) --------------------

    def dq_issues(
        self,
        status: str | None = None,
        severity: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params = {
            k: v
            for k, v in {
                "status": status,
                "severity": severity,
                "limit": limit,
                "cursor": cursor,
            }.items()
            if v is not None
        }
        return self._get("/machine/dq/issues", params or None)

    def dq_counts(self, status: str | None = None) -> dict[str, Any]:
        params = {"status": status} if status is not None else None
        return self._get("/machine/dq/issues/counts", params)

    def dq_issue(self, issue_id: str) -> dict[str, Any]:
        return self._get(f"/machine/dq/issues/{issue_id}")

    # -- operations surface (scope read:ops, handoff 0039) -------------------

    def ops_vehicles(self, max_age_seconds: int | None = None) -> dict[str, Any]:
        params = (
            {"max_age_seconds": max_age_seconds}
            if max_age_seconds is not None
            else None
        )
        return self._get("/machine/ops/vehicles/latest", params)

    # -- public (unauthenticated) surface ------------------------------------

    def public_certified(self) -> list[dict[str, Any]]:
        return self._get("/public/metrics/certified")

    def public_verify_certification(self, certification_id: str) -> dict[str, Any]:
        return self._get(f"/public/certifications/{certification_id}/verify")
