"""Guardrail test: core calculation modules import nothing but stdlib.

No network, no clocks, no randomness inside a calculation — time comes from
inputs. This test parses every headway_calc module and asserts each import is
either stdlib or headway_calc itself, and that forbidden nondeterminism
sources (random, time-as-clock, urllib, socket, ...) never appear.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "headway_calc"

FORBIDDEN_ROOTS = {
    "random", "secrets", "time", "socket", "http", "urllib", "requests",
    "asyncio", "subprocess", "os",
}


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_modules_import_only_stdlib_and_self():
    stdlib = sys.stdlib_module_names
    for module_path in sorted(PACKAGE_DIR.glob("*.py")):
        roots = _import_roots(module_path)
        for root in roots:
            assert root == "headway_calc" or root in stdlib, (
                f"{module_path.name} imports non-stdlib module {root!r}"
            )
            assert root not in FORBIDDEN_ROOTS, (
                f"{module_path.name} imports forbidden nondeterminism source {root!r}"
            )
