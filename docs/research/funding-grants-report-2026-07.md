# Funding & Grants Report — Programs That Could Fund Headway's Continued Development

**Date:** 2026-07-13
**Status:** Research draft — web-sourced; every claim cites its URL. Eligibility and deadlines are only asserted where a primary source (solicitation, statute, NOFO, program page, grants.gov/SAM.gov record) says them; where a primary source could not be reached, that is flagged inline. PENDING human review.
**Applicant entities considered:** Headway the open-source project (Apache-2.0, github.com/headway-transit/headway), Bekus Solutions (small for-profit, WA) as SBIR/for-profit applicant, and the agency-partnership path (a transit agency applies; Headway is the funded technology).

Path labels: **DIRECT** (Bekus Solutions or the project can apply itself), **PARTNER** (only agencies/nonprofits apply; Headway rides as the procured technology), **WATCH** (real and recurring, but no open window today), **NO-FIT** (looks attractive, verified not to fit — see the dedicated section).

---

## Method

Research run 2026-07-08 → 2026-07-13 via web search and direct primary-source fetches, in five parallel sweeps (federal open-source / NSF; USDOT SBIR + TRB IDEA + TCRP; FTA/USDOT innovation programs; Washington State; philanthropy + transit ecosystem). 67 search queries (listed verbatim in the appendix), plus direct fetches of: NSF solicitations (26-506, 26-510, 22-632), the grants.gov Search2 API (agency DOT-FTA, all statuses), the SAM.gov opportunities API (FY26 DOT SBIR record + Appendix A topics PDF), Federal Register full texts (2026-13907, 2024-14429, 2024-28271), 49 USC 5312 (uscode.house.gov), the enrolled text of H.R. 7148 (Consolidated Appropriations Act, 2026), RCW chapter 47.66 (full chapter), the TRB IDEA Program Announcement PDF, WSTIP program pages and its 2024 Annual Report/2022 audited financials, and foundation program pages (Sloan, Mozilla, Omidyar, Schmidt Sciences, Sovereign Tech, NLnet, CZI, GitHub, Code for Science & Society).

Limits: `volpe.dot.gov`, `transit.dot.gov`, `transportation.gov`, `opentech.fund`, and `mobilitydata.org` blocked automated fetching (403) — claims resting on those pages are marked and rest on official mirrors (SAM.gov, Federal Register, US Code, grants.gov API) or search-indexed snippets of the agency's own pages. Anything that could not be verified from a primary source is stated as unverified rather than guessed.

---

## Executive summary — ranked top 5 (fit × accessibility × award size)

