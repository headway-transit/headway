"""Who a request came from — the one answer every per-caller control uses.

WHY THIS EXISTS
---------------
Seven places in this API held a caller responsible at an address, and all
seven wrote the same expression::

    request.client.host if request.client else "unknown"

That is the address of whatever opened the TCP connection. On the LAN profile
(deploy/compose/caddy/Caddyfile) that is always Caddy, on the compose network,
with one address for the entire office. So before this module existed:

- **The failure-audit throttle coalesced everyone into one bucket.** One
  person mistyping a password, or one attacker, suppressed the audit record of
  every other failed sign-in in the building. A control whose whole job is to
  keep the trail honest was blinding it.
- **The public and SSO rate limiters were one shared allowance.** Whoever
  spent it first locked out the rest of the agency. ``app.py`` even sized the
  SSO limit around this — "generous even for a whole agency arriving behind
  one reverse-proxy address" — which treats an identity bug as a sizing
  question. Raising a shared limit does not stop one caller from spending all
  of it.
- **Every audit row recorded the proxy's container address.** For a system
  whose reason to exist is an evidence trail, "who did this" read the same for
  everybody.

TRUSTING A HEADER IS THE DANGEROUS PART
---------------------------------------
``X-Forwarded-For`` is written by whoever is talking to you. An API that
believes it unconditionally is WORSE than one that ignores it: every caller
picks their own bucket, per request, and no rate limit or throttle means
anything. So:

1. **The header is read only when the immediate peer is a configured trusted
   proxy.** Nothing else is ever consulted.
2. **The set of trusted proxies defaults to EMPTY.** An installation that is
   directly exposed, or that has not been told about its proxy, behaves
   exactly as it did before this module — the peer address, unspoofable.
   Safe by default is the default.
3. **The chain is read RIGHT TO LEFT.** A proxy APPENDS the peer it actually
   saw, so the rightmost entry is the only one it vouched for; everything to
   the left was supplied by the caller and is decoration. Reading left to
   right — the common mistake — reads exactly the part an attacker controls.

The result is normalized through ``ipaddress``, so one caller cannot occupy
several buckets by varying the spelling of one address (``::ffff:10.0.0.7``,
``[::1]:5000``, ``010.0.0.7``).

CONFIGURING IT
--------------
``HEADWAY_TRUSTED_PROXIES``: a comma-separated list of addresses or CIDR
blocks, e.g. ``172.18.0.0/16`` for a compose network, or ``10.0.0.5``. A value
that is not a valid address or network refuses at STARTUP rather than being
skipped — a typo that silently disabled the whole mechanism would leave an
operator believing they had per-client limits when they had none.
"""

from __future__ import annotations

import ipaddress
from typing import Iterable, Optional, Sequence

#: What every caller-facing control used before, and still uses when the peer
#: address is genuinely unavailable (an ASGI transport with no client, which
#: happens in-process under TestClient). Kept as the literal string the audit
#: trail already contains, so history stays readable.
UNKNOWN = "unknown"

FORWARDED_FOR_HEADER = "x-forwarded-for"

#: A forwarded chain longer than this is not a deployment, it is someone
#: paying us to parse. The walk stops; the peer address is used.
MAX_FORWARDED_HOPS = 32

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


class InvalidTrustedProxy(ValueError):
    """Raised at startup rather than silently trusting nothing.

    Refusing to boot is the right failure: the alternative is an operator who
    configured a proxy, saw no error, and believes per-client limits are in
    force when every request is still bucketed as the proxy.
    """


def parse_trusted_proxies(raw: str | None) -> tuple[str, ...]:
    """Split and VALIDATE ``HEADWAY_TRUSTED_PROXIES``.

    Accepts bare addresses (``10.0.0.5``, ``::1``) and CIDR blocks
    (``172.18.0.0/16``). Empty or unset yields an empty tuple, which means
    "trust nothing" — the safe default, not an error.
    """
    if not raw or not raw.strip():
        return ()
    entries = [part.strip() for part in raw.split(",")]
    out: list[str] = []
    for entry in entries:
        if not entry:
            continue
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise InvalidTrustedProxy(
                f"HEADWAY_TRUSTED_PROXIES contains {entry!r}, which is not an "
                f"IP address or CIDR block. Headway refuses to start rather "
                f"than ignore it: a typo here would silently leave every "
                f"caller sharing one rate-limit bucket and one audit-throttle "
                f"bucket, with nothing to show that it had happened. Use a "
                f"comma-separated list like '172.18.0.0/16, 10.0.0.5'."
            ) from exc
        out.append(entry)
    return tuple(out)


def networks(entries: Sequence[str]) -> tuple[Network, ...]:
    """Compile validated entries once, at startup, not per request."""
    return tuple(ipaddress.ip_network(entry, strict=False) for entry in entries)


def _address(text: str) -> Optional[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """One forwarded-chain entry as an address, or None if it is not one.

    Tolerates the shapes proxies actually emit: ``[2001:db8::1]:443``,
    ``203.0.113.9:51234``, and plain addresses. A port is not identity — two
    requests from one machine are one caller — so it is dropped.
    """
    candidate = text.strip()
    if not candidate:
        return None
    if candidate.startswith("["):
        # [v6]:port or [v6]
        closing = candidate.find("]")
        if closing == -1:
            return None
        candidate = candidate[1:closing]
    elif candidate.count(":") == 1:
        # Exactly one colon means v4:port; a bare IPv6 address has several.
        candidate = candidate.split(":", 1)[0]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _is_trusted(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    trusted: Iterable[Network],
) -> bool:
    return any(address in network for network in trusted)


def resolve(
    peer: Optional[str],
    forwarded_for: Optional[str],
    trusted: Sequence[Network],
) -> str:
    """The caller's address, given the peer, the header, and who is trusted.

    Pure — no Request, no app state — so the security-relevant decisions can
    be tested as a table instead of through seven endpoints.
    """
    if peer is None:
        return UNKNOWN
    peer_address = _address(peer)
    if peer_address is None:
        # An address we cannot parse cannot be checked against the trusted
        # set, so the header stays unread. Returned verbatim: a bucket key
        # only has to be stable and unforgeable, not pretty.
        return peer
    if not trusted or not _is_trusted(peer_address, trusted):
        # The peer is the caller, or is an untrusted middlebox. Either way its
        # claims about someone else are not evidence.
        return str(peer_address)
    if not forwarded_for:
        return str(peer_address)

    hops = forwarded_for.split(",")
    if len(hops) > MAX_FORWARDED_HOPS:
        return str(peer_address)
    # RIGHT TO LEFT: the rightmost entry is the one the trusted proxy saw and
    # appended itself. Everything left of it is caller-supplied.
    for hop in reversed(hops):
        candidate = _address(hop)
        if candidate is None:
            continue
        if _is_trusted(candidate, trusted):
            # Another one of ours, further out. Keep walking.
            continue
        return str(candidate)
    # A chain made entirely of our own proxies: the caller is one of them.
    return str(peer_address)


def client_address(request) -> str:
    """The address to hold this request's caller responsible at.

    Reads the trusted-proxy set from ``app.state`` and tolerates its absence,
    matching how the rate limiter and audit throttle already tolerate a bare
    test app: no configuration means the peer address, which is what every
    call site did before this module existed.
    """
    trusted = getattr(request.app.state, "trusted_proxy_networks", ())
    peer = request.client.host if request.client else None
    forwarded = request.headers.get(FORWARDED_FOR_HEADER)
    return resolve(peer, forwarded, trusted)
