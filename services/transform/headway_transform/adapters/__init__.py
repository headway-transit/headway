"""Vendor adapter framework v0 (handoff 0015).

Adapters are DECLARATIVE mappings from vendor export formats onto the open
contracts (ADR-0006: Headway core speaks only open contracts; vendors get
adapters, never pipeline forks). This package is the transform-side runtime:

- ``spec``     — load + machine-validate ``mapping.v0.yaml`` files against
                 ``contracts/adapter-mapping.v0.schema.json``;
- ``registry`` — discover registered adapters under ``adapters/`` and resolve
                 envelope source labels FAIL-CLOSED (an unregistered label
                 refuses; nothing is guessed);
- ``engine``   — execute a spec over one vendor file: dialect-aware parsing,
                 row filters, coercions/constants/derived fields/unit
                 conversions, declared-timezone handling (never guessed),
                 the TARGET CONTRACT's validation, per-row quarantine via the
                 row_guard patterns, and lineage from every canonical row to
                 the content-addressed raw vendor bytes AND to the exact
                 mapping-spec version that mapped it;
- ``harness``  — the validation harness core behind ``adapters/validate``
                 (every fixture row mapped or explicitly quarantined with a
                 reason; contract validation green; deterministic round-trip).

Placement decision (documented per handoff 0015 design point 2): the runtime
is transform-side Python because both v0 target contracts land in Python
normalizers here — the adapter engine REUSES ``tides_passenger_events`` /
``dr_trips`` (the verified contract validation + canonical row construction +
idempotent writer paths) instead of duplicating them in Go.
"""

from .engine import AdapterRunResult, run_adapter
from .registry import AdapterRegistry, RegistryError
from .spec import MappingSpec, SpecError, load_spec

__all__ = [
    "AdapterRegistry",
    "AdapterRunResult",
    "MappingSpec",
    "RegistryError",
    "SpecError",
    "load_spec",
    "run_adapter",
]