**The single most important finding: NSF POSE no longer exists.** The POSE program page is marked "Status: Archived"; it has been superseded by **PESOSE — Pathways to Enable Secure Open-Source Ecosystems (NSF 26-506)**, posted 2026-02-19, with a **September 1, 2026 full-proposal deadline** ([program page](https://www.nsf.gov/funding/opportunities/pesose-pathways-enable-secure-open-source-ecosystems); [POSE archive notice](https://www.nsf.gov/funding/opportunities/pose-pathways-enable-open-source-ecosystems)). Any funding strategy written around "POSE" should be rewritten around PESOSE — and the deadline is seven weeks out.

| # | Program | Path | Money | Next date | Why this rank |
|---|---------|------|-------|-----------|---------------|
| 1 | **NSF PESOSE Track 1** (NSF 26-506) | DIRECT — for-profit small businesses are explicitly eligible; Daniel as PI, Bekus Solutions as proposing org | $300K / 1 yr (Track 2: $1.5M / 2 yrs later) | **Sept 1, 2026** (then Mar 2, 2027) | The only federal program whose literal purpose is funding an open-source ecosystem around an existing product. Strong fit, direct eligibility, real money, live deadline. Gate: 3–5 letters from independent users/contributors. |
| 2 | **TRB Transit IDEA** | DIRECT — "open to all," individuals and small businesses | up to $100K (most awards $70–85K) | FY26 closed Jun 30, 2026; next ~mid-2027 | Transit-specific, investigator-driven, small-business-friendly; safety/efficiency focus areas match NTD S&S + reporting automation exactly. Smaller dollars, annual cycle. |
| 3 | **NSF SBIR Phase I** (America's Seed Fund, NSF 26-510) | DIRECT — Bekus Solutions qualifies; mandatory Project Pitch first | $305K Phase I → $1.25M Phase II | Pitch by early fall for the **Nov 4, 2026** deadline | Largest direct-award ladder available; moderate fit (must frame the provenance-computation R&D, not "reporting software"); the Project Pitch is a cheap appetite test. |
| 4 | **WSDOT Consolidated Grant Program** (2027-2029 biennium) | PARTNER — nonprofits, tribes, transit and local agencies only | prior cycle: $136.5M across 153 projects; tech purchases eligible under Capital | **Applications due 3 p.m. Sept 9, 2026** (opened Jun 16) | The big in-state channel, open right now. Needs one WA agency to carry Headway as a technology line item; otherwise the next cycle is ~June 2028. |
| 5 | **WSTIP member grants** (Risk Management $5K/yr; Technology Grant up to ~$500K reserve pool) | PARTNER — grants go to WSTIP's ~25 member transit agencies, never to vendors | $5K RM per member/yr; tech awards historically ~$30–100K | RM grants rolling Jan 1–Dec 15 annually | Smallest dollars, best shape: 25 identical WA prospects, an always-open window, and documented precedent of members using these grants to buy vendor safety tech (Lytx DriveCam). Direct fit for the NTD Safety & Security module. |

Watch list (real, recurring, nothing open today): **USDOT SBIR FY27** (pre-solicitation ~April 2027 — FY26 closed July 7, 2026 and had no data/reporting topic), **FTA 49 USC 5312 research NOFOs** (for-profits statutorily eligible; EMI's FY2024 eligibility list literally included "software and technology developers"; zero research NOFOs open or forecasted today), **TCRP problem statements** (FY2028 window ~June 2027), **Cal-ITP Mobility Marketplace** (NTD reporting is an unlisted category — white space), **GitHub Secure Open Source Fund** ($10K, rolling, security-hardening scope), **Code for Science & Society fiscal sponsorship** (enabling move that opens 501(c)(3)-only funders).

*Ranking rationale:* #1–3 are programs Bekus Solutions can apply to with no one's permission; #4–5 require a Washington agency partner but are the nearest-term paths to funded deployments (which in turn produce the user letters #1 needs). The two nearest hard deadlines — PESOSE Sept 1 and WSDOT Sept 9 — are eight days apart.

---

## 1. NSF PESOSE — Pathways to Enable Secure Open-Source Ecosystems (NSF 26-506) — **DIRECT, top pick**

**What it is.** The successor to POSE (archived; final solicitation NSF 24-606) and Safe-OSE (also archived; absorbed as PESOSE Track 3). Posted 2026-02-19, lead directorate CISE with seven other directorates participating. Goal: translation of open-source products "into safe and sustainable ecosystems that address national and societal challenges" ([solicitation](https://www.nsf.gov/funding/opportunities/pesose-pathways-enable-secure-open-source-ecosystems/nsf26-506/solicitation); [program page](https://www.nsf.gov/funding/opportunities/pesose-pathways-enable-secure-open-source-ecosystems)).

**Eligibility (verified, verbatim from the solicitation).** "For-profit organizations: U.S.-based commercial organizations, including small businesses, with strong capabilities in scientific or engineering research or education and a passion for innovation" may submit; the PI "must be an employee of the proposing organization." So Bekus Solutions can be the proposing/managing organization with Daniel as PI. Individuals cannot apply directly. Every proposal must point to an existing publicly-available open-source product and document its user and contributor base — and must include **3–5 letters of collaboration from current users or contributors not directly related to the proposing team**.

**Structure and money.** Track 1 (Scoping & Planning): up to **$300K / 1 year**, ~30 awards — ecosystem discovery, governance design, risk/security plan, community-building strategy. Track 2 (Establishing & Expanding): up to **$1.5M / 2 years**, ~10 awards — requires documented demand and an existing user/contributor base. Track 3 (security of mature OSEs): $1.5M / 2 years. $40M total, 40–60 awards, no LOI required, no per-org proposal limit.

**Deadlines.** **September 1, 2026**, then March 2, 2027, then first Tuesday of March/September annually. Program Q&A webinar July 21, 2026; proposal-preparation webinar August 11, 2026.

**Fit.** Strong. A federally mandated reporting pipeline used by ~2,000+ NTD reporters is a legible "national and societal challenge"; the new "secure" framing rewards exactly Headway's provenance/auditability/supply-chain story (Track 1 already requires security safeguards and risk analysis as deliverables). Risks: (a) the 3–5 independent user/contributor letters are a hard gate if traction is thin; (b) "science and engineering-focused research product" framing is weaker for a civic-data tool than for a lab-born one — worth a program-officer conversation before July 21.

**What Daniel would do next.** Start the letters *now* — identify 3–5 independent users/contributors (pilot agencies, consultancies, contributors) and ask this week; register/attend the July 21 Q&A and Aug 11 webinar; draft a Track 1 proposal (ecosystem scoping: governance, agency onboarding, contributor pipeline, security plan) targeting Sept 1, with Mar 2, 2027 as the fallback if letters aren't ready.

## 2. TRB Transit IDEA — **DIRECT**

**What it is.** TRB's small-innovator arm of TCRP (FTA-funded, National Academies-managed): investigator-driven exploratory projects in transit, priority areas including transit safety/security and operational efficiency ([IDEA program page](https://www.trb.org/IDEAProgram/IDEAProgram.aspx); [Program Announcement PDF](https://onlinepubs.trb.org/onlinepubs/IDEA/IDEA_Program_Announcement.pdf)).

**Eligibility (verified).** The Program Announcement states verbatim that "IDEA programs are open to all" — inventors, businesses, academia; private-sector proposers need SAM registration. A small business, or Daniel individually, can propose.

**Money.** Type 1 (concept) and Type 2 (prototype) proposals "for up to $100,000 in IDEA costs"; Type 2 requires ≥20% cost share; most awards run $70,000–$85,000 ([TRB project page](https://apps.trb.org/cmsfeed/TRBNetProjectDisplay.asp?ProjectID=1170)). *Caveat:* the posted announcement PDF is dated (~2020 deadlines inside); reconfirm the ceiling when the 2027 announcement posts.

**Status.** Funded and running: TRB's official account announced a **June 30, 2026** proposal deadline ([@NASEMTRB](https://x.com/NASEMTRB/status/2054261637448663461)) — now passed. One review cycle per year, so expect ~mid-2027 next. *Flagged honestly:* the June 30, 2026 date was verifiable only from TRB's official social account; trb.org's own pages are stale (the submit page still shows 2022 deadlines). Confirm with the IDEA office: ideaprogram@nas.edu; Transit IDEA program officer Velvet Basemera-Fitzpatrick (vfitzpatrick@nas.edu, 202-334-2324).

**Fit.** Strong: "provenance-backed automation of NTD Safety & Security and service reporting for small agencies" sits squarely in the safety and efficiency focus areas, and the announcement explicitly encourages transit-agency participation and early-implementation paths — pilot-agency letters would carry weight.

**What Daniel would do next.** Email the IDEA office to confirm the 2027 cycle and get on the announcement list; line up 1–2 WA pilot agencies as named participants; draft a Type 1 concept around the NTD S&S module.

## 3. NSF SBIR — America's Seed Fund (NSF 26-510) — **DIRECT**

**What it is.** NSF's FY2026 SBIR/STTR relaunch: "Developing Deep Technologies that Advance U.S. Competitiveness and Security." Technology-agnostic ("the programs do not solicit specific technologies"), open to software ([solicitation](https://www.nsf.gov/funding/opportunities/small-business-innovation-research-small-business-technology/nsf26-510/solicitation); [open solicitations](https://seedfund.nsf.gov/solicitations/)).

**Eligibility (verified).** U.S. for-profit small business (<500 employees incl. affiliates), ≥50% owned by U.S. citizens/permanent residents; PI primarily employed by the company at award (≥20 hrs/week). Bekus Solutions qualifies structurally. A **Project Pitch is mandatory** before any Phase I proposal (max two pitches/company/year; an invitation covers the next two deadlines) ([get started](https://seedfund.nsf.gov/apply/get-started/)).

**Money.** Phase I up to **$305,000** (6–18 months); Phase II up to **$1,250,000**; Fast-Track combined up to $1,555,555. No equity; company keeps IP.

**Deadlines.** Full proposals July 27, 2026 (out of reach given pitch turnaround); **November 4, 2026**; March 4, 2027; then annually. Pitch turnaround is ~1–2 months, so a pitch by early fall targets Nov 4.

**Fit.** Moderate, with a framing job: NTD reporting automation reads as govtech SaaS unless the pitch isolates the genuinely novel R&D (provenance-carrying deterministic computation over heterogeneous transit data; verifiable regulatory reporting). The open-source/commercialization tension resolves the standard way: Apache-2.0 engine + Bekus Solutions' hosted/support/certification layer as the commercial story.

**What Daniel would do next.** Write the 2-page Project Pitch (free, fast, non-binding) in September framed on the provenance-computation R&D; submit targeting the November 4 Phase I deadline only if invited.

## 4. WSDOT Consolidated Grant Program (2027-2029) — **PARTNER, open now**

**What it is.** WSDOT's biennial consolidated public-transportation grant program (FTA 5310/5311 pass-through + state accounts + 20% Climate Commitment Act). The **2027-2029 cycle is open**: applications opened June 16, 2026; **due 3 p.m. September 9, 2026**; revised applications Nov 13, 2026; awards May–June 2027 ([WSDOT program page](https://wsdot.wa.gov/business-wsdot/grants/public-transportation-grants/public-transportation-grant-programs-and-awards/consolidated); [current-cycle FAQ](https://wsdot.wa.gov/sites/default/files/2026-01/PT-Guide-Grants-ConsolidatedGrantProgramFrequentlyAskedQuestions.pdf)).

**Eligibility (verified, quoted).** "Nonprofits, tribes, public transit agencies, and local agencies in Washington state are eligible to apply." Bekus Solutions cannot apply directly.

**Money.** No fixed per-award cap published; the prior (2025-2027) cycle totaled $136.5M across 153 projects. Five categories — the **Capital category explicitly includes "vehicle, equipment, and technology purchases."** Match: 10% sustaining, 5% new/expansion.

**Fit / partnership path.** A rural/special-needs WA agency (exactly the small-agency audience Headway's one-box deployment targets) includes Headway procurement + support as a Capital technology line item, then procures Bekus Solutions under normal public procurement. NTD reporting burden is a documented pain point for the 5311-sized agencies this program funds.

**What Daniel would do next.** This is an eight-week window: contact the 2–3 friendliest WA small-agency prospects immediately and offer to draft the technology line item and justification for their application. If none bites by mid-August, target the 2029-2031 cycle (applications ~June 2028) with pilots already running.

## 5. WSTIP member grants — **PARTNER, always-on**

**What it is.** The Washington State Transit Insurance Pool (~25 member transit agencies — 7 large, 9 medium, 9–10 small per its [member list](https://www.wstip.org/members/memberlist.html) and [2024 Annual Report](https://www.wstip.org/userfiles/Annual%20Reports/WSTIP_2024_Annual_Report.pdf)) runs four member funding programs: **Risk Management Grant, Technology Grant, Network Security Grant**, and a scholarship ([wstip.org](https://wstip.org/)).

**Verified mechanics.** Risk Management Grant: "Maximum funding is $5,000 per member per year" for projects "intended to avoid, prevent, or reduce the likelihood of accidental loss"; applications accepted Jan 1 – Dec 15 annually, decisions typically under two weeks; cannot fund staff salaries ([rmgrant page](https://www.wstip.org/rmgrant/)). Technology Grant: the public page is member-gated, but WSTIP's own [2022 audited financials](https://www.wstip.org/userfiles/Financial%20Audits/2022_WSTIP_Audited_Financial_Statements.pdf) describe an "Unrestricted Technology Grant Reserve" carrying forward up to **$500,000** (~$484K designated), and the [2021 Annual Report](https://www.wstip.org/userfiles/Annual%20Reports/WSTIP_2021_Annual_Report.pdf) shows **$95,854 awarded to three members** for vendor technology — Lytx DriveCam (Community Transit), TrackIt! (Grays Harbor). *Flagged:* current Technology and Network Security Grant terms could not be verified from public pages (member-gated); confirm with WSTIP Member Services (Joanne Kerrigan, 360-786-1647, joanne@wstip.org).

**Fit — honest shape.** WSTIP grants go to members, never vendors: **there is no mechanism that pays Bekus Solutions directly.** But the precedent is exactly Headway's shape — members using pool grants to procure vendor risk/safety technology — and the NTD Safety & Security reporting module is a clean loss-prevention/compliance-risk story. WSTIP also has pool-wide technology-initiative history (it once won a TRB IDEA grant to evaluate collision-avoidance tech across members — [Mass Transit coverage](https://www.masstransitmag.com/bus/article/12127151/wstip-awarded-trb-idea-grant-to-study-and-evaluate-collision-avoidance-technology), secondary source) and its 2024 Annual Report emphasizes intensifying proactive loss prevention.

**What Daniel would do next.** One call to Member Services: pitch provenance-backed NTD S&S reporting as a member risk-reduction tool, ask for the Technology Grant terms, and ask whether WSTIP would flag it to members as grant-eligible. Then let member agencies apply with Headway as the named procurement — a repeatable motion across 25 prospects.

---

## 6. USDOT SBIR (Volpe-administered) — **DIRECT but topic-gated; WATCH FY27**

**No STTR exists at USDOT** — SBIR.gov lists DOT as SBIR-only (STTR requires >$1B extramural R&D; only USDA, DoD, DOE, HHS, NASA, NSF qualify) ([participating agencies](https://www.sbir.gov/participating-agencies); [SBIR FAQ](https://www.sbir.gov/faq); [CRS R43695](https://www.congress.gov/crs-product/R43695)). Awards are **contracts**, not grants; one annual Phase I solicitation with agency-authored topics only — no open topics.

**FY26 cycle (verified from the SAM.gov record, solicitation 6913G626QSBIR1):** pre-solicitation April 29 – May 29, 2026; solicitation ~June 3; **Phase I closed July 7, 2026** ([SAM.gov opportunity](https://sam.gov/opp/203f2a954cb14f149afee6b104d20914/view); [Volpe page](https://www.volpe.dot.gov/work-us/small-business-innovation-research/fy26-solicitation-now-open)). The 10 FY26 topics (verified from the official Appendix A PDF via SAM.gov) included exactly one FTA topic — 26-FT1, "Person-Centered, Carefree, Complete Trip Planning – Powered by AI" — i.e., **no NTD/reporting/data-quality topic this year**. Phase I ceiling: Volpe's pages state ~$200K/6 months, Phase II up to ~$1.5M/2 years; *flagged:* the exact FY26 Phase I ceiling could not be confirmed from a primary source (volpe.dot.gov blocks automated access) — verify by hand in the FY26 solicitation PDF.

**Eligibility.** Standard SBIR: for-profit ≤500 employees, majority U.S.-owned, PI primarily employed by the firm ([sbir.gov tutorial](https://www.sbir.gov/tutorials/program-basics/tutorial-2)). Open-source licensing is a business-model consideration (commercialization is scored), not an eligibility bar.

**What Daniel would do next.** Calendar the FY27 pre-solicitation watch for ~April 2027 (volpe.dot.gov + SAM.gov); use the public Q&A forum ([usdot.uservoice.com](https://usdot.uservoice.com/forums/967226)) that cycle; longer-game, get "NTD data quality/reporting automation" in front of FTA research staff so a topic like it exists to bid on.

## 7. FTA Public Transportation Innovation (49 USC 5312) — **DIRECT eligibility, WATCH for NOFOs**

**Statutory eligibility (verified from the US Code).** 49 USC 5312(b)(2) lists eligible recipients including "private or non-profit organizations" alongside governments, transit providers, and universities ([uscode.house.gov](https://uscode.house.gov/view.xhtml?req=%28title%3A49+section%3A5312+edition%3Aprelim%29)). Federal share ≤80%, waivable; in-kind match allowed. FTA runs it as topic-specific competitive NOFOs (usually cooperative agreements).

**Precedents that prove the direct path.** FY2024 Enhancing Mobility Innovation (FTA-2024-010-TRI-EMI, closed 8/30/2024, $1.936M, awards $400K–$968K) listed eligible applicants verbatim including "**software and technology developers**" ([Federal Register 2024-14429](https://www.federalregister.gov/documents/2024/07/01/2024-14429/fy-2024-competitive-funding-opportunity-enhancing-mobility-innovation)); the FY2025 Bus Safety and Accessibility Research Program ($10M, closed 1/17/2025) accepted for-profits ([grants.gov 357154](https://www.grants.gov/search-results-detail/357154)); the FY2025 Technology Transfer (T2) NOFO used the full 5312 list ([Federal Register 2024-28271](https://www.federalregister.gov/documents/2024/12/03/2024-28271/fiscal-year-2024-competitive-funding-opportunity-technology-transfer-t2-program)).

**Current status (verified via the grants.gov API, 2026-07-13).** FTA has exactly two posted opportunities — Tribal Transit FY2026 (tribes only, closes 8/25/2026) and ICAM (below) — and **zero forecasted research NOFOs**. All other FY2026 FTA competitions have been capital programs.

**What Daniel would do next.** Stand up a lightweight watch (grants.gov saved search, agency DOT-FTA + Federal Register FTA notices — the same "regulatory watch" motion the feature-gap report recommends for NTD dockets). When a data/standards/safety-research NOFO appears, Bekus Solutions applies directly; the FY2023 Transit Standards Development Program (FTA-2023-004-TRI) is the on-point precedent topic.

## 8. TCRP — **agenda-setting + subcontract path, slow**

**How it works (verified).** Anyone may submit a problem statement → screening panel (August 2026 this cycle) → TOPS Commission selection (October 2026) → panels → **RFPs to research contractors (spring 2027)** ([TCRP Getting Involved](https://www.trb.org/TCRP/TCRPGettingInvolved.aspx)). FY2027 problem statements closed **June 22, 2026**. Any qualified research organization — including a small business — can compete for TCRP contracts ([RFP page](https://www.trb.org/TCRP/RequestsforProposals.aspx); the live RFP list is JS-loaded and couldn't be enumerated — check by hand). TCRP is FTA-funded under 5312(i) and TRB-managed; APTA convenes oversight and dissemination only ([FTA TCRP page](https://www.transit.dot.gov/funding/grants/transit-cooperative-research-program-5312i); [APTA on TCRP](https://www.apta.com/news-research/transit-cooperative-research-program/about-tcrp/)).

**What Daniel would do next.** Two-track: submit an FY2028 problem statement (~June 2027, *extrapolated — not yet posted*) on NTD reporting burden/data-quality automation (free, agenda-shaping); meanwhile watch issued RFPs for a subcontract slot with an incumbent research firm or university — the realistic near-term entry. Even a selected problem statement leads to an openly-competed RFP ~18 months later.

## 9. FTA ICAM FY2026 pilot — **PARTNER, open now, moderate fit**

The one FTA competition open today: Innovative Coordinated Access and Mobility, ~$11.96M, **closes September 9, 2026** (FTA-2026-012-TPM-ICAM) — capital projects coordinating transportation and non-emergency medical transport for older adults, people with disabilities, and low-income riders ([Federal Register 2026-13907](https://www.federalregister.gov/documents/2026/07/09/2026-13907/fy-2026-competitive-funding-opportunity-innovative-coordinated-access-and-mobility); [grants.gov 363122](https://www.grants.gov/search-results-detail/363122)). Eligibility is 5310-shaped, and verbatim: "For profits organizations that do not operate public transportation are not eligible applicants." Fit is moderate (coordination-tech-centric, not reporting-centric; demand-response data provenance is the credible angle) — and it shares the September 9 deadline with the WSDOT Consolidated program. Only worth pursuing if an agency partner is already assembling an application that needs a data platform component; do not chase it cold.

## 10. Philanthropy and ecosystem — what's actually usable

- **GitHub Secure Open Source Fund** — **DIRECT, active, rolling**: $10,000/project ($6K/$2K/$2K tranches) plus a three-week security sprint; Session 4 began April 2026 ([program page](https://github.com/open-source/github-secure-open-source-fund); [announcement](https://github.blog/news-insights/company-news/announcing-github-secure-open-source-fund/)). Scope is security hardening of an existing project, not feature work, and demonstrated adoption matters. Small but real; the security-review deliverables would also feed a PESOSE Track 1 narrative. *Next step:* apply once there are named production deployments.
- **Code for Science & Society fiscal sponsorship** — **enabling move, accepting inquiries**: a 501(c)(3) public-interest-tech fiscal sponsor currently accepting new project inquiries ([apply page](https://www.codeforsociety.org/become-a-fiscally-sponsored-project)); would let the *project* (as distinct from Bekus Solutions) receive c3-only philanthropy (Knight open calls, future Mozilla calls) without forming a nonprofit. Fees not published — ask. Note: **Open Collective Foundation (the c3) dissolved end-2024** ([official statement](https://blog.opencollective.com/open-collective-official-statement-ocf-dissolution/)); Open Source Collective continues but is a 501(c)(6) (10% fee, donations not deductible, many foundations won't grant to it) ([fees](https://docs.oscollective.org/how-it-works/fees)).
- **Cal-ITP / California Mobility Marketplace** — **procurement, not grants**: vendors reach California agencies via DGS-awarded Master Service Agreements that agencies (including out-of-state buyers) purchase from without further bidding; current categories are data plans, scheduling, GTFS-RT, payments — **no NTD-reporting category exists, which is white space** ([camobilitymarketplace.org](https://www.camobilitymarketplace.org/); [Cal-ITP](https://www.calitp.org/)). Precedent that Caltrans pays small firms to build open-source transit software: Compiler LLC builds/maintains the open-source Cal-ITP Benefits app ([docs.calitp.org/benefits](https://docs.calitp.org/benefits/); [compiler.la](https://compiler.la/blog/2026/remix-case-study)). *Next step:* a conversation with Cal-ITP about an NTD-reporting MSA category; subcontract relationships (Compiler, Xentrans) as the nearer entry.
- **Open Source Pledge / GitHub Sponsors** — revenue rails, not grants: companies pledge ≥$2,000/dev/year to maintainers they depend on ([opensourcepledge.com](https://opensourcepledge.com/)). Pays off only after commercial actors depend on Headway. Plumbing to have in place; not a funding strategy.

---

## Paths that look attractive but don't fit (with reasons)

- **USDOT SMART grants** — **defunded.** The FY2026 appropriations act transfers **$204,912,000** from SMART's unobligated FY22–26 balances (verbatim in the enrolled [H.R. 7148](https://www.congress.gov/119/bills/hr7148/BILLS-119hr7148enr.htm)); no FY25/FY26 NOFO ever posted (grants.gov API, all statuses); DOT's page states no new NOFOs will be issued ([transportation.gov/grants/SMART](https://www.transportation.gov/grants/SMART), via snippet — page blocked direct fetch). It was public-sector-only anyway ([FY24 NOFO, grants.gov 354130](https://www.grants.gov/search-results-detail/354130)).
- **FTA AIM** — one NOFO ever (2020, ~$14M to 25 projects); nothing since ([grants.gov 325512](https://www.grants.gov/search-results-detail/325512); [FTA AIM selections](https://www.transit.dot.gov/research-innovation/fy20-accelerating-innovative-mobility-aim-project-selections)). Historical program, not a pipeline. (EMI, by contrast, ran twice — FY2021 and FY2024 — so it stays on the §7 watch list rather than here.)
- **ITS4US** — closed to new entrants; Phases 2/3 fund only four previously selected sites ([its.dot.gov overview](https://www.its.dot.gov/research-areas/ITS4US/overview/)). *Flagged:* no dated 2026 primary-source wind-down statement found; the primary page simply offers no path for new applicants.
- **"WSDOT Public Transportation Innovation Grant"** — **does not exist.** The full chapter [RCW 47.66](https://app.leg.wa.gov/RCW/default.aspx?cite=47.66&full=true) contains no innovation or innovative-partnership grant section; the name belongs to the federal 5312 program. Adjacent WA programs (Regional Mobility 47.66.030, Green Transportation Capital 47.66.120, Bus & Bus Facilities 47.66.130) are all agency-only.
- **WA open-data/civic-tech funds** — nothing fits. WaTech's Innovation & Modernization program is "only Washington state government organizations" and "not accepting grant proposals at this time" ([watech.wa.gov](https://watech.wa.gov/strategy/programs/innovation-and-modernization-program)); WaTech Open Data is a standards program with no money; Commerce's RD&D grants (due Sept 3, 2026) are scoped to clean-energy technologies TRL 4–7 ([commerce.wa.gov](https://www.commerce.wa.gov/funding/apply-now-for-research-development-and-demonstration-program-grants/)).
- **NSF CSSI** — for-profits cannot submit (IHEs/nonprofits/FFRDCs only), and it funds cyberinfrastructure for *science research communities* ([NSF 22-632](https://www.nsf.gov/funding/opportunities/cssi-cyberinfrastructure-sustained-scientific-innovation/nsf22-632/solicitation)). Only opportunistic via a university partner (e.g., UW/TRAC) if researchers adopt Headway. *Flagged:* whether a Dec 1, 2026 cycle will run could not be confirmed from a refreshed solicitation.
- **Sloan Foundation** — Technology program scope is *research/academic* software (Open Source in Science takes 2-page LOIs; Better Software for Science is marked Completed); it states it does not fund individual OSS development projects, and civic/transit data is outside scope ([sloan.org](https://sloan.org/programs/digital-technology/open-source-in-science)).
- **Mozilla** — MOSS "is on indefinite hiatus" ([mozilla.org/moss](https://www.mozilla.org/en-US/moss/)); no open Technology Fund call as of today; current grantmaking is AI/trustworthy-tech themed ([foundation grantmaking page](https://www.mozillafoundation.org/en/what-we-fund/programs/mozilla-technology-fund-mtf/call-for-proposals/)). Watch for future Incubator calls; don't plan on it.
- **Open Technology Fund** — internet-freedom mandate (censorship circumvention, anti-surveillance); a US domestic transit platform does not fit, full stop — and OTF's own federal funding was terminated in March 2025 and is in litigation ([OTF lawsuit statement](https://www.opentech.fund/news/open-technology-fund-files-lawsuit-to-contest-grant-termination-and-preserve-critical-mission/)).
- **Knight Foundation / Omidyar Network** — no unsolicited door. Knight: "funding typically emerges through relationships" with occasional targeted open calls ([how we fund](https://knightfoundation.org/how-we-fund/)); Omidyar: "We do not accept funding requests or proposals" ([FAQ](https://omidyar.com/frequently-asked-questions/)).
- **Schmidt Sciences VISS** — a network of four university centers serving academic researchers; no external application channel ([schmidtsciences.org/viss](https://www.schmidtsciences.org/viss/)).
- **Sovereign Tech Fund (Germany)** — worldwide eligibility, but funds "open digital base technologies" (libraries, protocols, toolchains) and states verbatim "We are currently not looking for user-facing applications" ([sovereign.tech/programs/fund](https://www.sovereign.tech/programs/fund)). Headway is an application; it fails the core criterion regardless of geography.
- **NLnet / NGI Zero** — the final Commons Fund call closed June 1, 2026, and non-EU proposals require "a clear European dimension" ([eligibility](https://nlnet.nl/commonsfund/eligibility/)). A US FTA-reporting tool has none.
- **CZI EOSS** — biomedical-research software only, and the program has concluded (successor Open Source for Science Fund is also science-only) ([chanzuckerberg.com/eoss](https://chanzuckerberg.com/rfa/essential-open-source-software-for-science/); [Renaissance Philanthropy](https://www.renaissancephilanthropy.org/insights/open-source-for-science-fund-launches)).
- **GitHub Accelerator** — last cohort 2024 (AI-themed); no 2025/2026 cohort announced from primary sources — treat as dormant ([accelerator.github.com](https://accelerator.github.com/)).
- **APTA** — plainly: a trade association, not a grantor. Transit research money flows through TCRP (FTA-funded, TRB-managed); APTA convenes oversight and dissemination ([APTA on TCRP](https://www.apta.com/news-research/transit-cooperative-research-program/about-tcrp/)).
- **MobilityData** — membership dues flow inward; no evidence it funds external projects ([mobilitydata.org](https://mobilitydata.org/)). Note: rumored 2024–2025 financial troubles could **not** be verified from any public source — do not repeat that claim in a proposal.
- **CISA / "Securing Open Source Software Act" / 18F** — no money here: CISA's OSS Security Roadmap has no grant mechanism ([cisa.gov](https://www.cisa.gov/resources-tools/resources/cisa-open-source-software-security-roadmap)); the Act never passed (S.917, 118th Congress — [congress.gov](https://www.congress.gov/bill/118th-congress/senate-bill/917/all-info)); 18F was eliminated March 1, 2025 ([Nextgov](https://www.nextgov.com/people/2025/03/gsa-eliminates-18f/403400/)). The closest real federal OSS money is PESOSE.
- **WSDOT Research Program** — real (SPR-funded, biennial [work program](https://wsdot.wa.gov/sites/default/files/2025-07/Funding-StatePlanningResearchWorkProgram-2527Biennium.pdf)) but publishes no open solicitation or private-firm eligibility; administered heavily through universities (UW TRAC). *Flagged unverified:* whether private firms can propose directly — assume not absent contact with the Research Office (360-705-7961). University-partnership play only.

---

## Verification note

Every grant claim above was checked against program pages, solicitations, statutes, or the grants.gov/SAM.gov records as of **2026-07-13**. Residual uncertainty, stated plainly:

- **Transit IDEA's June 30, 2026 deadline** was verifiable only from TRB's official X account; trb.org pages are stale. The current award ceiling rests on a ~2020 Program Announcement PDF. Confirm both with the IDEA office before planning a 2027 submission.
- **USDOT SBIR FY26 Phase I dollar ceiling** ($200K per Volpe page snippets vs. up-to-$300K per a secondary source) is unresolved — volpe.dot.gov blocks automated access; verify in the FY26 solicitation PDF.
- **WSTIP Technology and Network Security Grant current terms** are member-gated; amounts cited come from WSTIP's own audited financials and annual reports (2021/2022 vintage). Call Member Services.
- **NSF CSSI's December 1, 2026 cycle** and **TCRP's FY2028 problem-statement window (~June 2027)** are extrapolations from published schedules, not posted dates.
- **FTA T2 award status**, a dated 2026 **ITS4US** wind-down statement, and any FTA intention to issue an FY2026 5312 research NOFO could not be verified (none is forecasted on grants.gov).
- `transit.dot.gov`, `transportation.gov`, `volpe.dot.gov`, `opentech.fund`, and `mobilitydata.org` blocked direct fetching; where used, their content came from official mirrors (Federal Register, US Code, SAM.gov, grants.gov, congress.gov) or search-indexed snippets of the agencies' own pages, and is marked as such.

---

## Appendix — search queries run (verbatim, by sweep)

NSF / federal open-source (6):
1. `NSF POSE Pathways to Enable Open-Source Ecosystems 2026 solicitation deadline`
2. `NSF POSE solicitation 24-503 status 2026`
3. `NSF SBIR America's Seed Fund 2026 solicitation deadline small business Phase I`
4. `NSF CSSI Cyberinfrastructure for Sustained Scientific Innovation 2026 solicitation status`
5. `"NSF 26-510" SBIR STTR deep technologies solicitation`
6. `NSF Safe-OSE Safety Security Privacy Open-Source Ecosystems 2026 solicitation archived PESOSE`

USDOT SBIR / Transit IDEA / TCRP (15):
7. `USDOT SBIR program Volpe Center 2026 solicitation topics`
8. `TRB Transit IDEA program 2026 proposal deadline funding status`
9. `TCRP problem statement submission deadline 2026`
10. `DOT FY26 SBIR Phase I topics list FTA transit topic 26-FT`
11. `"Transit IDEA" proposal deadline "June 30, 2026"`
12. `USDOT SBIR "STTR" "does not" DOT extramural research budget threshold`
13. `site:sbir.gov DOT FY26 solicitation Phase I 2026`
14. `"26-FT1" SBIR FTA topic`
15. `Transit IDEA program announcement 2026 pdf onlinepubs.trb.org award`
16. `"Transit IDEA" program paused OR suspended OR "not accepting" proposals funding 2023 2024`
17. `"Transit IDEA" 2026 announcement "June 30" proposals $100,000 TRB`
18. `Transit IDEA overview site:trb.org OR site:nationalacademies.org`
19. `volpe.dot.gov FY26 SBIR phase I award amount "$" six-month period of performance`
20. `Volpe "about" DOT SBIR "Phase II" award "will not exceed" amount months`
21. `sbir.gov eligibility 500 employees "more than 50%" owned citizens for-profit principal investigator`

FTA/USDOT innovation programs (7):
22. `FTA Public Transportation Innovation 5312 eligibility private for-profit NOFO 2026`
23. `USDOT SMART grants FY2026 notice of funding opportunity deadline Stage 1`
24. `SMART grants program 2025 2026 status "Stage 2" FY25 no new funding rounds`
25. `ITS4US deployment program status 2025 phase 3 sites complete no new funding`
26. `FTA "Accelerating Innovative Mobility" AIM program status completed projects`
27. `"SMART" grants rescission "204,912,000" OR "unobligated balances" Consolidated Appropriations Act 2026 transportation`
28. `FTA Technology Transfer Program $5 million cooperative agreement selected awardee 2025`

Washington State (13):
29. `WSDOT Consolidated Grant Program public transportation 2025-2027 biennium`
30. `WSTIP grant program member risk management funding transit insurance pool`
31. `WSDOT Public Transportation Innovation grant RCW 47.66 innovative partnership`
32. `WSDOT research program office how to propose research project funding university`
33. `WSDOT "public transportation innovation" grant program`
34. `Washington state Commerce WaTech grant open data civic technology innovation software`
35. `Cal-ITP Caltrans contract transit data MnDOT research program transit data tools funding`
36. `WSTIP technology grant network security grant member`
37. `MnDOT research program solicitation transportation research ideas how funded`
38. `site:wstip.org "Technology Grant"`
39. `WSTIP annual report 2024 technology grant network security grant awarded members`
40. `"RCW 47.66.090" public transportation innovation repealed`
41. `Washington Department of Commerce innovation grant program technology companies 2026`

Philanthropy / ecosystem / federal OSS (26):
42. `Alfred P. Sloan Foundation Technology program open source grants "Better Software for Science"`
43. `Mozilla Open Source Support MOSS program status 2026 discontinued`
44. `Open Technology Fund apply internet freedom eligibility 2026`
45. `Open Technology Fund funding status 2025 2026 USAGM lawsuit terminated grants`
46. `Mozilla Technology Fund 2026 call for proposals status`
47. `Knight Foundation how to apply unsolicited proposals 2026`
48. `Omidyar Network how we fund unsolicited proposals grants`
49. `Schmidt Sciences Virtual Institute for Scientific Software open source 2026`
50. `GitHub Accelerator 2026 open source funding status`
51. `Sovereign Tech Agency eligibility application 2026 open source infrastructure`
52. `NLnet foundation NGI Zero open call 2026 eligibility applicants outside EU`
53. `Chan Zuckerberg Initiative Essential Open Source Software EOSS program status 2025 2026`
54. `"Sovereign Tech Fund" application criteria "outside of Germany" OR "anywhere in the world" eligibility maintainers`
55. `Code for Science and Society fiscal sponsorship accepting new projects 2026`
56. `Open Source Pledge 2026 status companies pay maintainers GitHub Sponsors`
57. `Cal-ITP vendor contracting Compiler LLC Caltrans Mobility Marketplace solicitations`
58. `MobilityData financial difficulties 2024 2025 layoffs funding membership`
59. `APTA grants program does APTA fund research TCRP trade association`
60. `"MobilityData" "funding" crisis OR shortfall OR "difficult decision" OR restructuring 2025`
61. `Compiler LLC Cal-ITP Caltrans transit data contractor`
62. `Securing Open Source Software Act status passed Congress CISA open source security roadmap 2025 2026`
63. `NSF Pathways to Enable Open-Source Ecosystems POSE program 2026 solicitation`
64. `GitHub Accelerator 2025 cohort applications discontinued OR paused OR "no upcoming"`
65. `GitHub Secure Open Source Fund session 3 2026 applications open`
66. `Open Collective Foundation dissolution 2024 Open Source Collective fiscal host 501(c)(6) fees status`
67. `18F shut down eliminated GSA 2025 status Technology Transformation Services`

---

## Sources

Federal — NSF:
- https://www.nsf.gov/funding/opportunities/pesose-pathways-enable-secure-open-source-ecosystems — PESOSE program page (status, deadlines, webinars)
- https://www.nsf.gov/funding/opportunities/pesose-pathways-enable-secure-open-source-ecosystems/nsf26-506/solicitation — NSF 26-506 solicitation (eligibility, tracks, letters requirement)
- https://www.nsf.gov/funding/opportunities/pose-pathways-enable-open-source-ecosystems — POSE archive notice
- https://www.nsf.gov/funding/opportunities/pose-pathways-enable-open-source-ecosystems/505982/nsf24-606/solicitation — final POSE solicitation (historical)
- https://www.nsf.gov/funding/opportunities/safe-ose-safety-security-privacy-open-source-ecosystems — Safe-OSE (archived)
- https://www.nsf.gov/funding/opportunities/small-business-innovation-research-small-business-technology/nsf26-510/solicitation — NSF SBIR FY2026
- https://seedfund.nsf.gov/solicitations/ , https://seedfund.nsf.gov/apply/get-started/ , https://seedfund.nsf.gov/apply/full-proposal/ — America's Seed Fund mechanics
- https://www.nsf.gov/funding/opportunities/cssi-cyberinfrastructure-sustained-scientific-innovation — CSSI program page
- https://www.nsf.gov/funding/opportunities/cssi-cyberinfrastructure-sustained-scientific-innovation/nsf22-632/solicitation — NSF 22-632

Federal — USDOT/FTA/TRB:
- https://www.sbir.gov/participating-agencies , https://www.sbir.gov/faq , https://www.sbir.gov/tutorials/program-basics/tutorial-2 — SBIR/STTR agency list, thresholds, eligibility
- https://www.congress.gov/crs-product/R43695 — CRS on SBIR/STTR thresholds
- https://sam.gov/opp/203f2a954cb14f149afee6b104d20914/view — FY26 DOT SBIR SAM.gov record (incl. Appendix A topics PDF)
- https://www.volpe.dot.gov/work-us/small-business-innovation-research/fy26-solicitation-now-open — Volpe FY26 status (blocked; snippet)
- https://www.trb.org/IDEAProgram/IDEAProgram.aspx , https://www.trb.org/IDEAProgram/IDEASubmitProposal.aspx — Transit IDEA pages (stale)
- https://onlinepubs.trb.org/onlinepubs/IDEA/IDEA_Program_Announcement.pdf — IDEA Program Announcement (eligibility, award sizes)
- https://apps.trb.org/cmsfeed/TRBNetProjectDisplay.asp?ProjectID=1170 — Transit IDEA award sizes
- https://x.com/NASEMTRB/status/2054261637448663461 — TRB announcement of June 30, 2026 deadline
- https://www.trb.org/TCRP/TCRPGettingInvolved.aspx , https://www.trb.org/TCRP/RequestsforProposals.aspx , https://www.trb.org/TCRP/AboutTCRP.aspx — TCRP process
- https://www.transit.dot.gov/funding/grants/transit-cooperative-research-program-5312i — TCRP funding authority
- https://uscode.house.gov/view.xhtml?req=%28title%3A49+section%3A5312+edition%3Aprelim%29 — 49 USC 5312 (eligibility, cost share)
- https://www.transit.dot.gov/funding/grants/public-transportation-innovation-5312 — FTA 5312 page (blocked; snippet)
- https://www.federalregister.gov/documents/2024/07/01/2024-14429/fy-2024-competitive-funding-opportunity-enhancing-mobility-innovation — EMI FY2024 NOFO ("software and technology developers")
- https://www.federalregister.gov/documents/2024/12/03/2024-28271/fiscal-year-2024-competitive-funding-opportunity-technology-transfer-t2-program — T2 NOFO
- https://www.federalregister.gov/documents/2026/07/09/2026-13907/fy-2026-competitive-funding-opportunity-innovative-coordinated-access-and-mobility — ICAM FY2026 NOFO
- https://www.grants.gov/search-results-detail/363122 (ICAM), /357154 (Bus Safety Research), /354130 (SMART FY24 Stage 1), /325512 (AIM 2020) — grants.gov records
- https://www.congress.gov/119/bills/hr7148/BILLS-119hr7148enr.htm — H.R. 7148 enrolled (SMART transfer of $204,912,000)
- https://www.transportation.gov/grants/SMART — SMART status (blocked; snippet)
- https://www.its.dot.gov/research-areas/ITS4US/overview/ — ITS4US phases/sites
- https://www.transit.dot.gov/AIM , https://www.transit.dot.gov/research-innovation/fy20-accelerating-innovative-mobility-aim-project-selections — AIM history

Washington State:
- https://wsdot.wa.gov/business-wsdot/grants/public-transportation-grants/public-transportation-grant-programs-and-awards/consolidated — Consolidated Grant Program (cycle, eligibility, categories)
- https://wsdot.wa.gov/sites/default/files/2026-01/PT-Guide-Grants-ConsolidatedGrantProgramFrequentlyAskedQuestions.pdf — current-cycle FAQ
- https://app.leg.wa.gov/RCW/default.aspx?cite=47.66&full=true — RCW 47.66 full chapter
- https://app.leg.wa.gov/RCW/default.aspx?cite=47.29 — RCW 47.29 (P3 authority, not grants)
- https://wsdot.wa.gov/about/library-research-reports/research-reports , https://wsdot.wa.gov/sites/default/files/2025-07/Funding-StatePlanningResearchWorkProgram-2527Biennium.pdf — WSDOT research program
- https://wstip.org/ , https://www.wstip.org/rmgrant/ , https://www.wstip.org/members/memberlist.html , https://www.wstip.org/organization/ — WSTIP programs and members
- https://www.wstip.org/userfiles/Annual%20Reports/WSTIP_2024_Annual_Report.pdf , https://www.wstip.org/userfiles/Annual%20Reports/WSTIP_2021_Annual_Report.pdf , https://www.wstip.org/userfiles/Financial%20Audits/2022_WSTIP_Audited_Financial_Statements.pdf — WSTIP grant evidence
- https://www.masstransitmag.com/bus/article/12127151/wstip-awarded-trb-idea-grant-to-study-and-evaluate-collision-avoidance-technology — WSTIP/IDEA precedent (secondary)
- https://watech.wa.gov/strategy/programs/innovation-and-modernization-program , https://watech.wa.gov/strategy/programs/open-data — WaTech
- https://www.commerce.wa.gov/funding/apply-now-for-research-development-and-demonstration-program-grants/ — Commerce RD&D (clean energy)

Philanthropy / open-source / ecosystem:
- https://sloan.org/programs/digital-technology/open-source-in-science , https://sloan.org/programs/digital-technology/better-software-for-science — Sloan scope
- https://www.mozilla.org/en-US/moss/ — MOSS hiatus
- https://www.mozillafoundation.org/en/what-we-fund/programs/mozilla-technology-fund-mtf/call-for-proposals/ — Mozilla grantmaking status
- https://www.opentech.fund/funds/internet-freedom-fund/ , https://www.opentech.fund/news/open-technology-fund-files-lawsuit-to-contest-grant-termination-and-preserve-critical-mission/ — OTF mandate and funding litigation
- https://knightfoundation.org/how-we-fund/ , https://knightfoundation.org/apply/ — Knight model
- https://omidyar.com/frequently-asked-questions/ — Omidyar (no unsolicited proposals)
- https://www.schmidtsciences.org/viss/ — Schmidt VISS
- https://accelerator.github.com/ , https://github.com/open-source/accelerator — GitHub Accelerator (2024 cohort)
- https://github.com/open-source/github-secure-open-source-fund , https://github.blog/news-insights/company-news/announcing-github-secure-open-source-fund/ — Secure OSS Fund
- https://github.com/open-source/sponsors , https://opensourcepledge.com/ — sponsorship rails
- https://www.sovereign.tech/programs/fund — Sovereign Tech Fund criteria ("not… user-facing applications")
- https://nlnet.nl/commonsfund/eligibility/ , https://nlnet.nl/funding.html — NLnet/NGI eligibility
- https://chanzuckerberg.com/rfa/essential-open-source-software-for-science/ , https://www.renaissancephilanthropy.org/insights/open-source-for-science-fund-launches — CZI EOSS / successor
- https://www.codeforsociety.org/become-a-fiscally-sponsored-project , https://www.codeforsociety.org/fsp/faq — CS&S fiscal sponsorship
- https://blog.opencollective.com/open-collective-official-statement-ocf-dissolution/ , https://docs.oscollective.org/how-it-works/fees — Open Collective landscape
- https://www.camobilitymarketplace.org/ , https://dot.ca.gov/cal-itp , https://www.calitp.org/ , https://docs.calitp.org/benefits/ , https://compiler.la/blog/2026/remix-case-study — Cal-ITP procurement model
- https://mobilitydata.org/ , https://share.mobilitydata.org/2025-annual-report — MobilityData
- https://www.apta.com/news-research/transit-cooperative-research-program/about-tcrp/ — APTA/TCRP roles
- https://www.cisa.gov/resources-tools/resources/cisa-open-source-software-security-roadmap , https://www.congress.gov/bill/118th-congress/senate-bill/917/all-info — CISA/Securing OSS Act
- https://www.nextgov.com/people/2025/03/gsa-eliminates-18f/403400/ — 18F elimination
