"""The API image must carry every contract headway_transform opens on import.

WHY THIS TEST EXISTS. The block-label upload calls
``headway_transform.adapters.resolution``. Three modules in that import chain
— ``adapters/spec.py``, ``adapters/resolution.py``, ``envelope.py`` — read a
JSON schema at MODULE SCOPE. So the import itself raises FileNotFoundError
when a contract is missing, before any block-label code runs.

Shipping the resolution spec without the contracts did exactly that: every
unit test passed, CI was green, and the first real upload on a real machine
returned a 500. The unit tests import from a source checkout, where
``spec.py``'s default repo-root ``contracts/`` path resolves. Only the
container has neither the repo root nor the contracts.

Nothing else in this suite can see that gap, because nothing else in this
suite looks at the image. This test reads the transform SOURCE for the
contracts it loads and asserts the API Dockerfile copies each one — so adding
a new import-time schema to transform fails here rather than in production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
API_DOCKERFILE = REPO_ROOT / "services/api/Dockerfile"
TRANSFORM_PKG = REPO_ROOT / "services/transform/headway_transform"

#: `_CONTRACTS_DIR / "some-contract.v0.schema.json"` — how every one of them
#: is spelled. Matching the source beats hard-coding a list that goes stale
#: the moment somebody adds a schema.
_CONTRACT_REF = re.compile(r'_CONTRACTS_DIR\s*/\s*"([^"]+\.json)"')

#: Only the modules the API actually pulls in. adapters/__init__ imports
#: engine, which imports resolution, which imports spec; envelope rides along
#: through headway_transform's own package init.
_IMPORTED_BY_API = (
    "adapters/spec.py",
    "adapters/resolution.py",
    "envelope.py",
)


def _contracts_loaded_at_import() -> set[str]:
    found: set[str] = set()
    for relative in _IMPORTED_BY_API:
        source = (TRANSFORM_PKG / relative).read_text(encoding="utf-8")
        found.update(_CONTRACT_REF.findall(source))
    return found


@pytest.mark.skipif(
    not API_DOCKERFILE.is_file(), reason="Dockerfile absent in this checkout"
)
def test_api_dockerfile_ships_every_import_time_contract():
    dockerfile = API_DOCKERFILE.read_text(encoding="utf-8")
    required = _contracts_loaded_at_import()

    # Sanity: if the regex stops matching, this test would pass vacuously and
    # silently stop guarding anything.
    assert len(required) >= 3, (
        f"Expected to find several import-time contracts in transform, found "
        f"{sorted(required)}. The reference spelling probably changed — fix "
        f"this test rather than deleting it."
    )

    missing = sorted(name for name in required if name not in dockerfile)
    assert not missing, (
        f"services/api/Dockerfile does not COPY {missing}, but "
        f"headway_transform opens them at import time. The API container will "
        f"raise FileNotFoundError on the first block-label upload, with every "
        f"test in this suite still green."
    )


@pytest.mark.skipif(
    not API_DOCKERFILE.is_file(), reason="Dockerfile absent in this checkout"
)
def test_api_image_points_transform_at_the_contracts_it_copied():
    """Copying the files is half of it — transform reads HEADWAY_CONTRACTS_DIR
    and otherwise looks four parents up from its own installed location, which
    in site-packages is nowhere near /app."""
    dockerfile = API_DOCKERFILE.read_text(encoding="utf-8")
    assert "HEADWAY_CONTRACTS_DIR=/app/contracts" in dockerfile
    assert "/app/contracts/" in dockerfile


@pytest.mark.skipif(
    not API_DOCKERFILE.is_file(), reason="Dockerfile absent in this checkout"
)
def test_the_resolution_spec_the_router_looks_for_is_shipped():
    """block_labels._SPEC_CANDIDATES prefers the in-image path; if the image
    does not carry it the endpoint 503s with a packaging message."""
    dockerfile = API_DOCKERFILE.read_text(encoding="utf-8")
    assert "adapters/tripspark/streets/resolution.v0.yaml" in dockerfile
