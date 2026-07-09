"""Export the OpenAPI spec to services/api/openapi.json.

This is the contract artifact handed to the Frontend Engineer (contract-first,
ADR-0008 / role file). Run from services/api:

    python3 scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from headway_api.app import Settings, create_app  # noqa: E402


def main() -> None:
    # The secret is never embedded in the spec; any value builds the same schema.
    app = create_app(
        settings=Settings(session_secret="openapi-export-only-not-a-real-secret")
    )
    spec = app.openapi()
    out = Path(__file__).resolve().parent.parent / "openapi.json"
    out.write_text(json.dumps(spec, indent=2) + "\n")
    print(
        f"Wrote {out} — OpenAPI {spec['openapi']}, "
        f"{len(spec['paths'])} paths: {', '.join(sorted(spec['paths']))}"
    )


if __name__ == "__main__":
    main()
