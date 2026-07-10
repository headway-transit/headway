# Reference documents

Authoritative regulatory source documents that Headway's calculations are verified against. These are **the exact files cited by `services/calc/REGULATORY_TRACKER.md`** — keeping them in-repo preserves the provenance of every verification claim (a tracker citation must point at bytes a reviewer can open).

| File | What it is | Verification use |
| --- | --- | --- |
| `2025 NTD Full Reporting Policy Manual.pdf` | FTA National Transit Database Policy Manual, 2025 reporting year (Full Reporting) | Cross-check source for VRM/VRH/deadhead/layover definitions (verified textually identical to 2026 on 2026-07-10) |
| `National Transit Database 2026 Policy Manual_ Full Reporting.pdf` | FTA NTD Policy Manual, 2026 reporting year (Full Reporting) | Primary verification source: definitions quoted in the regulatory tracker from manual pp. 128–136 (Service Data Requirements, Exhibits 35–37) |

These manuals are works of the United States Government (Federal Transit Administration) and are in the public domain (17 U.S.C. § 105); their inclusion here does not affect the repository's Apache-2.0 licensing of Headway code. Obtain current editions from transit.dot.gov — new reporting years supersede these files, and the tracker's rule stands: re-verify against the current published manual before implementing any rule that depends on it.
