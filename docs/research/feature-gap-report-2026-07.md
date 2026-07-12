# Feature-Gap Report — What the Transit-Data World Discusses That Headway May Have Missed

**Date:** 2026-07-11
**Status:** Research draft — web-sourced; every claim cites its URL. Community sentiment is only asserted where a source says it; nothing is inferred. PENDING human review.
**Compared against:** `README.md`, `docs/adr/` (0001–0011), `docs/connecting-your-data.md`, `services/calc/REGULATORY_TRACKER.md` (VRM/VRH/UPT/VOMS, MR-20 preview, divergences D1–D6), `.claude/roles/INGESTION_ENGINEER.md` (planned sources: CAD/AVL, APC, farebox/AFC, J1939, EV charging, paratransit/DRT, maintenance).

Gap labels: **HAVE** (shipped), **PARTIAL** (some of it shipped or explicitly planned with a concrete surface), **MISSING** (openly discussed in the field, absent from both shipped code and the tracker/charter), **OUT-OF-SCOPE** (real, but outside Headway's stated mission).

---

## Method

Research run 2026-07-08 → 2026-07-11 via web search and direct source fetches. 21 search queries across four angles, plus 4 primary-source fetches (Federal Register final notice via govinfo.gov mirror; TIDES-transit/TIDES open issues).

Queries run (verbatim):

1. `NTD reporting burden data quality problems transit agencies GAO FTA oversight report`
2. `National Transit Database reporting pain points small transit agencies state DOT guidance`
3. `TRB paper APC data validation NTD reporting challenges automatic passenger counters`
4. `FTA triennial review common findings NTD data deficiencies`
5. `Cal-ITP California Integrated Travel Project data infrastructure GTFS quality warehouse tools`
6. `TIDES-transit GitHub issues discussions data specification adoption transit agencies`
7. `TransAM open source transit asset management TAM plan software agencies`
8. `MobilityData GTFS validator canonical projects transit data tools 2025 2026`
9. `Swiftly transit platform features on-time performance run-times speed maps NTD reporting`
10. `Hopthru ridership analytics APC data cleaning NTD reporting transit agencies features`
11. `Clever Devices Trapeze TripSpark CAD/AVL NTD reporting features transit ITS platform`
12. `Optibus transit scheduling platform features rostering runcutting electric vehicle planning`
13. `GTFS-Flex adoption demand response transit feeds 2025 FTA GTFS requirement NTD`
14. `GTFS-Fares v2 adoption transit agencies 2025 fare data standard`
15. `NTD reporting changes report year 2025 2026 final notice GTFS requirement safety security forms`
16. `Operational Data Standard ODS transit scheduling deadhead blocks California open data mandate SB 922 transit`
17. `Passenger Miles Traveled PMT NTD reporting APC estimation requirement transit`
18. `TheTransitClock OpenTripPlanner ecosystem open source AVL prediction GTFS-realtime archive tools`
19. `TransTrack NTD reporting software features transit performance data management`
20. `"NTD" final notice July 2025 "agency_id" GTFS "shapes.txt" cybersecurity event reporting summary RY 2025 RY 2026 changes`
21. `Ito World transit data platform features real-time feed quality GTFS services`

Limits: US-centric search index; vendor feature claims taken from public marketing pages only (feature *names*, not verified behavior); TRB papers seen via abstracts/aggregators, not full texts.

---

## Findings by theme

### Theme 1 — NTD reporting pain points agencies and overseers discuss publicly

**1.1 Federal oversight has long flagged NTD data completeness/accuracy as the core risk.**
The DOT Office of Inspector General audited FTA's NTD oversight, examining whether Urbanized Area Formula grant recipients "submit complete, accurate, and timely data," and framed NTD modernization as a chance to gain "greater assurance that the NTD appropriately distributes Federal grant funds" ([OIG audit report, oig.dot.gov](https://www.oig.dot.gov/sites/default/files/NTD%20Final%20Report.pdf)).
**Gap: HAVE.** Provable accuracy is Headway's founding thesis (provenance, refuse-to-report-over-gaps, certification cockpit). This theme validates the product, it doesn't extend it.

**1.2 Reporting burden dominates agency comments — especially for small agencies.**
FTA's own final notice records commenter concerns about "increased administrative burden, complexity, and confusion" ([Federal Register 2025-12813](https://www.federalregister.gov/documents/2025/07/10/2025-12813/national-transit-database-reporting-changes-and-clarifications-for-report-years-2025-and-2026)); N-CATT describes a "digital divide between large and small agencies" in data staffing and says small providers "dread" typical reporting ([N-CATT](https://n-catt.org/news/its-time-for-small-transit-providers-to-have-access-to-critical-data-insights/)); commenters called GTFS geospatial requirements "unduly burdensome, especially for small or rural reporters" ([Federal Register proposed notice 2024-25341](https://www.federalregister.gov/documents/2024/10/31/2024-25341/national-transit-database-proposed-reporting-changes-and-clarifications-for-report-years-2025-and)).
**Gap: PARTIAL.** The one-box commodity deployment targets exactly this audience, but Headway's calc/report surface is Full-Reporter-shaped (MR-20, Full Reporting Policy Manual citations). Reduced/rural/tribal reporter workflows (simpler forms, different manuals) are absent from the tracker.

**1.3 Triennial-review findings: NTD submissions inconsistent with agency records, especially maintenance.**
FTA publishes top triennial-review deficiencies ([FTA FY2023 Top 10 Deficiencies](https://www.transit.dot.gov/regulations-and-programs/safety/fiscal-year-2023-triennial-reviews-top-10-deficiencies); [FTA 2022 APTA presentation](https://www.transit.dot.gov/sites/fta.dot.gov/files/2022-10/2022-APTA-TRANSform-FTA-Top-Triennial-Review-Findings-October-9-2022.pdf); [AZTA deficiencies deck](https://www.azta.org/images/uploads/event-files/FTA_Program_Compliance_Updates_.pdf)). Industry guidance highlights "inconsistent NTD data vs. actual records" for maintenance — preventive-maintenance records, defect tracking, TERM-scale condition assessments ([buscmms.com guide](https://buscmms.com/blog/transit-agency-bus-maintenance-fta-compliance-guide); [Trapeze on triennial prep](https://www.trapezegroup.com/blog-entry/7-steps-to-a-successful-fta-triennial-review-for-maintenance)).
**Gap: MISSING.** Maintenance ingestion is chartered (INGESTION_ENGINEER.md) but no maintenance/asset *reporting* target exists anywhere in the tracker. Headway's whole pitch is "survive the triennial review," yet it addresses only the service-data slice of what reviews actually find.

**1.4 APC validation/sampling is a decades-deep, still-live research literature.**
TRB/academic work documents that APCs "undercount boardings and overcount alightings," need correction factors, and that the hard problems are validation, sampling design, and "inferring system-level ridership from sample data in the presence of selective APC failures" ([TriMet rail APC validation paper](https://www.researchgate.net/publication/325307724_Validation_and_Sampling_of_Automatic_Rail_Passenger_Counters_for_National_Transit_Database_and_Internal_Reporting_at_TriMet); [APC evaluation for NTD](https://www.researchgate.net/publication/237219562_Automatic_Passenger_Counter_Evaluation_Implications_for_National_Transit_Database_Reporting); [FTA APC guidebook](https://rosap.ntl.bts.gov/view/dot/6456); [Oregon DOT APC/AFC white paper](https://www.oregon.gov/odot/RPTD/RPTD%20Document%20Library/APC-AFC-White-Paper-Trillium-2021.pdf)).
**Gap: PARTIAL.** upt_v0 implements the manual's p. 146/151 validations (imbalance, negative load, missing-trip factor-up). What's absent: correction-factor estimation, sampling-plan design/execution, and the FTA APC certification/benchmarking workflow (±5% ride-check, discard-rate) that the tracker itself defers as "an agency workflow outside calc logic."

### Theme 2 — Emerging FTA requirements (rulemaking)

**2.1 RY2025/26 final notice (July 10, 2025) makes the GTFS feed itself a reportable, certified artifact.**
Finalized: `agency_id` must align to the agency's NTD ID and becomes non-conditionally required in `routes.txt`/`fare_attributes.txt`; `shapes.txt` becomes mandatory (RY2025 full reporters, RY2026 reduced/rural/tribal); FTA notes CEO D-10 certification covers submitted GTFS files ([govinfo.gov full text](https://www.govinfo.gov/content/pkg/FR-2025-07-10/html/2025-12813.htm); [Federal Register 2025-12813](https://www.federalregister.gov/documents/2025/07/10/2025-12813/national-transit-database-reporting-changes-and-clarifications-for-report-years-2025-and-2026)). Commenters said the GTFS changes "require software or vendor changes" and may force "separate GTFS file[s]" ([govinfo.gov](https://www.govinfo.gov/content/pkg/FR-2025-07-10/html/2025-12813.htm)).
**Gap: MISSING.** Headway ingests GTFS but never *evaluates* it. There is no check that a feed satisfies the NTD GTFS mandate (NTD-ID-aligned agency_id, shapes.txt present/valid) and no GTFS validation at all — while the feed is now something the CEO certifies. This is squarely inside Headway's "informed consent, mechanized" thesis.

**2.2 Safety & Security reporting, including new cybersecurity events.**
The same notice finalizes cyber-security event reporting clarifications and a disabling-damage threshold for rail collisions (CY2025); commenters called cyber reporting "duplicative and burdensome" alongside TSA/CISA obligations ([govinfo.gov](https://www.govinfo.gov/content/pkg/FR-2025-07-10/html/2025-12813.htm)). The S&S reporting family has its own policy manual ([2025 NTD Safety and Security Policy Manual](https://www.transit.dot.gov/ntd/2025-ntd-safety-and-security-reporting-policy-manual)) and its own prior rulemaking ([Federal Register 2023-03789](https://www.federalregister.gov/documents/2023/02/23/2023-03789/national-transit-database-safety-and-security-reporting-changes-and-clarifications)).
**Gap: MISSING.** No S&S form, event model, or ingestion source (incidents/road calls feed both S&S and maintenance) appears anywhere in Headway's tracker or charter. It is an entire monthly NTD reporting module agencies must file.

**2.3 Asset reporting realignment (A-20 ↔ TERM, A-10/A-15 consolidation).**
Finalized for RY2025: A-20 alignment with the Transit Economic Requirements Model and consolidation of passenger-station/maintenance-facility forms ([govinfo.gov](https://www.govinfo.gov/content/pkg/FR-2025-07-10/html/2025-12813.htm)). The TAM rule (2016) already obligates every FTA-funded provider to a TAM plan ([FTA TAM](https://www.transit.dot.gov/TAM)).
**Gap: MISSING.** See 1.3 — no asset inventory model or A-form target in Headway.

**2.4 Rulemaking moves fast in both directions — WE-20 is already proposed for rescission.**
FTA proposes rescinding the weekly WE-20 requirement because it "no longer offers sufficient value relative to the administrative burden" ([Federal Register 2025-20086](https://www.federalregister.gov/documents/2025/11/18/2025-20086/proposed-rescission-of-the-national-transit-database-weekly-reference-reporting-requirement)).
**Gap: PARTIAL.** REGULATORY_TRACKER.md documents WE-20 (p. 34) as a "bonus" target. Implication: don't build WE-20; more generally, Headway has no process artifact for *watching Federal Register NTD dockets* — the tracker records manuals verified, not rulemaking in flight. A lightweight "regulatory watch" section/feed would fit the tracker's philosophy.

**2.5 GTFS-Flex and GTFS-Fares v2 are now mainline GTFS.**
Flex was adopted into GTFS in March 2024 and is produced "for well over a hundred" US agencies, with state-scale production by Cal-ITP and MnDOT ([gtfs.org Flex](https://gtfs.org/community/extensions/flex/); [N-CATT Flex guidebook](https://n-catt.org/guidebooks/updated-gtfs-flex/); [Optibus blog](https://blog.optibus.com/gtfs-flex-officially-adopted-into-gtfs)). Fares v2 gained Rider Categories (adopted Feb 13, 2025) and has 30+ Bay Area agencies live via MTC/Interline ([gtfs.org Fares v2](https://gtfs.org/community/extensions/fares-v2/); [Interline](https://www.interline.io/blog/mtc-regional-gtfs-feed-fares-updates/)). Note: FTA's NTD GTFS mandate today covers only fixed-route static GTFS; demand-response is excluded ([FTA NTD developments FAQ](https://www.transit.dot.gov/ntd/recent-ntd-developments-frequently-asked-questions-0)).
**Gap:** Flex — **MISSING** (and it is the schedule backbone for the DR mode Headway defers as D5); Fares v2 — **OUT-OF-SCOPE** for NTD figures today, but relevant context for the planned farebox/AFC connector's fare-policy joins.

### Theme 3 — Open-source transit tooling landscape

**3.1 Cal-ITP runs statewide GTFS quality reporting on the MobilityData canonical validator.**
Cal-ITP publishes monthly per-agency GTFS quality reports for every California provider using its own deployment of MobilityData's open-source canonical validator ([reports.calitp.org](https://reports.calitp.org/); [Caltrans GTFS data quality](https://dot.ca.gov/programs/rail/gtfs-guidelines/gtfs-data-quality); [cal-itp/reports on GitHub](https://github.com/cal-itp/reports); [gtfs-validator](https://github.com/MobilityData/gtfs-validator)), backed by the California Transit Data Guidelines ([Caltrans guidelines](https://dot.ca.gov/cal-itp/california-transit-data-guidelines)).
**Gap: MISSING.** A state DOT already operationalized what Headway lacks: continuous GTFS feed validation with published quality reports. Embedding the canonical validator (Apache-2.0, fits Guardrail 3) at ingest would give Headway feed-quality DQ issues natively and directly serves finding 2.1.

**3.2 TIDES is heading to v2.0, and its open issues map onto Headway's own divergences.**
Open issues in TIDES-transit/TIDES ([issues list](https://github.com/TIDES-transit/TIDES/issues), fetched 2026-07-11): **#269 vehicle attributes and consists** (train-car composition — exactly the consist data Headway's D2 rail divergence needs), #271 v2.0 release checklist, #244 aggregated ridership table, #242 device_status (APC device health — relevant to discard-rate tracking), #241 fare-gate/station passenger events, #252 GTFS-RT `schedule_relationship` incompatibility, #240 vehicle_label, #270 departure_load aggregation bias, #236 `event_count` usage clarification. TIDES explicitly names NTD reporting as a use case ([TIDES repo](https://github.com/TIDES-transit/TIDES)).
**Gap: PARTIAL.** Headway is TIDES-aligned (ADR-0003) and pins spec commits, but only consumes `passenger_events`. Not consuming `vehicle_locations`/`stop_visits`/`trips_performed`, not tracking v2.0, and — most concretely — not participating in/watching #269, whose consists table is the published closure path for D2.

**3.3 TransAM: open-source transit asset management already exists.**
TransAM (Cambridge Systematics, born from Virginia DRPT + PennDOT) is open-source, "aggregat[es] asset data to produce pre-formatted FTA NTD reports," and handles grants/capital planning ([camsys TransAM](https://camsys.software/platforms/transam); [AASHTO TAM portal](https://www.transportationmanagement.us/blog/document/trans-am-customizable-open-source-software-for-transit-asset-management/)).
**Gap: MISSING** (asset domain), but the existence of an open-source incumbent argues for *integration/import* (TransAM as a source feeding Headway's A-forms provenance) before building asset management from scratch.

**3.4 Cal-ITP's Operational Data Standard (ODS/TODS) covers exactly Headway's deadhead blind spot.**
ODS extends GTFS to "personnel, scheduled maintenance, and non-revenue service"; "information about moving vehicles without passengers aboard (also known as deadheading), runs, and daily pull-ins and pull-outs... is not captured in rider-facing GTFS" ([Cal-ITP announcement](https://www.calitp.org/press/cal-itp-announces-ods); [tods.mobilitydata.org](https://tods.mobilitydata.org/); [spec examples](https://ods.calitp.org/spec/examples/)). Built by a working group of 40+ agencies and CAD/AVL/scheduling vendors; Swiftly is already a consumer with SF Bay Ferry ([Swiftly/WETA](https://www.goswift.ly/blog/first-consumer-operational-data-standard)).
**Gap: MISSING.** Headway's D3 (revenue-service proxy via trip assignment) and D6 (excluded activities) are documented residual risks precisely because Headway has no source that states *scheduled* deadhead/pull-out truth. A TODS connector is a standards-based closure path and fits the existing connector contract.

**3.5 OTP / TheTransitClock ecosystem.**
OpenTripPlanner (trip planning) and TheTransitClock (Kalman-filter arrival predictions from GTFS-RT) are the active open-source realtime consumers ([OTP](https://github.com/opentripplanner/OpenTripPlanner); [TheTransitClock](https://thetransitclock.github.io/); [awesome-transit](https://github.com/MobilityData/awesome-transit)).
**Gap: OUT-OF-SCOPE.** Rider-facing prediction/planning is not Headway's mission. One PARTIAL note: the community's GTFS-RT *archival* tooling need ([gtfs.org producing-data](https://gtfs.org/resources/producing-data/)) is something Headway's immutable raw store already does well — a possible adoption wedge, not a gap.

### Theme 4 — Commercial platforms' publicly-marketed features (names only, for gap mapping)

**4.1 Swiftly (160+ agencies): "on-time performance," "headway adherence," "run-times," "speed map," "dwell times."**
Marketed as improving OTP "by up to 40%," analyzing "actual versus scheduled run-times for every segment," and mapping "route segments and intersections that cause avoidable slowdowns" ([goswift.ly platform](https://www.goswift.ly/platform); [performance insights](https://www.goswift.ly/performance-insights); [planning](https://www.goswift.ly/solution-planning)).
**Gap: MISSING** (deliberately, so far). Headway ingests the same vehicle positions + (unused) trip updates but computes only NTD figures. OTP/run-time analytics is the single most-marketed use of the data Headway already holds; it's also what makes a platform daily-useful between reporting deadlines.

**4.2 Hopthru (acquired by Swiftly, Aug 2024): "Cleanse" + "Analyze" — APC cleaning certified for NTD.**
"Hopthru Cleanse processes raw APC data, combining it with GTFS... to produce information certifiable for NTD reporting"; builds "a statistician-certified, expanded data set that alleviates the common pains of accessing and certifying ridership data"; acquisition explicitly adds "NTD reporting" to Swiftly ([PR Newswire](https://www.prnewswire.com/news-releases/swiftly-acquires-hopthru-to-add-ridership-analysis-and-ntd-reporting-to-its-transit-data-platform-302231440.html); [goswift.ly Hopthru Ridership](https://www.goswift.ly/hopthru-ridership)).
**Gap: PARTIAL.** Headway's upt_v0 has honest validation + factor-up, but the commercially-proven package is cleaning **+ statistical expansion + certification support** as a workflow. The "statistician-certified expanded data set" is precisely the >2%-missing path where Headway currently (correctly) refuses and stops.

**4.3 TransTrack: "95% of annual NTD reporting in one click," "271 standard reports," financial + roadcalls + safety consolidation.**
Markets out-of-the-box NTD annual reporting, consolidation of "financial accounts, roadcalls, and safety/security events" under NTD methodologies, and APC certification guidance ([TransTrack NTD](https://www.transtracksystems.net/ntd); [out-of-the-box blog](https://www.transtracksystems.net/blog/out-of-the-box-ntd-reporting-with-transtrack); [TransTrack Manager](https://www.transtracksystems.net/transtrack-manager); [APC certification steps](https://www.transtracksystems.net/blog/six-step-to-certifying-apcs-for-ntd-reporting)).
**Gap: MISSING (breadth).** The incumbent NTD-specific product's pitch is *form coverage across the whole report year* — financial (F-forms), safety, roadcalls, assets — while Headway covers 4 service-data points on one monthly form. Headway's depth (provenance) is unmatched in TransTrack's marketing; its breadth is not yet comparable.

**4.4 Clever Devices / Trapeze / TripSpark: CAD/AVL with "reporting tools that support NTD funding requirements."**
CAD/AVL suites market NTD-supporting reporting off dispatch/AVL/APC data ([TripSpark CAD/AVL](https://www.tripspark.com/fixed-route-software/cad-avl/); [CleverCAD](https://www.cleverdevices.com/products/clevercad/); Trapeze pairs with TransTrack for analytics ([TransTrack/Trapeze integration](https://www.transtracksystems.net/blog/transtrack-and-trapeze-data-analytics-integrate-to-unlock-the-full-potential-of-your-transit-data))).
**Gap: PARTIAL.** Confirms the CAD/AVL connector priority already in the ingestion charter; no new feature class beyond findings above.

**4.5 Optibus: "planning," "scheduling," "rostering," "runcutting," "EV planning" (battery range, charging, depots).**
Cloud-native planning/scheduling/rostering with EV-specific optimization ([optibus.com product](https://optibus.com/product/); [scheduling](https://optibus.com/product/scheduling/); [planning](https://optibus.com/product/planning/)).
**Gap: OUT-OF-SCOPE.** Schedule *optimization* is a different product. Relevant edge: Optibus consumes/produces the schedule artifacts (blocks, runs) that TODS standardizes — reinforcing 3.4.

**4.6 Ito World: "Notify," "Elevate" — feed aggregation/quality for journey planners; "automatically quarantining bad schedules."**
UK-centric (BODS) real-time data quality and aggregation for Google Maps et al. ([itoworld.com](https://www.itoworld.com/); [data quality](https://www.itoworld.com/inside-ito/why-ito/data-quality/); [Notify](https://www.itoworld.com/solutions/notify/)).
**Gap: OUT-OF-SCOPE** for NTD, but "quarantining bad schedules before they impact operations" is the same pattern as Headway's malformed-record quarantine — no new gap beyond GTFS validation (2.1/3.1).

---

## Top-10 missed-feature candidates ranked by agency impact

1. **Passenger Miles Traveled (PMT) + NTD Sampling Manual support.** PMT is a required annual figure alongside UPT for Full Reporters, with a defined sampling path (95% confidence / ±10%) when 100% counts aren't reliable ([FTA NTD Sampling Manual](https://www.transit.dot.gov/ntd/ntd-sampling-manual)). Headway computes UPT but has no PMT calc at all — the single largest missing *number* in a platform whose product is NTD numbers.
2. **APC certification & benchmarking workflow.** FTA requires APC approval via ride-check benchmarking within 5% variance and discard-rate tracking ([FTA APC guidebook](https://rosap.ntl.bts.gov/view/dot/6456); Headway's own tracker cites Manual pp. 147–148 and defers it). Hopthru built a company on exactly this ([PR Newswire](https://www.prnewswire.com/news-releases/swiftly-acquires-hopthru-to-add-ridership-analysis-and-ntd-reporting-to-its-transit-data-platform-302231440.html)). Headway is uniquely positioned: a provenance-native benchmarking workbook (manual counts vs APC, variance, discard rate, statistician sign-off) is certification-cockpit territory.
3. **Safety & Security (S&S) reporting module — including the new cybersecurity event reporting.** A whole monthly NTD reporting family with fresh CY2025 requirements agencies call burdensome ([govinfo.gov final notice](https://www.govinfo.gov/content/pkg/FR-2025-07-10/html/2025-12813.htm); [2025 S&S Policy Manual](https://www.transit.dot.gov/ntd/2025-ntd-safety-and-security-reporting-policy-manual)) — absent from Headway's roadmap entirely.
4. **GTFS feed NTD-compliance validation (embed the MobilityData canonical validator).** The RY2025/26 mandate makes the GTFS feed a CEO-certified NTD artifact (agency_id = NTD ID, shapes.txt) ([govinfo.gov](https://www.govinfo.gov/content/pkg/FR-2025-07-10/html/2025-12813.htm)); Cal-ITP proves the validator-report pattern at state scale ([reports.calitp.org](https://reports.calitp.org/)). Headway ingests feeds it never checks.
5. **Operational Data Standard (TODS) connector.** Open, Cal-ITP-backed standard carrying deadhead/pull-out/run/block truth ([tods.mobilitydata.org](https://tods.mobilitydata.org/); [Cal-ITP](https://www.calitp.org/press/cal-itp-announces-ods)) — the standards-based path to shrinking Headway's documented D3/D6 revenue-service-proxy risk and hardening VRH.
6. **Asset inventory / TAM reporting (A-forms, TERM alignment) — via TransAM interop first.** Asset/maintenance record inconsistency is a recurring triennial finding ([FTA FY2023 top deficiencies](https://www.transit.dot.gov/regulations-and-programs/safety/fiscal-year-2023-triennial-reviews-top-10-deficiencies)), RY2025 realigns A-20 to TERM ([govinfo.gov](https://www.govinfo.gov/content/pkg/FR-2025-07-10/html/2025-12813.htm)), and open-source TransAM already emits "pre-formatted FTA NTD reports" ([camsys](https://camsys.software/platforms/transam)).
7. **Annual-report breadth: financial (F-forms) and the rest of the report year.** The incumbent's headline is "95% of annual NTD reporting in one click" spanning financial accounts, roadcalls, safety ([TransTrack](https://www.transtracksystems.net/blog/out-of-the-box-ntd-reporting-with-transtrack)). Headway's 4 MR-20 fields are the right wedge, but agencies buy form coverage; a receipted S-10/F-form path is the growth axis.
8. **Service performance analytics from data already held (OTP, run-times, headway adherence).** Swiftly's entire marketed core ([goswift.ly](https://www.goswift.ly/platform)) runs on inputs Headway already stores — including trip updates Headway captures but doesn't use (`docs/connecting-your-data.md` §1). This is what keeps the platform open on an ops manager's screen between filings.
9. **TIDES v2.0 tracking + the consists table (issue #269).** Headway's D2 (rail passenger-car measure) is blocked on consist data; the TIDES community is actively designing that table now ([TIDES #269 via issues list](https://github.com/TIDES-transit/TIDES/issues)). Watching — better, contributing to — v2.0 (#271) is the cheapest D2 progress available, and Headway consumes only 1 of TIDES' tables today.
10. **Demand-response support: GTFS-Flex ingestion + the DR revenue-time calc (close D5).** Flex is mainline GTFS with 100+ US producers and state-scale programs ([gtfs.org Flex](https://gtfs.org/community/extensions/flex/); [N-CATT](https://n-catt.org/guidebooks/updated-gtfs-flex/)); DR is the dominant mode at the small/rural agencies Headway's one-box design courts, and paratransit ingestion is already chartered with no calc to land in.

*Ranking rationale:* 1–3 are things agencies are federally required to do and currently pay vendors or consultants for; 4–6 are new-mandate/standards plays where Headway's provenance model is a differentiator; 7–10 are breadth/adoption plays. Deliberately excluded from the Top-10: schedule optimization and rider-facing prediction (Optibus/OTP territory — OUT-OF-SCOPE per README mission), Fares v2 production (no NTD pull yet).

---

## Non-findings (searched, not found discussed)

- **No public discussion found of any open-source competitor doing regulation-cited, deterministic NTD calculation** with lineage to raw records. Searches across Cal-ITP, TIDES, MobilityData, awesome-transit surfaced validators, warehouses, and spec work — not receipted NTD figure computation. Headway's core differentiator appears unclaimed (absence of evidence in ~21 queries, not proof).
- **No specific state statute mandating transit open data surfaced** in the ODS/"SB 922" query; California's lever appears to be the (non-statutory) Transit Data Guidelines tied to Caltrans programs ([Caltrans guidelines](https://dot.ca.gov/cal-itp/california-transit-data-guidelines)). Not established either way.
- **No public agency complaints found about NTD certification/signing UX** (the D-10 consent problem Headway's cockpit solves) — the burden discourse is about data collection, not signature workflows.
- **No NTD-relevant features found for Ito World** — its public material is UK/BODS and journey-planner feed quality ([itoworld.com](https://www.itoworld.com/)).
- **TIDES issue tracker shows no open issue on NTD-specific calculation or reporting outputs** — v2.0 issues are schema/clarity items ([issues list](https://github.com/TIDES-transit/TIDES/issues), fetched 2026-07-11).

---

## Sources

Federal / oversight:
- https://www.oig.dot.gov/sites/default/files/NTD%20Final%20Report.pdf — DOT OIG audit, FTA NTD data quality oversight
- https://www.federalregister.gov/documents/2025/07/10/2025-12813/national-transit-database-reporting-changes-and-clarifications-for-report-years-2025-and-2026 — RY2025/26 final notice
- https://www.govinfo.gov/content/pkg/FR-2025-07-10/html/2025-12813.htm — same notice, full text (fetched)
- https://www.federalregister.gov/documents/2024/10/31/2024-25341/national-transit-database-proposed-reporting-changes-and-clarifications-for-report-years-2025-and — RY2025/26 proposed notice (burden comments)
- https://www.federalregister.gov/documents/2025/11/18/2025-20086/proposed-rescission-of-the-national-transit-database-weekly-reference-reporting-requirement — WE-20 rescission proposal
- https://www.federalregister.gov/documents/2023/02/23/2023-03789/national-transit-database-safety-and-security-reporting-changes-and-clarifications — S&S reporting changes (2023)
- https://www.transit.dot.gov/ntd/2025-ntd-safety-and-security-reporting-policy-manual — 2025 S&S Policy Manual
- https://www.transit.dot.gov/ntd/ntd-sampling-manual — NTD Sampling Manual (PMT/UPT estimation)
- https://www.transit.dot.gov/ntd/recent-ntd-developments-frequently-asked-questions-0 — GTFS mandate scope FAQ
- https://www.transit.dot.gov/regulations-and-programs/safety/fiscal-year-2023-triennial-reviews-top-10-deficiencies — FY2023 triennial top deficiencies
- https://www.transit.dot.gov/sites/fta.dot.gov/files/2022-10/2022-APTA-TRANSform-FTA-Top-Triennial-Review-Findings-October-9-2022.pdf — FTA top findings deck
- https://www.azta.org/images/uploads/event-files/FTA_Program_Compliance_Updates_.pdf — triennial common deficiencies deck
- https://www.transit.dot.gov/TAM — FTA Transit Asset Management rule

Research / guidance:
- https://rosap.ntl.bts.gov/view/dot/6456 — FTA guidebook: using APC data for NTD
- https://www.researchgate.net/publication/325307724_Validation_and_Sampling_of_Automatic_Rail_Passenger_Counters_for_National_Transit_Database_and_Internal_Reporting_at_TriMet — TriMet APC validation (TRR)
- https://www.researchgate.net/publication/237219562_Automatic_Passenger_Counter_Evaluation_Implications_for_National_Transit_Database_Reporting — APC evaluation for NTD (TRR)
- https://www.oregon.gov/odot/RPTD/RPTD%20Document%20Library/APC-AFC-White-Paper-Trillium-2021.pdf — Oregon DOT APC/AFC white paper
- https://n-catt.org/news/its-time-for-small-transit-providers-to-have-access-to-critical-data-insights/ — N-CATT on small-agency data divide
- https://n-catt.org/guidebooks/updated-gtfs-flex/ — N-CATT GTFS-Flex guidebook

Open-source ecosystem:
- https://reports.calitp.org/ — Cal-ITP monthly GTFS quality reports
- https://github.com/cal-itp/reports — Cal-ITP reports source
- https://dot.ca.gov/programs/rail/gtfs-guidelines/gtfs-data-quality — Caltrans GTFS data quality
- https://dot.ca.gov/cal-itp/california-transit-data-guidelines — California Transit Data Guidelines
- https://github.com/MobilityData/gtfs-validator — canonical GTFS validator
- https://github.com/TIDES-transit/TIDES — TIDES spec
- https://github.com/TIDES-transit/TIDES/issues — TIDES open issues incl. #269 consists, #271 v2.0 (fetched 2026-07-11)
- https://camsys.software/platforms/transam — TransAM
- https://www.transportationmanagement.us/blog/document/trans-am-customizable-open-source-software-for-transit-asset-management/ — TransAM background
- https://tods.mobilitydata.org/ — Transit Operational Data Standard
- https://www.calitp.org/press/cal-itp-announces-ods — ODS announcement (deadhead/runs/pull-outs)
- https://ods.calitp.org/spec/examples/ — ODS examples
- https://github.com/opentripplanner/OpenTripPlanner — OTP
- https://thetransitclock.github.io/ — TheTransitClock
- https://github.com/MobilityData/awesome-transit — community tool list
- https://gtfs.org/community/extensions/flex/ — GTFS-Flex
- https://gtfs.org/community/extensions/fares-v2/ — GTFS-Fares v2
- https://www.interline.io/blog/mtc-regional-gtfs-feed-fares-updates/ — Bay Area Fares v2 rollout
- https://gtfs.org/resources/producing-data/ — GTFS-RT archival tooling context

Commercial (public marketing pages only):
- https://www.goswift.ly/platform , https://www.goswift.ly/performance-insights , https://www.goswift.ly/solution-planning — Swiftly features
- https://www.goswift.ly/blog/first-consumer-operational-data-standard — Swiftly as first ODS consumer
- https://www.prnewswire.com/news-releases/swiftly-acquires-hopthru-to-add-ridership-analysis-and-ntd-reporting-to-its-transit-data-platform-302231440.html — Swiftly/Hopthru acquisition
- https://www.goswift.ly/hopthru-ridership — Hopthru Cleanse/Analyze
- https://www.transtracksystems.net/ntd , https://www.transtracksystems.net/blog/out-of-the-box-ntd-reporting-with-transtrack , https://www.transtracksystems.net/transtrack-manager , https://www.transtracksystems.net/blog/six-step-to-certifying-apcs-for-ntd-reporting — TransTrack features
- https://www.tripspark.com/fixed-route-software/cad-avl/ — TripSpark CAD/AVL
- https://www.cleverdevices.com/products/clevercad/ — CleverCAD
- https://www.transtracksystems.net/blog/transtrack-and-trapeze-data-analytics-integrate-to-unlock-the-full-potential-of-your-transit-data — Trapeze/TransTrack
- https://optibus.com/product/ , https://optibus.com/product/scheduling/ , https://optibus.com/product/planning/ — Optibus features
- https://www.itoworld.com/ , https://www.itoworld.com/inside-ito/why-ito/data-quality/ , https://www.itoworld.com/solutions/notify/ — Ito World features
- https://buscmms.com/blog/transit-agency-bus-maintenance-fta-compliance-guide — maintenance/NTD compliance guide
- https://www.trapezegroup.com/blog-entry/7-steps-to-a-successful-fta-triennial-review-for-maintenance — Trapeze triennial prep
