# Is anyone else looking for this? — market evidence, and what it means for the backlog

Researched 2026-08-04. Three parallel sweeps: agency demand signals, the
vendor landscape, and language/localisation obligations. Everything below is
either cited or explicitly marked as inference.

The question behind it: can this become a genuinely vendor-agnostic platform
any US transit agency could adopt, and where should effort go next?

## The short answer

Demand is real but **latent**. No agency is issuing an RFP for a "standalone
NTD platform" — they buy the capability inside BI/data-warehouse contracts or
as consulting labour. But the need is documented in FTA's own paperwork
burden estimate, in a January 2026 RFI that reads like a product spec, and in
a national survey of small agencies.

And the lane is empty. **No open-source system produces or pre-validates an
NTD submission.** Six candidates were checked and eliminated one by one.

## 1. The demand, with numbers

| Finding | Source |
|---|---|
| **456,179 annual burden hours** across 2,914 reporters (~157 hrs each) | FTA PRA estimate, Federal Register 2026-05922 |
| NTD data drives **63% (>$3B/yr)** of Urbanized Area Formula funds | DOT OIG MH-2014-117 |
| **75%** of small agencies rely on spreadsheets; only **22%** use APCs | N-CATT/CUTR-USF, *Data Literacy Among Small Transit Agencies*, Sept 2025 (n=74% under 26 vehicles) |
| **700+ automated validation checks** per submission, plus a human analyst | NTD validation process |
| Average rural fleet **24 vehicles**; most common fleet size **five** | National RTAP Rural & Tribal Survey 2024, n=391 |
| Only **one-third to one-half** of rural agencies use technology for most compliance reporting | ibid. |

**The RFI that reads like a spec.** SouthWest Transit (Eden Prairie, MN)
issued a Data Warehouse & BI RFI on 2026-01-09. Current processes "rely
heavily on manual data collection, spreadsheets, and siloed reports". Goal #1
is to "Automate compliance reporting (FTA, NTD, audits)". It lists **16
systems to integrate** — Infodev, TransitMaster, Swiftly, Spare, Optibus,
Kuba, eMaint, Caselle, Samsara, Gasboy — and stresses in-house ad-hoc
reporting as a hard requirement.

Sixteen systems is the whole thesis: the problem is not any one vendor, it is
that nothing reconciles across them.

## 2. The market structure, and why small agencies are stranded

**Two roll-ups.** Modaxo (Constellation Software) owns Trapeze, TripSpark,
Vontas, TransLoc **and TransTrack** — the leading NTD reporting product.
Transit Technologies LLC owns Ecolane, TripMaster, Passio, busHive, FASTER,
TripShot, Bytecurve, MJM. Independents: Clever Devices, GMV Syncromatics,
Avail, ETA Transit, Swiftly, Optibus, Via/Remix.

That the CAD/AVL vendor and the NTD reporting vendor are often the same
parent company is the lock-in story in one line.

**Verified pricing floors** (Florida DOT TRIPS APTS-21 state contract price
lists, public record, April 2022):

- Avail: $37,500 flat licence + $15,500/yr
- GMV Syncromatics: $20,000 flat + $590/veh/yr
- Optibus: **$12,000/yr or $65/veh/month, whichever is greater**
- Swiftly at Banning Pass Transit (11 buses): $17,200 year 1, $79,830 over 5

**Inference, clearly labelled:** those floors are built for 100+ vehicle
fleets. A five-vehicle agency — the most common size in rural transit — pays
substantially the same entry price as a fifty-vehicle one. The per-vehicle
economics invert exactly where the need is greatest.

