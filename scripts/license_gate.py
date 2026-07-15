#!/usr/bin/env python3
"""ADR-0001 license gate — enforce the dependency license tiers in CI and locally.

Policy (docs/adr/0001-core-license-apache-2-and-osi-only-dependencies.md,
Amendment 1 — Dependency license tiers):

  Tier 1  Headway's own code: Apache-2.0 (not checked here; own packages are
          skipped by name).
  Tier 2  Permissive dependencies (Apache-2.0, MIT, BSD, ISC, and
          equivalents): PASS without ceremony.
  Tier 3  Weak-copyleft dependencies (LGPL*, MPL-2.0, EPL-class): PASS ONLY
          if listed in scripts/license_allowlist.toml with a one-line
          reviewed rationale. The allowlist can never rescue tier 4.
  Tier 4  Strong copyleft (GPL, AGPL) and all non-OSI licenses (BSL/BUSL,
          SSPL, Confluent Community License, proprietary): FAIL the build.

  Unknown / undetectable licenses FAIL LOUDLY — the gate never passes a
  dependency it cannot classify. Use --explain for detection provenance.

Ecosystems:
  go      services/ingestion — prefers `go-licenses csv ./...`
          (go install github.com/google/go-licenses@latest); falls back to
          `go mod download -json all` + LICENSE-file fingerprinting in the
          module cache when go-licenses is not installed.
  python  resolves each services/*/pyproject.toml and clients/*/pyproject.toml
          [project.dependencies] (+ all optional-dependency extras) and
          db/requirements.txt against
          the installed environment via importlib.metadata, walking the
          transitive Requires-Dist closure. This pyproject-driven mode is the
          default; --all-installed scans every installed distribution instead.
  node    web/node_modules/*/package.json license fields. Skipped (not
          failed) when web/package.json does not exist yet.

Usage:
  python3 scripts/license_gate.py                    # all ecosystems
  python3 scripts/license_gate.py --ecosystem python
  python3 scripts/license_gate.py --ecosystem go --explain

Exit code: 0 = all scanned dependencies pass; 1 = at least one failure.
Stdlib-only by design (ADR-0001 gate must not itself drag in dependencies).

Local Go note: if your system `go` is older than go.mod's version and the
toolchain was auto-fetched (GOTOOLCHAIN=auto), go-licenses mis-detects GOROOT
and errors on stdlib packages. Put the fetched toolchain first on PATH and
export its GOROOT, e.g.:
  export GOROOT=$(go env GOPATH)/pkg/mod/golang.org/toolchain@v0.0.1-go<ver>.linux-amd64
  export PATH=$GOROOT/bin:$PATH
CI is unaffected (actions/setup-go installs the go.mod version natively).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Policy: license classification
# --------------------------------------------------------------------------

TIER_PERMISSIVE = "permissive (tier 2)"
TIER_WEAK = "weak-copyleft (tier 3)"
TIER_PUBLIC_DOMAIN = "public-domain dedication (tier 3b, dev-only)"
TIER_FORBIDDEN = "strong-copyleft/non-OSI (tier 4)"
TIER_UNKNOWN = "unknown"

# Canonical SPDX-ish identifiers. Keys are canonicalized via _canon_token().
PERMISSIVE = {
    "APACHE-2.0", "MIT", "MIT-0", "BSD-2-CLAUSE", "BSD-3-CLAUSE",
    "BSD-3-CLAUSE-CLEAR", "BSD-2-CLAUSE-PATENT", "ISC", "PYTHON-2.0",
    "PSF-2.0", "UNLICENSE", "0BSD", "ZLIB", "BLUEOAK-1.0.0", "HPND",
    "APACHE-2.0-WITH-LLVM-EXCEPTION",
}
WEAK_COPYLEFT = {
    "LGPL-2.0-ONLY", "LGPL-2.0-OR-LATER", "LGPL-2.1-ONLY",
    "LGPL-2.1-OR-LATER", "LGPL-3.0-ONLY", "LGPL-3.0-OR-LATER",
    "LGPL-3.0-WITH-EXCEPTION", "LGPL",
    "MPL-1.1", "MPL-2.0", "EPL-1.0", "EPL-2.0", "CDDL-1.0", "CDDL-1.1",
}
FORBIDDEN = {
    "GPL-1.0-ONLY", "GPL-1.0-OR-LATER", "GPL-2.0-ONLY", "GPL-2.0-OR-LATER",
    "GPL-3.0-ONLY", "GPL-3.0-OR-LATER", "GPL",
    "AGPL-1.0-ONLY", "AGPL-3.0-ONLY", "AGPL-3.0-OR-LATER", "AGPL",
    "BUSL-1.1", "BSL-1.1", "SSPL-1.0", "ELASTIC-2.0",
    "CONFLUENT-COMMUNITY-1.0", "CC-BY-NC-4.0", "CC-BY-NC-SA-4.0",
    "PROPRIETARY", "COMMERCIAL", "BSD-4-CLAUSE",
}
# ADR-0001 Amendment 2: public-domain dedications are NOT OSI-approved
# (CC0's OSI review was withdrawn over its patent-rights reservation) but
# are permitted for dev/test/build-only dependencies that never ship in a
# release artifact — via an allowlist entry carrying scope = "dev".
# Runtime/shipped use remains excluded pending case-by-case ADR review.
PUBLIC_DOMAIN = {
    "CC0-1.0",
}

# Free-text and trove-classifier aliases -> canonical token above.
# Keys are lowercased with whitespace/punctuation squashed by _squash().
ALIASES = {
    "apache20": "APACHE-2.0",
    "apache2": "APACHE-2.0",
    "apachelicense20": "APACHE-2.0",
    "apachelicenseversion20": "APACHE-2.0",
    "apachesoftwarelicense": "APACHE-2.0",
    "asl20": "APACHE-2.0",
    "mit": "MIT",
    "mitlicense": "MIT",
    "expat": "MIT",
    "bsd": "BSD-3-CLAUSE",
    "bsdlicense": "BSD-3-CLAUSE",
    "bsd2clause": "BSD-2-CLAUSE",
    "bsd2clauselicense": "BSD-2-CLAUSE",
    "simplifiedbsd": "BSD-2-CLAUSE",
    "bsd3clause": "BSD-3-CLAUSE",
    "bsd3clauselicense": "BSD-3-CLAUSE",
    "3clausebsdlicense": "BSD-3-CLAUSE",
    "2clausebsdlicense": "BSD-2-CLAUSE",
    "newbsd": "BSD-3-CLAUSE",
    "modifiedbsd": "BSD-3-CLAUSE",
    "bsd3clausenewedorrevisedlicense": "BSD-3-CLAUSE",
    "isc": "ISC",
    "isclicense": "ISC",
    "isclicenseiscl": "ISC",
    "psf": "PSF-2.0",
    "psf20": "PSF-2.0",
    "python20": "PYTHON-2.0",
    "pythonsoftwarefoundationlicense": "PSF-2.0",
    "zlib": "ZLIB",
    "zliblibpnglicense": "ZLIB",
    "0bsd": "0BSD",
    "zeroclausebsd": "0BSD",
    "theunlicenseunlicense": "UNLICENSE",
    "unlicense": "UNLICENSE",
    "publicdomain": "UNLICENSE",
    "lgpl": "LGPL",
    "lgplv2": "LGPL-2.0-ONLY",
    "lgplv21": "LGPL-2.1-ONLY",
    "lgplv3": "LGPL-3.0-ONLY",
    "lgpl21": "LGPL-2.1-ONLY",
    "lgpl30": "LGPL-3.0-ONLY",
    "lgpl30only": "LGPL-3.0-ONLY",
    "lgpl30orlater": "LGPL-3.0-OR-LATER",
    "lgpl30withexception": "LGPL-3.0-WITH-EXCEPTION",
    "gnulessergeneralpubliclicensev3lgplv3": "LGPL-3.0-ONLY",
    "gnulessergeneralpubliclicensev3orlaterlgplv3": "LGPL-3.0-OR-LATER",
    "gnulessergeneralpubliclicensev2lgplv2": "LGPL-2.0-ONLY",
    "gnulessergeneralpubliclicensev21lgplv21": "LGPL-2.1-ONLY",
    "gnulibraryorlessergeneralpubliclicenselgpl": "LGPL",
    "mpl20": "MPL-2.0",
    "mozillapubliclicense20mpl20": "MPL-2.0",
    "mozillapubliclicense20": "MPL-2.0",
    "epl10": "EPL-1.0",
    "epl20": "EPL-2.0",
    "eclipsepubliclicense20epl20": "EPL-2.0",
    "eclipsepubliclicense10epl10": "EPL-1.0",
    "gpl": "GPL",
    "gplv2": "GPL-2.0-ONLY",
    "gplv3": "GPL-3.0-ONLY",
    "gnugeneralpubliclicensev2gplv2": "GPL-2.0-ONLY",
    "gnugeneralpubliclicensev3gplv3": "GPL-3.0-ONLY",
    "gnugeneralpubliclicensev3orlatergplv3": "GPL-3.0-OR-LATER",
    "agpl": "AGPL",
    "agplv3": "AGPL-3.0-ONLY",
    "gnuafferogeneralpubliclicensev3agplv3": "AGPL-3.0-ONLY",
    "gnuafferogeneralpubliclicensev3orlateragplv3": "AGPL-3.0-OR-LATER",
    "bsl11": "BSL-1.1",
    "businesssourcelicense11": "BUSL-1.1",
    "serversidepubliclicense": "SSPL-1.0",
    "sspl10": "SSPL-1.0",
}


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _canon_token(token: str) -> str:
    """Map one license token (SPDX id, trove classifier tail, or free text)
    to a canonical identifier, or return it uppercased if unrecognized."""
    token = token.strip().strip("()")
    if not token:
        return ""
    upper = token.upper()
    # Exact SPDX-style ids (normalize legacy '-only'-less GNU ids).
    spdx_fixups = {
        "GPL-2.0": "GPL-2.0-ONLY", "GPL-2.0+": "GPL-2.0-OR-LATER",
        "GPL-3.0": "GPL-3.0-ONLY", "GPL-3.0+": "GPL-3.0-OR-LATER",
        "LGPL-2.1": "LGPL-2.1-ONLY", "LGPL-2.1+": "LGPL-2.1-OR-LATER",
        "LGPL-3.0": "LGPL-3.0-ONLY", "LGPL-3.0+": "LGPL-3.0-OR-LATER",
        "AGPL-3.0": "AGPL-3.0-ONLY", "AGPL-3.0+": "AGPL-3.0-OR-LATER",
        "APACHE-2": "APACHE-2.0", "PSF": "PSF-2.0",
    }
    if upper in spdx_fixups:
        return spdx_fixups[upper]
    if upper in PERMISSIVE | WEAK_COPYLEFT | PUBLIC_DOMAIN | FORBIDDEN:
        return upper
    return ALIASES.get(_squash(token), upper)


def _tier_of_canonical(canon: str) -> str:
    if canon in PERMISSIVE:
        return TIER_PERMISSIVE
    if canon in WEAK_COPYLEFT:
        return TIER_WEAK
    if canon in PUBLIC_DOMAIN:
        return TIER_PUBLIC_DOMAIN
    if canon in FORBIDDEN:
        return TIER_FORBIDDEN
    # Prefix rules for versioned families (order matters: LGPL before GPL).
    if canon.startswith(("LGPL", "MPL-", "EPL-", "CDDL-")):
        return TIER_WEAK
    if canon.startswith(("AGPL", "GPL", "SSPL", "BUSL", "CC-BY-NC")):
        return TIER_FORBIDDEN
    return TIER_UNKNOWN


# Severity order for compound expressions (OR takes the best part, AND the
# worst). Public-domain dedications rank between weak-copyleft and forbidden:
# they can pass, but only via a scope="dev" allowlist entry (Amendment 2) —
# stricter than tier 3, never as fatal as tier 4. (numpy 2.x exposed the
# earlier omission of this tier here: its 'BSD-3-Clause AND … AND CC0-1.0'
# expression crashed the gate instead of being judged — 2026-07-15.)
_TIER_RANK = {TIER_PERMISSIVE: 0, TIER_WEAK: 1, TIER_PUBLIC_DOMAIN: 2,
              TIER_FORBIDDEN: 3, TIER_UNKNOWN: 4}


def classify(license_expr: str) -> tuple[str, str]:
    """Classify a license expression. Returns (tier, canonical_form).

    Handles 'A OR B' (best alternative wins — we may choose either),
    'A AND B' (worst part wins — every part binds us), and 'X WITH exc'
    (exception never changes the tier of the base license).
    """
    if not license_expr or not license_expr.strip():
        return TIER_UNKNOWN, "(none)"
    expr = license_expr.strip()
    # Drop parentheses; we only handle flat OR/AND (sufficient in practice).
    flat = re.sub(r"[()]", " ", expr)
    if re.search(r"\bOR\b", flat, re.IGNORECASE):
        parts = re.split(r"\bOR\b", flat, flags=re.IGNORECASE)
        results = [classify(p) for p in parts if p.strip()]
        best = min(results, key=lambda r: _TIER_RANK[r[0]])
        return best[0], " OR ".join(r[1] for r in results)
    if re.search(r"\bAND\b", flat, re.IGNORECASE):
        parts = re.split(r"\bAND\b", flat, flags=re.IGNORECASE)
        results = [classify(p) for p in parts if p.strip()]
        worst = max(results, key=lambda r: _TIER_RANK[r[0]])
        return worst[0], " AND ".join(r[1] for r in results)
    # 'WITH exception' — classify the base id; keep the full form for display.
    m = re.match(r"\s*(\S+)\s+WITH\s+(\S+)\s*$", flat, re.IGNORECASE)
    if m:
        base = _canon_token(m.group(1))
        # Special-case: LGPL-3.0 + linking exception is the psycopg precedent;
        # the exception relaxes obligations but the tier stays weak-copyleft.
        tier = _tier_of_canonical(base)
        return tier, f"{base} WITH {m.group(2)}"
    canon = _canon_token(flat)
    return _tier_of_canonical(canon), canon


# --------------------------------------------------------------------------
# Allowlist
# --------------------------------------------------------------------------

def _norm_pkg(name: str) -> str:
    """PEP 503-style normalization, also fine for Go paths / npm names."""
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def load_allowlist(path: Path) -> dict[tuple[str, str], dict]:
    if not path.is_file():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = {}
    for e in data.get("allow", []):
        pkg = e.get("package", "")
        eco = e.get("ecosystem", "")
        if not pkg or not eco or not e.get("rationale"):
            raise SystemExit(
                f"license_allowlist.toml: entry {e!r} is missing "
                "package/ecosystem/rationale — every exception must be "
                "reviewed and justified (ADR-0001 Amendment 1, tier 3).")
        entries[(eco, _norm_pkg(pkg))] = e
    return entries


# --------------------------------------------------------------------------
# Result model
# --------------------------------------------------------------------------

@dataclass
class Dep:
    ecosystem: str
    name: str
    version: str
    license: str        # raw, as detected
    canonical: str = ""
    tier: str = ""
    status: str = ""    # PASS | PASS (allowlisted) | FAIL
    reason: str = ""
    provenance: str = ""  # how the license was detected (--explain)


@dataclass
class EcosystemReport:
    name: str
    deps: list[Dep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: bool = False
    hard_error: str = ""  # scan-level failure (fail loudly)


def judge(dep: Dep, allowlist: dict) -> None:
    tier, canon = classify(dep.license)
    dep.tier, dep.canonical = tier, canon
    key = (dep.ecosystem, _norm_pkg(dep.name))
    # Exact match first; then glob entries (e.g. platform-binary families
    # like lightningcss-* that share one upstream project and license).
    entry = allowlist.get(key)
    if entry is None:
        for (eco, pat), e in allowlist.items():
            if eco == dep.ecosystem and ("*" in pat or "?" in pat) \
                    and fnmatch.fnmatch(_norm_pkg(dep.name), pat):
                entry = e
                break
    if tier == TIER_PERMISSIVE:
        dep.status = "PASS"
        dep.reason = "permissive — ADR-0001 tier 2, allowed without ceremony"
    elif tier == TIER_WEAK:
        if entry is not None:
            dep.status = "PASS (allowlisted)"
            dep.reason = (f"weak-copyleft, reviewed allowlist entry: "
                          f"{entry.get('rationale', '')}")
        else:
            dep.status = "FAIL"
            dep.reason = (
                f"license '{dep.license}' is weak-copyleft — ADR-0001 "
                f"Amendment 1 tier 3 allows it ONLY with a reviewed entry in "
                f"scripts/license_allowlist.toml; add one with a one-line "
                f"rationale (unmodified, imported-only) or drop the dependency")
    elif tier == TIER_PUBLIC_DOMAIN:
        if entry is not None and entry.get("scope") == "dev":
            dep.status = "PASS (allowlisted)"
            dep.reason = (f"public-domain dedication, dev-only reviewed entry "
                          f"(ADR-0001 Amendment 2): {entry.get('rationale', '')}")
        else:
            dep.status = "FAIL"
            dep.reason = (
                f"license '{dep.license}' is a public-domain dedication (not "
                f"OSI-approved) — ADR-0001 Amendment 2 permits it ONLY for "
                f"dev/test/build-only dependencies via an allowlist entry "
                f"carrying scope = \"dev\" (reviewer asserts it never ships); "
                f"runtime use needs case-by-case ADR review")
    elif tier == TIER_FORBIDDEN:
        dep.status = "FAIL"
        dep.reason = (
            f"license '{dep.license}' is strong-copyleft or non-OSI — "
            f"ADR-0001 Amendment 1 tier 4 excludes GPL/AGPL/BSL/SSPL/"
            f"proprietary from the core critical path; the allowlist cannot "
            f"rescue this tier. Replace the dependency or raise an ADR")
    else:
        dep.status = "FAIL"
        dep.reason = (
            f"license could not be determined (detected: '{dep.license or '<empty>'}') "
            f"— the gate fails loudly on unknowns per ADR-0001; it never "
            f"passes what it cannot classify. Re-run with --explain, then "
            f"either fix the metadata source or add the license to the "
            f"policy map after review")


# --------------------------------------------------------------------------
# Go ecosystem
# --------------------------------------------------------------------------

GO_MODULE_DIR = "services/ingestion"
OWN_MODULE_PREFIX = "github.com/headway-transit/headway"


def _find_go_licenses() -> str | None:
    p = shutil.which("go-licenses")
    if p:
        return p
    gopath = subprocess.run(["go", "env", "GOPATH"], capture_output=True,
                            text=True).stdout.strip()
    for cand in (Path(gopath) / "bin" / "go-licenses",
                 Path.home() / "go" / "bin" / "go-licenses"):
        if cand.is_file():
            return str(cand)
    return None


def scan_go(repo: Path, allowlist: dict) -> EcosystemReport:
    rep = EcosystemReport("go")
    mod_dir = repo / GO_MODULE_DIR
    if not (mod_dir / "go.mod").is_file():
        rep.skipped = True
        rep.notes.append(f"{GO_MODULE_DIR}/go.mod not found — skipped")
        return rep
    tool = _find_go_licenses()
    if tool:
        # --ignore: the Headway module itself is tier 1 (Apache-2.0 at the
        # repo root); go-licenses would otherwise fail looking for a LICENSE
        # at the module root inside the monorepo.
        rep.notes.append(f"source: `go-licenses csv --ignore "
                         f"{OWN_MODULE_PREFIX} ./...` ({tool})")
        proc = subprocess.run(
            [tool, "csv", "--ignore", OWN_MODULE_PREFIX, "./..."],
            cwd=mod_dir, capture_output=True, text=True)
        if proc.returncode != 0 and not proc.stdout.strip():
            rep.hard_error = (
                "go-licenses failed and produced no output — failing loudly "
                f"rather than passing unscanned deps:\n{proc.stderr.strip()}")
            return rep
        if proc.stderr.strip():
            rep.notes.append("go-licenses stderr (informational): "
                             + proc.stderr.strip().splitlines()[0]
                             + (" …" if len(proc.stderr.strip().splitlines()) > 1 else ""))
        for line in proc.stdout.splitlines():
            parts = line.strip().split(",")
            if len(parts) < 3 or not parts[0]:
                continue
            module, url, lic = parts[0], parts[1], ",".join(parts[2:])
            if module.startswith(OWN_MODULE_PREFIX):
                continue  # tier 1: Headway core, Apache-2.0 by policy
            dep = Dep("go", module, "", lic,
                      provenance=f"go-licenses csv (license URL: {url})")
            judge(dep, allowlist)
            rep.deps.append(dep)
    else:
        rep.notes.append(
            "go-licenses not installed — falling back to module-cache LICENSE "
            "fingerprinting over the `go list -deps ./...` import graph. For "
            "the authoritative scan: go install github.com/google/go-licenses@latest")
        rep.deps.extend(_scan_go_fallback(mod_dir, rep, allowlist))
    return rep


_LICENSE_FILE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING",
                       "LICENSE-APACHE", "LICENSE.MIT", "UNLICENSE",
                       "COPYING.LESSER", "License", "license")


def _sniff_license_text(text: str) -> str:
    t = re.sub(r"\s+", " ", text[:6000])
    checks = [
        ("Business Source License", "BUSL-1.1"),
        ("Server Side Public License", "SSPL-1.0"),
        ("GNU AFFERO GENERAL PUBLIC LICENSE", "AGPL-3.0-only"),
        ("GNU LESSER GENERAL PUBLIC LICENSE Version 3", "LGPL-3.0-only"),
        ("GNU LESSER GENERAL PUBLIC LICENSE Version 2.1", "LGPL-2.1-only"),
        ("GNU LESSER GENERAL PUBLIC LICENSE", "LGPL"),
        ("GNU GENERAL PUBLIC LICENSE Version 3", "GPL-3.0-only"),
        ("GNU GENERAL PUBLIC LICENSE Version 2", "GPL-2.0-only"),
        ("GNU GENERAL PUBLIC LICENSE", "GPL"),
        ("Mozilla Public License Version 2.0", "MPL-2.0"),
        ("Mozilla Public License, v. 2.0", "MPL-2.0"),
        ("Eclipse Public License - v 2.0", "EPL-2.0"),
        ("Apache License Version 2.0", "Apache-2.0"),
        ("Apache License, Version 2.0", "Apache-2.0"),
        ("free and unencumbered software released into the public domain",
         "Unlicense"),
        ("Permission to use, copy, modify, and/or distribute this software",
         "ISC"),
        ("Permission is hereby granted, free of charge", "MIT"),
    ]
    for needle, spdx in checks:
        if needle.lower() in t.lower():
            return spdx
    if "redistribution and use in source and binary forms" in t.lower():
        return ("BSD-3-Clause" if "neither the name" in t.lower()
                else "BSD-2-Clause")
    return ""


def _scan_go_fallback(mod_dir: Path, rep: EcosystemReport,
                      allowlist: dict) -> list[Dep]:
    # Make sure the module cache is populated, then enumerate exactly the
    # modules the build imports (NOT `go mod download all`, which can drag in
    # stale go.sum entries that are not part of the import graph).
    subprocess.run(["go", "mod", "download"], cwd=mod_dir,
                   capture_output=True, text=True)
    proc = subprocess.run(
        ["go", "list", "-deps", "-f",
         '{{if .Module}}{{.Module.Path}}\t{{.Module.Version}}\t{{.Module.Dir}}{{end}}',
         "./..."],
        cwd=mod_dir, capture_output=True, text=True)
    if proc.returncode != 0:
        rep.hard_error = ("go list -deps failed — cannot enumerate the "
                          "import graph; failing loudly:\n"
                          + proc.stderr.strip())
        return []
    modules: dict[str, tuple[str, str]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        path, ver, moddir = parts
        if not path or path.startswith(OWN_MODULE_PREFIX):
            continue
        modules.setdefault(path, (ver, moddir))
    deps = []
    for path, (ver, moddir) in sorted(modules.items()):
        lic, prov = "", "no LICENSE-like file found in module cache"
        if moddir:
            for name in _LICENSE_FILE_NAMES:
                f = Path(moddir) / name
                if f.is_file():
                    lic = _sniff_license_text(
                        f.read_text(encoding="utf-8", errors="replace"))
                    prov = f"fingerprinted {f}"
                    break
        dep = Dep("go", path, ver, lic, provenance=prov)
        judge(dep, allowlist)
        deps.append(dep)
    return deps


# --------------------------------------------------------------------------
# Python ecosystem
# --------------------------------------------------------------------------

_REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?")


def _parse_req(req: str) -> tuple[str, frozenset[str], str]:
    """'psycopg[binary]>=3.1; extra == "db"' -> (name, extras, marker)."""
    marker = ""
    if ";" in req:
        req, marker = req.split(";", 1)
    m = _REQ_RE.match(req)
    if not m:
        return "", frozenset(), marker.strip()
    extras = frozenset(e.strip().lower() for e in (m.group(2) or "").split(",")
                       if e.strip())
    return m.group(1), extras, marker.strip()


def _marker_extras(marker: str) -> set[str]:
    return set(re.findall(r"""extra\s*==\s*['"]([^'"]+)['"]""", marker))


def _dist_license(dist) -> tuple[str, str]:
    """Return (license_string, provenance) from installed metadata."""
    md = dist.metadata
    expr = md.get("License-Expression")
    if expr:
        return expr.strip(), "core metadata License-Expression"
    classifiers = [c for c in (md.get_all("Classifier") or [])
                   if c.startswith("License ::")]
    lic_ids = []
    for c in classifiers:
        tail = c.split("::")[-1].strip()
        if tail and tail.lower() not in ("osi approved",):
            lic_ids.append(tail)
    if lic_ids:
        # Multiple license classifiers conventionally mean dual-licensed (OR).
        return " OR ".join(dict.fromkeys(lic_ids)), \
            f"trove classifiers: {'; '.join(classifiers)}"
    lic = (md.get("License") or "").strip()
    if lic and lic.upper() != "UNKNOWN" and len(lic) < 120 \
            and "\n" not in lic:
        return lic, "core metadata License field"
    return "", ("no License-Expression, no license classifier, License "
                f"field unusable ({lic[:40]!r}…)" if lic else
                "no License-Expression, classifier, or License field")


OWN_PY_PREFIX = "headway-"


def scan_python(repo: Path, allowlist: dict, all_installed: bool,
                pyproject_globs: list[str]) -> EcosystemReport:
    import importlib.metadata as im
    rep = EcosystemReport("python")

    if all_installed:
        rep.notes.append("source: every distribution in the current environment"
                         " (--all-installed)")
        for dist in im.distributions():
            name = (dist.metadata.get("Name") or "").strip()
            if not name or _norm_pkg(name).startswith(OWN_PY_PREFIX):
                continue
            lic, prov = _dist_license(dist)
            dep = Dep("python", name, dist.version, lic, provenance=prov)
            judge(dep, allowlist)
            rep.deps.append(dep)
        rep.deps.sort(key=lambda d: _norm_pkg(d.name))
        return rep

    # Default: pyproject-driven resolution (declared deps + all extras),
    # transitively closed over installed metadata.
    roots: list[tuple[str, frozenset[str], str]] = []
    sources = []
    for pattern in pyproject_globs:
        for pp in sorted(repo.glob(pattern)):
            data = tomllib.loads(pp.read_text(encoding="utf-8"))
            proj = data.get("project", {})
            declared = list(proj.get("dependencies", []))
            for extra, reqs in proj.get("optional-dependencies", {}).items():
                declared.extend(reqs)
            src = str(pp.relative_to(repo))
            sources.append(src)
            for r in declared:
                name, extras, _ = _parse_req(r)
                if name:
                    roots.append((name, extras, src))
    req_txt = repo / "db" / "requirements.txt"
    if req_txt.is_file():
        sources.append("db/requirements.txt")
        for line in req_txt.read_text().splitlines():
            line = line.split("#")[0].strip()
            if line:
                name, extras, _ = _parse_req(line)
                if name:
                    roots.append((name, extras, "db/requirements.txt"))
    rep.notes.append("source: declared dependencies (incl. all extras) of "
                     + ", ".join(sources)
                     + " resolved transitively via importlib.metadata")

    seen: dict[str, set[str]] = {}   # norm name -> extras already expanded
    queue: list[tuple[str, frozenset[str], str, bool]] = [
        (n, e, f"declared in {s}", True) for n, e, s in roots]
    results: dict[str, Dep] = {}
    while queue:
        name, extras, via, is_root = queue.pop(0)
        norm = _norm_pkg(name)
        if norm.startswith(OWN_PY_PREFIX):
            continue
        prev = seen.setdefault(norm, set())
        new_extras = set(extras) - prev
        already = norm in results or (norm in seen and not new_extras and prev)
        prev.update(extras)
        try:
            dist = im.distribution(name)
        except im.PackageNotFoundError:
            if is_root:
                dep = Dep("python", name, "(not installed)", "",
                          provenance=via)
                dep.tier, dep.canonical = TIER_UNKNOWN, "(uninstalled)"
                dep.status = "FAIL"
                dep.reason = (
                    f"declared dependency ({via}) is not installed in this "
                    "environment — its license cannot be verified. Install "
                    "it (pip install -e '<service>[all-extras]') and re-run; "
                    "the gate fails loudly rather than skipping")
                results[norm] = dep
            else:
                rep.notes.append(
                    f"note: conditional/transitive '{name}' ({via}) not "
                    "installed here — not judged (environment-marker dep)")
            continue
        if norm not in results:
            lic, prov = _dist_license(dist)
            dep = Dep("python", dist.metadata["Name"], dist.version, lic,
                      provenance=f"{prov}; first required {via}")
            judge(dep, allowlist)
            results[norm] = dep
        if already and not new_extras:
            continue
        for r in dist.requires or []:
            rname, rextras, rmarker = _parse_req(r)
            if not rname:
                continue
            m_extras = _marker_extras(rmarker)
            if m_extras and not (m_extras & set(extras)):
                continue  # extra not requested
            queue.append((rname, rextras,
                          f"required by {dist.metadata['Name']}", False))
    rep.deps = sorted(results.values(), key=lambda d: _norm_pkg(d.name))
    return rep


# --------------------------------------------------------------------------
# Node ecosystem
# --------------------------------------------------------------------------

def scan_node(repo: Path, allowlist: dict) -> EcosystemReport:
    rep = EcosystemReport("node")
    web = repo / "web"
    if not (web / "package.json").is_file():
        rep.skipped = True
        rep.notes.append("web/package.json does not exist yet — node scan "
                         "skipped (web frontend not landed)")
        return rep
    nm = web / "node_modules"
    if not nm.is_dir():
        rep.hard_error = ("web/package.json exists but web/node_modules is "
                          "missing — run `npm ci` in web/ first; the gate "
                          "fails loudly rather than passing an unscanned tree")
        return rep
    rep.notes.append("source: web/node_modules/*/package.json license fields")
    pkg_dirs = []
    for entry in sorted(nm.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.name.startswith("@"):
            pkg_dirs.extend(sorted(p for p in entry.iterdir() if p.is_dir()))
        elif entry.is_dir():
            pkg_dirs.append(entry)
    for pdir in pkg_dirs:
        pj = pdir / "package.json"
        if not pj.is_file():
            continue
        try:
            meta = json.loads(pj.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
        name = meta.get("name") or str(pdir.relative_to(nm))
        lic = meta.get("license", "")
        prov = "package.json license field"
        if isinstance(lic, dict):
            lic = lic.get("type", "")
            prov = "package.json license object (legacy)"
        if not lic and isinstance(meta.get("licenses"), list):
            lic = " OR ".join(l.get("type", "") for l in meta["licenses"]
                              if isinstance(l, dict))
            prov = "package.json licenses array (legacy)"
        dep = Dep("node", name, meta.get("version", ""), lic, provenance=prov)
        judge(dep, allowlist)
        rep.deps.append(dep)
    return rep


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def print_report(reports: list[EcosystemReport], explain: bool) -> int:
    failures = 0
    total = 0
    for rep in reports:
        print(f"\n=== {rep.name} " + "=" * max(1, 60 - len(rep.name)))
        for note in rep.notes:
            print(f"  [{note}]")
        if rep.skipped:
            print("  SKIPPED")
            continue
        if rep.hard_error:
            print(f"  SCAN FAILURE: {rep.hard_error}")
            failures += 1
            continue
        width = max((len(d.name) for d in rep.deps), default=10)
        for d in rep.deps:
            total += 1
            mark = "ok " if d.status.startswith("PASS") else "XX "
            line = (f"  {mark}{d.name:<{width}}  {d.version:<12.12}  "
                    f"{(d.license or '<none>'):<32.32}  {d.status}")
            print(line)
            if d.status == "FAIL":
                failures += 1
                print(f"       -> {d.reason}")
            if explain:
                print(f"       tier: {d.tier}  canonical: {d.canonical}")
                print(f"       detection: {d.provenance}")
                if d.status != "FAIL":
                    print(f"       verdict: {d.reason}")
        passed = sum(1 for d in rep.deps if d.status.startswith("PASS"))
        allowed = sum(1 for d in rep.deps if d.status == "PASS (allowlisted)")
        failed = sum(1 for d in rep.deps if d.status == "FAIL")
        print(f"  -- {len(rep.deps)} deps: {passed} pass "
              f"({allowed} via reviewed allowlist), {failed} fail")
    print("\n" + "=" * 65)
    if failures:
        print(f"LICENSE GATE: FAIL — {failures} problem(s). "
              "ADR-0001 Amendment 1 tiers enforced: permissive passes; "
              "weak-copyleft needs a reviewed allowlist entry; strong "
              "copyleft, non-OSI, and unknown licenses fail the build.")
        return 1
    print(f"LICENSE GATE: PASS — {total} dependencies conform to "
          "ADR-0001 Amendment 1.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="ADR-0001 dependency license gate (stdlib-only)")
    ap.add_argument("--ecosystem", choices=["all", "go", "python", "node"],
                    default="all")
    ap.add_argument("--repo-root", type=Path,
                    default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--allowlist", type=Path, default=None,
                    help="default: <repo>/scripts/license_allowlist.toml")
    ap.add_argument("--explain", action="store_true",
                    help="show detection provenance and tier for every dep")
    ap.add_argument("--all-installed", action="store_true",
                    help="python: scan every installed distribution instead "
                         "of the pyproject-declared dependency closure")
    ap.add_argument("--requirements-from-pyproject", action="store_true",
                    help="python: resolve services/*/pyproject.toml and "
                         "clients/*/pyproject.toml declared dependencies via "
                         "importlib.metadata (this is the default; flag kept "
                         "for explicit invocation)")
    args = ap.parse_args()

    repo = args.repo_root.resolve()
    allowlist_path = args.allowlist or repo / "scripts" / "license_allowlist.toml"
    allowlist = load_allowlist(allowlist_path)
    print(f"ADR-0001 license gate — repo {repo}")
    print(f"allowlist: {allowlist_path} "
          f"({len(allowlist)} reviewed weak-copyleft entr{'y' if len(allowlist)==1 else 'ies'})")

    reports = []
    if args.ecosystem in ("all", "go"):
        reports.append(scan_go(repo, allowlist))
    if args.ecosystem in ("all", "python"):
        reports.append(scan_python(repo, allowlist, args.all_installed,
                                   ["services/*/pyproject.toml",
                                    "clients/*/pyproject.toml"]))
    if args.ecosystem in ("all", "node"):
        reports.append(scan_node(repo, allowlist))
    return print_report(reports, args.explain)


if __name__ == "__main__":
    sys.exit(main())
