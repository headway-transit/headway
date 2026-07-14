"""Adapter registry: discover mapping specs and resolve source labels fail-closed.

The registry is built once at process start from the adapters directory
(``adapters/`` at the repo root; HEADWAY_ADAPTERS_DIR for installed
deployments). Registration requirements (handoff 0015, design point 1):

- a schema-valid ``mapping.v0.yaml`` (contracts/adapter-mapping.v0.schema.json
  plus the semantic checks in spec.py);
- at least one committed sample fixture under ``fixtures/`` next to the spec —
  a spec without a verified sample fixture cannot be registered (field
  semantics never come from memory or vendor documentation alone);
- a unique source label — two specs claiming one label is a configuration
  defect and the whole registry REFUSES to load (fail loudly at startup,
  never a silent shadowing).

Lookup is FAIL-CLOSED: an envelope source label no registered spec carries
returns None and the consumer refuses the file (blocking DQ issue, raw record
retained, zero canonical writes).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .spec import MappingSpec, SpecError, load_spec

SPEC_FILENAME = "mapping.v0.yaml"
FIXTURES_DIRNAME = "fixtures"
#: Fixture companions that are not vendor data files.
_NON_DATA_SUFFIXES = (".expected.json", ".md")


class RegistryError(Exception):
    """The adapters directory is not a loadable registry (fail at startup)."""


def fixture_files(spec_path: Path) -> list[Path]:
    """The vendor data fixtures registered next to a spec, sorted by name."""
    fixtures_dir = spec_path.parent / FIXTURES_DIRNAME
    if not fixtures_dir.is_dir():
        return []
    return sorted(
        p
        for p in fixtures_dir.iterdir()
        if p.is_file() and not p.name.endswith(_NON_DATA_SUFFIXES)
    )


class AdapterRegistry:
    """source_label -> MappingSpec, built from a scanned adapters directory."""

    def __init__(self, specs: dict[str, MappingSpec]) -> None:
        self._specs = dict(specs)

    @classmethod
    def load(cls, adapters_dir: Path | str) -> "AdapterRegistry":
        """Scan adapters_dir recursively for mapping.v0.yaml files.

        Raises RegistryError listing EVERY defect found — a broken spec never
        silently drops out of the registry (that would turn a typo into a
        fail-open unregistered label days later).
        """
        adapters_dir = Path(adapters_dir)
        if not adapters_dir.is_dir():
            raise RegistryError(
                f"adapters directory {adapters_dir} does not exist — set "
                "HEADWAY_ADAPTERS_DIR to the checked-out adapters/ directory"
            )
        problems: list[str] = []
        specs: dict[str, MappingSpec] = {}
        for spec_path in sorted(adapters_dir.rglob(SPEC_FILENAME)):
            try:
                spec = load_spec(spec_path)
            except SpecError as exc:
                problems.append(str(exc))
                continue
            if not fixture_files(spec_path):
                problems.append(
                    f"{spec_path}: no sample fixtures under "
                    f"{spec_path.parent / FIXTURES_DIRNAME}/ — a spec without "
                    "a verified sample fixture cannot be registered "
                    "(handoff 0015, design point 1)"
                )
                continue
            if spec.source_label in specs:
                problems.append(
                    f"{spec_path}: source_label {spec.source_label!r} is "
                    f"already registered by "
                    f"{specs[spec.source_label].path} — labels must be unique"
                )
                continue
            specs[spec.source_label] = spec
        if problems:
            raise RegistryError(
                f"adapter registry at {adapters_dir} failed to load "
                f"({len(problems)} problem(s)):\n- " + "\n- ".join(problems)
            )
        return cls(specs)

    def lookup(self, source_label: str) -> Optional[MappingSpec]:
        """The spec registered for a source label, or None (fail closed)."""
        return self._specs.get(source_label)

    def labels(self) -> list[str]:
        return sorted(self._specs)

    def __len__(self) -> int:
        return len(self._specs)