Corroborating: when rural agencies are asked what software they use for NTD
reporting, they name Appian (which *is* FTA's own submission portal),
Ecolane, MYLEOnet, Routematch, STTARS, TripMaster — **no dedicated NTD
product appears at all**, and Excel is named across most other compliance
categories.

## 3. The lane is empty — verified, not assumed

| Candidate | Verdict |
|---|---|
| RideSheet | MIT, active — **scheduling only, zero NTD code** |
| RidePilot | Dead since 2019 |
| TransAM | Active — assets/TAM only, ≈15% of a package |
| TNExT | Dormant, **no licence** |
| TIDES | A specification, no reference pipeline; `tides-implementations` essentially empty |
| cal-itp/data-infra | Production quality — but consumes FTA's *published* data |

All 22 GitHub repositories matching "National Transit Database" analyse
published data. FTA provides no software and **no submission API** —
submission is an Appian portal behind Login.gov.

TIDES lists an "NTD Reporting Use Case Profile" as *coming soon*. That is the
gap, named by the standards body itself.

## 4. What they want vs. what we have

Mapped against the backlog as it stands.

| What the evidence says agencies need | Where we are |
|---|---|
| Reconcile across many systems (16, in the RFI) | **Partial.** Dataset registry (PR #32) knows what is declared and what arrived. Cross-source reconciliation is task #35, not built. |
| Defensible validation explanations — "Data is correct" is explicitly rejected by NTD analysts | **Strong.** Every refusal is plain-language with a citation. Built for one operator; turns out to be what submissions are rejected over. |
| Close a critical issue with a *data change*, not a comment | **Requested, not built.** Task #40 (auditor exclusion). NTD requires a data change for critical issues — this is not optional polish. |
| Passenger-miles sampling | **Built.** Sampling plans, draws, measurements, worksheet, estimate. |
| APC benchmarking to ±5%, revalidated every 3 years | **Not built.** The FTA benchmarking checklist is on the roadmap; the balancing tables are a cross-check target (see the Streets landscape doc). |
| Ratio/variance checks (VRM/VRH, OpEx/VRH), 10% significance | **Partial.** VRM/VRH computed; year-over-year variance monitoring is part of #35. |
| Get your own data out of a vendor system | **Strong.** Open contracts only; declarative adapters; the SQL connector reads an agency-supplied view so vendor table names never enter this repo. |
| GTFS — **mandatory** for fixed-route NTD reporters since RY2023 | **Aligned by accident.** ADR-0009 bet on open feeds for reproducibility; it is now a federal requirement. |
| `shapes.txt` — **mandatory for rural/tribal reporters in RY2026** | **GAP WITH A CLOCK.** The map view states plainly we do not ingest `shapes.txt`. This just acquired a deadline. |
| Self-service ad-hoc reporting (stressed in the RFI) | **Weak.** Fixed screens; no ad-hoc query surface. |
| Affordable at five vehicles | **Structurally strong** — self-hosted, no per-vehicle licence — **but** install effort is the real price (task #33). |

## 5. Language packs: the assumption to correct

**Title VI / LEP is a binding grant condition, not a courtesy.** FTA C
4702.1B (effective 2012-10-01, still current) requires a written Language
Assistance Plan — FTA overrides the DOT allowance to skip one. Safe harbour
is 5% or 1,000 persons, whichever is less. Teeth: an expired Title VI Program
means "draw-down privileges suspended and grants may not be processed."

**But the obligation runs to riders, not to staff tools.** Four real RFPs
(RADAR Roanoke 2024-01, Bay Transit, MATA 25-01, Omaha Metro) require Spanish
in the *customer-facing* interface, under headings that literally say "Title
VI Requirements". In all four, the dispatcher/scheduler/back-office sections
contain **zero** language requirements.

So: a Spanish UI for a back-office compliance tool is **not** a Title VI
obligation. Anyone who tells us otherwise is wrong, and building it for that
reason would be building it on a false premise.

**The real reason is better.** Puerto Rico has **64 agencies reporting to the
NTD in RY2024** (4 Full, 36 Reduced, 18 Reduced Asset, 5 Rural, 1 State) —
AMA (Metropolitan Bus Authority, 107 VOMS), ATI/PRITA, PRHTA/Tren Urbano (234
VOMS), and roughly 55 municipios.

PRHTA's own Title VI Program states the split precisely: business with the
public is conducted in Spanish, while "documents produced for or at the
request of federal entities are produced in English". PRITA's plan reports
78.9% of the population speaks English "less than very well" and 5.3% speak
English only; its staff — operators, station managers — "speak mostly
Spanish". ATI's own `/english/home` page renders entirely in Spanish.

**The inversion is the point.** For a Puerto Rico agency, English is the
compliance artefact and Spanish is the working language. A back-office tool
in English-only is not non-compliant — it is simply unusable by the people
who would operate it. That is a market-reach argument, and it is a stronger
one than a compliance argument because it does not depend on a rule that does
not exist.

All four territories report too — Guam GRTA, USVI Vitran, American Samoa,
CNMI COTA — though all are tiny (9–27 VOMS).

**What we could not verify:** whether FTA would accept a Spanish-language NTD
submission (no rule found either way), and any Puerto Rico agency's software
procurement language.

### What it would cost us

The expensive half of an i18n retrofit is already paid: `web/src/copy.ts` is
3,920 lines used by 81 files with **zero hardcoded JSX text**.

The remaining work is specific: ~80 hand-rolled plural conditionals need
converting to a real plural format (Spanish pluralisation and gender do not
follow English rules), and 26 `toLocaleString`/`Intl` sites are currently
locale-implicit.

Tooling note: `i18next + react-i18next` is the ecosystem default (Grafana runs
exactly this). `i18next-parser` was **archived Oct 2025**; the successor is
`i18next-cli`. Weblate Libre is free for public projects; Crowdin and
Transifex free tiers require non-commercial use, which may disqualify them.

Evidence from real repos says the recurring cost is **key drift**, not
translation: Immich deleted 312 lines of dead keys, Grafana has open bugs
where the extractor silently drops strings and exits 0, and Home Assistant
had "over 3000 lines corrupted" when one language landed in another's file.
Whatever we adopt needs a CI check that fails on drift — the same posture as
the existing drift gates.

## 6. Where this points

Ranked by evidence strength, not by appetite:

1. **`shapes.txt` ingestion** — the only item here with a federal deadline
   (RY2026, rural/tribal).
2. **Data exclusion (#40)** — NTD requires a *data change* to close a
   critical issue. Already requested by a real operator.
3. **Cross-source reconciliation (#35)** — the 16-system RFI is the whole
   argument; the dataset registry is the foundation already laid.
4. **A second real vendor adapter** — the architecture is vendor-agnostic by
   design, but exactly one real vendor is proven. A Trapeze or Clever Devices
   agency converts intent into demonstrated fact.
5. **APC benchmarking to ±5%** — named in the NTD process, not built.
6. **Install effort (#33)** — the price for a five-vehicle agency is not
   licence fees, it is the day someone spends installing it.
7. **Spanish language pack** — 64 Puerto Rico reporters, on market-reach
   grounds. Not a compliance requirement; do not sell it as one.

## Honest gaps in this research

- No RFP for a standalone NTD platform exists anywhere — positioning must
  enter an existing procurement category.
- No published count of rejected NTD submissions or agencies failing
  validation.
- Documented vendor lock-in comes from industry bodies (N-CATT, National
  RTAP) and vendor blogs, **not** first-person agency complaints. That
  evidence may exist in board minutes; it was not found.
- Prices for TransTrack, TripSpark, Trapeze, Passio, ETA Transit and
  Routematch are not public.
- NTD does *not* appear in FTA's FY2023 triennial review top-10 deficiencies.
  Consistent with OIG's finding that triennial reviews do not assess data
  accuracy — NTD accuracy is policed by validation and close-out alone.
