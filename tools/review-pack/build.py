#!/usr/bin/env python3
"""Build a self-contained adversarial code-review prompt with the diff and
context files inlined — ready to paste into any chat model (Gemini, GPT, ...).

The three slots the external reviewer needs — the diff, the house constraints,
and the design intent — are filled automatically so you hand over ONE document
instead of assembling it by hand each time.

Usage:
    python tools/review-pack/build.py --range fd0d135..HEAD
    python tools/review-pack/build.py                      # defaults to <last tag>..HEAD
    python tools/review-pack/build.py --range A..B --paths services/api services/ingestion
    python tools/review-pack/build.py --range A..B --intent docs/handoffs/0040-*.md docs/adr/0014-*.md

Reviewing DIFFERENT code? Edit the "What to attack" surfaces in
tools/review-pack/prompt-template.md first — this script fills the slots, it
does not know which surfaces matter.

Stdlib only; no dependencies. Output goes to review-packs/ (gitignored) — it
inlines full source already in the repo, so it is never committed.
"""

from __future__ import annotations

import argparse
import glob
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).resolve().parent / "prompt-template.md"

DEFAULT_CONSTRAINTS = ".claude/roles/_SHARED_CONSTRAINTS.md"
# Design-intent defaults match the surfaces written into the template. Change
# these (via --intent) whenever you change the template's "What to attack".
DEFAULT_INTENT = [
    "docs/handoffs/0046-*.md",
    "docs/handoffs/0047-*.md",
    "docs/adr/0011-*.md",
    "docs/adr/0012-*.md",
]


def sh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True)


def since_last_tag() -> str:
    r = sh(["git", "describe", "--tags", "--abbrev=0"])
    if r.returncode != 0:
        sys.exit(
            "no tags found — pass --range explicitly, e.g. --range fd0d135..HEAD"
        )
    return f"{r.stdout.strip()}..HEAD"


def git_diff(rng: str, paths: list[str] | None) -> str:
    cmd = ["git", "diff", rng]
    if paths:
        cmd += ["--", *paths]
    r = sh(cmd)
    if r.returncode != 0:
        sys.exit(f"git diff failed: {r.stderr.strip()}")
    return r.stdout


def resolve(patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for pat in patterns:
        matches = sorted(glob.glob(str(REPO / pat)))
        if not matches:
            sys.exit(f"no file matched intent pattern: {pat}")
        out += [Path(m) for m in matches]
    return out


def read_files(paths: list[Path]) -> str:
    # Delimiter lines, NOT ``` fences: the docs being inlined contain their own
    # code fences, which would terminate a wrapping fence early.
    blocks = []
    for p in paths:
        rel = p.relative_to(REPO)
        blocks.append(f"----- BEGIN {rel} -----\n{p.read_text()}\n----- END {rel} -----")
    return "\n\n".join(blocks)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--range", dest="rng", help="git range (default: <last tag>..HEAD)")
    ap.add_argument("--constraints", default=DEFAULT_CONSTRAINTS)
    ap.add_argument(
        "--intent", nargs="*", default=DEFAULT_INTENT,
        help="design-intent files/globs (handoffs, ADRs)",
    )
    ap.add_argument(
        "--paths", nargs="*", default=None,
        help="optional pathspec to scope the diff (default: whole range)",
    )
    ap.add_argument("--out", default=None, help="output path (default: review-packs/<range>.md)")
    args = ap.parse_args()

    rng = args.rng or since_last_tag()
    diff = git_diff(rng, args.paths)
    if not diff.strip():
        sys.exit(f"empty diff for range {rng} — nothing to review")

    constraints_path = REPO / args.constraints
    if not constraints_path.exists():
        sys.exit(f"constraints file not found: {args.constraints}")

    intent_paths = resolve(args.intent)

    SLOTS = ("{{RANGE}}", "{{DIFF}}", "{{CONSTRAINTS}}", "{{DESIGN_INTENT}}")
    template = TEMPLATE.read_text()
    pack = (
        template
        .replace("{{RANGE}}", rng)
        .replace("{{DIFF}}", diff)
        .replace("{{CONSTRAINTS}}", constraints_path.read_text())
        .replace("{{DESIGN_INTENT}}", read_files(intent_paths))
    )

    if args.out:
        out = Path(args.out)
    else:
        safe = rng.replace("/", "-").replace("..", "_to_")
        out = REPO / "review-packs" / f"review-{safe}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(pack)

    print(f"wrote {out}  ({len(pack.encode()) / 1024:.0f} KB)")
    print(f"  range:       {rng}")
    print(f"  diff bytes:  {len(diff)}")
    print(f"  constraints: {args.constraints}")
    print("  intent:      " + ", ".join(str(p.relative_to(REPO)) for p in intent_paths))
    if args.paths:
        print(f"  scoped to:   {' '.join(args.paths)}")
    # Check only for OUR slot tokens: inlined content (e.g. a CI diff with
    # ${{ matrix }}) legitimately contains other {{...}} that must not trip this.
    leftover = [s for s in SLOTS if s in pack]
    if leftover:
        print(f"  WARNING: unfilled template slot(s) {leftover} — check the template", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
