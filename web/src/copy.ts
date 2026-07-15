/**
 * Copy catalog: every user-facing string the frontend OWNS lives here so it
 * can be plain-language reviewed (plainlanguage.gov) and is i18n-ready.
 * Adopting a full i18n framework (react-intl / i18next) is a later increment;
 * centralizing the strings now keeps that a mechanical move.
 *
 * API error messages are NOT here on purpose: the API writes plain-language
 * errors and the UI shows them verbatim.
 */

/**
 * THE shared NTD mode-code label map (deduped 2026-07-13 — was two drifting
 * copies). Both NTD-code namespaces reference it: copy.report.mr20.modeLabels
 * uses it as-is; copy.sampling.modeLabels overrides VP to the Sampling
 * Manual's own Table 41.01 vocabulary ("Commuter vanpool"). Lookup-only in
 * both places (the selects enumerate API-served vocabularies, never this
 * map), so extra codes are harmless; unknown codes fall back to the raw
 * code, honestly. NOT for copy.safety.modeLabels — that is a different
 * namespace entirely (the transform's lowercase GTFS route_type→mode
 * vocabulary, not NTD codes).
 */
const ntdModeLabels = {
  MB: "Bus (MB)",
  RB: "Bus rapid transit (RB)",
  CB: "Commuter bus (CB)",
  TB: "Trolleybus (TB)",
  DR: "Demand response (DR)",
  VP: "Vanpool (VP)",
  LR: "Light rail (LR)",
  HR: "Heavy rail (HR)",
  CR: "Commuter rail (CR)",
  SR: "Streetcar rail (SR)",
  YR: "Hybrid rail (YR)",
  MR: "Monorail (MR)",
  AG: "Automated guideway (AG)",
  FB: "Ferryboat (FB)",
} as Record<string, string>;

export const copy = {
  appName: "Headway",
  skipToContent: "Skip to main content",
  loading: "Loading…",
  signedInAs: (username: string, roleLabel: string) =>
    `Signed in as ${username} (${roleLabel})`,
  signOut: "Sign out",

  roleLabels: {
    viewer: "viewer",
    data_steward: "data steward",
    report_preparer: "report preparer",
    certifying_official: "certifying official",
  } as Record<string, string>,

  nav: {
    dashboard: "Dashboard",
    metrics: "Metrics",
    compare: "Compare",
    reports: "Monthly ridership",
    safety: "Safety & security",
    sampling: "PMT sampling",
    dq: "Data quality",
    sandbox: "Settings sandbox",
    certify: "Certify",
    branding: "Branding",
    /** Visible signed-in AND signed-out: the public page needs no account. */
    publicData: "Public data",
    signIn: "Sign in",
  },

  theme: {
    /** The label names the action (what pressing it switches TO). */
    switchToDark: "Switch to dark theme",
    switchToLight: "Switch to light theme",
  },

  /**
   * Action-confirmation toasts (handoff 0017, design point 4): the
   * shell-wide pattern for create / supersede / certify confirmations.
   * The region is aria-live polite; messages stay until dismissed or the
   * user leaves the page (no auto-hide).
   */
  toasts: {
    regionLabel: "Action confirmations",
    dismiss: "Dismiss",
  },

  /**
   * Server CSV/XLSX exports (handoff 0017, design point 5). Both formats
   * come from ONE server-side row assembly — XLSX cells are text holding
   * the byte-identical CSV strings — and the saved file is the response
   * byte for byte. Per-surface group labels live with each surface's copy.
   */
  exports: {
    csvButton: "Download CSV",
    xlsxButton: "Download XLSX (Excel)",
    toast: (filename: string) =>
      `Download ready: ${filename}. The file holds these figures exactly as the API served them.`,
  },

  /** Breadcrumb trails on deep entities (handoff 0017, design point 4). */
  breadcrumbs: {
    label: "Breadcrumb",
  },

  /** Summary-card filter toggles (handoff 0017, design point 2). */
  summaryCards: {
    pressedHint:
      "filter on. Press again to show everything. Filtering hides nothing from these counts.",
    unpressedHint: "press to show only these",
  },

  login: {
    heading: "Sign in to Headway",
    username: "Username",
    password: "Password",
    submit: "Sign in",
    unknownRole: (role: string) =>
      `Your account has a role this version of Headway does not recognize (“${role}”). Please contact your Headway administrator.`,
  },

  /**
   * Display labels for metric codes the API serves. Labels mirror
   * services/calc/REGULATORY_TRACKER.md (the NTD/Compliance Engineer's
   * naming) — the UI never invents a regulatory definition. Unknown codes
   * fall back to the raw code, shown honestly rather than guessed at.
   */
  metricLabels: {
    vrm: "Vehicle Revenue Miles (VRM)",
    vrh: "Vehicle Revenue Hours (VRH)",
    upt: "Unlinked Passenger Trips (UPT)",
    voms: "Vehicles Operated in Maximum Service (VOMS)",
    pmt: "Passenger Miles Traveled (PMT)",
    /** Ops metrics (handoff 0014): labels mirror services/calc/
     *  OPS_DEFINITIONS.md — industry-based, never NTD concepts. */
    otp: "On-time performance (OTP)",
    headway_adherence: "Headway adherence (cvh)",
  } as Record<string, string>,

  /**
   * Display labels for unit codes the API serves. Unknown codes fall back to
   * the raw code — shown honestly, never guessed at.
   */
  unitLabels: {
    miles: "miles",
    hours: "hours",
    unlinked_passenger_trips: "unlinked passenger trips",
    vehicles: "vehicles",
    passenger_miles: "passenger miles",
    percent: "percent",
    ratio: "(a ratio)",
  } as Record<string, string>,

  metrics: {
    heading: "Computed metric values",
    tableCaption:
      "Each figure was produced by the calculation service. Headway shows it exactly as computed — this page never recalculates or edits a number.",
    preVerificationBanner:
      "Some of these numbers come from an early calculation that has not yet been checked against FTA rules. They are not certifiable figures yet. Each one is marked “Pre-verification” below.",
    preVerificationTag: "Pre-verification",
    explainLink: "How this number was made",
    empty: "No computed values yet. Values appear here after the pipeline runs.",
    certifyMoved:
      "Certification has moved to its own room. This page is for reading figures; signing them happens on the Certify page, which shows exactly what your signature would cover.",
    certifyMovedLink: "Go to the Certify page",
    columns: {
      metric: "Metric",
      unit: "Unit",
      period: "Period",
      value: "Value",
      calc: "Calculation",
      status: "Certification status",
      details: "Details",
      provenance: "Provenance",
    },
    detailToggle: (metric: string, period: string) =>
      `Calculation details for ${metric}, ${period}`,
    detailListLabel: (metric: string, period: string) =>
      `Calculation details for ${metric}, ${period}`,
    detailEmpty:
      "The calculation recorded no extra detail for this figure.",
    /** The server export of exactly this table's rows (design point 5). */
    exportLabel: "Download the computed metric values",
  },

  /**
   * The certification cockpit (/certify — handoff 0007's deferred pillar):
   * one screen showing exactly what a signature covers. Attestation is
   * informed consent: each figure is selected explicitly against its full
   * receipt, blockers and warnings are stated before the button works, and
   * the blocked-state wording mirrors the API's own 409 refusal so the
   * screen and the server tell the same story.
   */
  certify: {
    heading: "Certify figures",
    intro:
      "This page shows exactly what your signature would cover. Pick a month, read each figure's receipt, and tick the figures you are certifying. Nothing is certified until you confirm in the final step, and the API records the certification — not this page.",
    notAllowed:
      "Only a certifying official can certify figures. You can still read every figure and its receipt on the Metrics page, and review data-quality issues on the Data quality page.",
    figuresHeading: "Figures in this period",
    figuresIntro:
      "Ticking a figure means you have read its receipt and intend to put your name on it.",
    empty:
      "No figures have been computed for this period. Pick another month, or wait for the pipeline to run.",
    selectFigure: (metric: string, period: string) =>
      `Certify ${metric}, ${period}`,
    alreadyCertified: "Already certified",
    blockersHeading: "Blockers",
    blockersNone:
      "No blocking data-quality issues are open. Certification is allowed.",
    /**
     * Mirrors the API's 409 refusal (services/api routers/certify.py)
     * word for word after the lead-in, so the reason the button is off is
     * the same reason the server would give.
     */
    blockersReason: (count: string) =>
      `Certification is blocked: ${count} blocking data-quality issue(s) are still unresolved. Every blocking issue must be resolved before any figure can be certified, because certifying over a known data gap would attest to numbers we know may be wrong.`,
    blockersUnknown:
      "Headway could not load the data-quality issues, so it cannot confirm certification is allowed. Certifying is disabled until the issue list loads.",
    blockersLoading:
      "Headway is still checking for blocking data-quality issues. Certifying stays off until that check finishes.",
    reviewDqLink: "Review the data-quality issues",
    /**
     * The always-visible reason line AT the certify button (2026-07-11
     * click-through, finding 1): a certify button that will not work must
     * say why exactly where the user is looking, for EVERY disabled cause.
     * The blocked wording states the same rule as the API's 409 refusal.
     */
    reasonBlockers: (count: string) =>
      `Certification is blocked: ${count} blocking data-quality issue(s) must be resolved first.`,
    reasonBlockersLink: "View the blocking issues",
    reasonLabel: "Why the certify button is off",
    warningsHeading: "Read this before you sign",
    simulatedWarning:
      "You are about to attest to figures computed from simulated test data. Simulated figures must never be submitted to the FTA. Certifying them would put your name on numbers that do not come from real service.",
    preVerificationWarning:
      "You are about to attest to figures from an early calculation that has not yet been checked against FTA rules. They are not certifiable figures yet.",
    acknowledgeLabel:
      "I have read these warnings and I understand what certifying these figures would mean.",
    acknowledgeHint:
      "The certify button stays off until you confirm the warning above.",
    certifySelected: "Certify selected figures",
    nothingSelected:
      "Select at least one figure to certify. Use the checkbox above each receipt.",
    /** The short toast confirmation; the inline message below stays as the
     *  durable record of the identifiers. */
    certifyToast:
      "Certification recorded and audit-logged. The details are on the page.",
    certifySuccess: (
      count: number,
      certificationId: string,
      auditEventId: string,
    ) =>
      `Certification recorded for ${count} figure${count === 1 ? "" : "s"}. Certification ID ${certificationId}. Audit event ${auditEventId}. The API has audit-logged who certified and when.`,
  },

  certifyModal: {
    heading: "Certify these figures",
    intro:
      "You are about to certify the figures below. Certifying means you are formally stating these numbers are correct. Headway will record who certified, when, and your statement — this record cannot be edited later.",
    attestationLabel: "Attestation statement",
    attestationHint:
      "In your own words, state that you have reviewed these figures and believe them to be correct.",
    attestationRequired:
      "Please write an attestation statement before certifying. It is the formal record of what you are stating.",
    confirm: "Certify",
    cancel: "Cancel",
    figureSummary: (
      metric: string,
      period: string,
      value: string,
      unit: string,
      calc: string,
    ) => `${metric}, ${period}: ${value} ${unit} — calculated by ${calc}`,
  },

  lineage: {
    /** The breadcrumb's middle crumb (handoff 0017 #4). */
    crumbFigure: "Figure",
    heading: "How this number was made",
    intro:
      "This is the full trail for the selected figure: from the reported number, through each processing step (with the exact version that ran), down to the raw records Headway received. Nothing on this page is recalculated — it is the recorded history.",
    back: "Back to metrics",
    toggleInputs: (label: string) => `Inputs of ${label}`,
    madeBy: (name: string, version: string) =>
      `made by ${name} (version ${version})`,
    rawLeaf: "raw source record as received — the end of the trail",
    /** The visual lineage graph (handoff 0007, pillar 2). */
    graph: {
      viewToggleLabel: "How to show the trail",
      graphView: "Graph view",
      textView: "Text view",
      graphLabel: "Lineage graph: from the reported figure to its raw records",
      instructions:
        "Use the arrow keys to move between steps (up and down within a column, left and right between columns). Press Enter on a group to expand or collapse it.",
      tierMetric: "Reported figure",
      tierTransforms: "Processing steps",
      tierRaw: "Raw records",
      metricNode: (id: string) => `Reported figure ${id}`,
      transformNode: (name: string, version: string, produced: string) =>
        `Processing step ${name}, version ${version} — produced ${produced} record${produced === "1" ? "" : "s"} in this trail`,
      transformDetail: (version: string, produced: string) =>
        `version ${version} — ${produced} record${produced === "1" ? "" : "s"}`,
      rawGroupNode: (count: string) => `${count} raw records`,
      rawGroupHint: "Press Enter to show or hide the raw records.",
      rawNode: (id: string) => `Raw source record ${id}`,
      showMore: (shown: string, total: string) =>
        `Showing ${shown} of ${total} raw records. Show 20 more`,
    },
    kindLabels: {
      "computed.metric_values": "Reported figure",
      "canonical.vehicle_positions": "Cleaned vehicle position",
      "canonical.trips": "Cleaned trip",
      "canonical.routes": "Cleaned route",
      "raw.records": "Raw source record",
    } as Record<string, string>,
  },

  dq: {
    heading: "Data-quality issues",
    intro:
      "Every gap, conflict, or failed check in the data is listed here until a person resolves it. Issues marked “Blocking” stop certification: no figure can be certified while one is open.",
    empty: "No data-quality issues. New issues appear here as pipelines run.",
    severityLabels: {
      blocking: "Blocking",
      warning: "Warning",
      info: "Info",
    } as Record<string, string>,
    statusLabels: {
      open: "Open",
      owned: "Owned",
      resolved: "Resolved",
    } as Record<string, string>,
    /**
     * The queue-at-a-glance chips (2026-07-11 click-through, finding 2).
     * Counts are of ISSUES IN THE QUEUE — workflow tallies, not regulatory
     * figures — counted client-side from the full list GET /dq/issues
     * serves (the endpoint returns every issue; no pagination today).
     */
    summaryHeading: "Queue at a glance",
    /** Summary-card labels (handoff 0017 #2): the count is the card's big
     *  figure; severity counts cover OPEN (unresolved) issues. */
    cardLabels: {
      blocking: "Blocking open",
      warning: "Warnings open",
      info: "Info open",
      resolved: "Resolved",
    } as Record<string, string>,
    severityFilterLabel: "Show issues by severity",
    statusFilterLabel: "Show issues by status",
    filterAllSeverities: "All severities",
    filterAllStatuses: "All statuses",
    showingCount: (shown: string, total: string) =>
      `Showing ${shown} of ${total} issues. The counts above always cover the whole queue.`,
    /**
     * The render cap (2026-07-14 live click-through finding: the live queue
     * held 35,456 issues and rendering every card hung the browser). The
     * cap is STATED, never silent — no issue leaves the queue or the
     * counts; the filters narrow to what matters.
     */
    renderCap: (cap: string, matching: string) =>
      `Only the first ${cap} of ${matching} matching issues are drawn on this page — drawing them all would freeze the browser. Nothing is dropped: the counts above cover the whole queue, and the filter cards narrow the list to what you need.`,
    noMatch: (total: string) =>
      `No issues match these filters. The queue still holds ${total} issue(s) — filtering hides nothing from the counts above, and no issue is resolved by being filtered out.`,
    clearFilters: "Show all issues",
    blockingNote: "Must be resolved before any figure can be certified.",
    statusLabel: "Status",
    ownerLabel: "Owner",
    ownerUnassigned: "Not yet assigned",
    createdLabel: "Reported",
    resolvedLabel: "Resolved",
    resolutionLabel: "Resolution",
    sourceRecordsLabel: "Source records",
    resolveButton: (title: string) => `Resolve: ${title}`,
    resolutionInputLabel: "How was this issue resolved?",
    resolutionHint:
      "Describe what you checked and why the issue is settled. This note is kept permanently with the issue.",
    resolutionRequired:
      "Please describe how the issue was resolved before submitting. The note is the permanent record.",
    submitResolution: "Mark as resolved",
    cancelResolution: "Cancel",
    resolveSuccess: (title: string) => `“${title}” is now resolved.`,
    /** The optional effort field on the resolve form (docket #3). */
    minutesLabel: "Time spent resolving (minutes)",
    minutesHint:
      "Optional. A whole number of minutes, like 45. Recording it helps show the work behind data quality.",
    minutesInvalid:
      "Time spent must be a whole number of minutes (like 45), or left blank.",
    minutesSpentLabel: "Time spent resolving",
    minutesSpentValue: (minutes: string) =>
      `${minutes} minute${minutes === "1" ? "" : "s"}`,
    /**
     * The documented-effort total in the queue header. This is UI arithmetic
     * on EFFORT METADATA (minutes stewards typed into the resolve form) —
     * a workflow tally like the issue counts above it, never a reported
     * regulatory figure, which would be displayed verbatim from the API.
     */
    summaryEffort: (hours: string) =>
      `≈${hours} hours of documented data-quality work`,
  },

  /**
   * Plain-language translations of the calculation detail the API serves
   * (computed.metric_values.detail — coverage details and UPT detail, see
   * services/calc/headway_calc/types.py). The UI translates WORDING only:
   * every number and ratio below is the API's string, never recomputed.
   * Detail keys this catalog does not know are shown raw-but-tidy
   * (forward-compatible — a new key is displayed, never hidden).
   */
  detail: {
    coverage: (percent: string, excluded: string) =>
      `Covers ${percent}% of vehicle-trips; ${excluded} excluded and documented.`,
    factorApplied: (factor: string, missingTrips: string, thresholdPercent: string) =>
      `Adjusted up ×${factor} for ${missingTrips} missing trips, as federal rules allow when ${thresholdPercent}% or fewer are missing.`,
    noFactorApplied: "No adjustment factor was applied.",
    sourceMix: (parts: string) => `Where the data came from: ${parts}.`,
    sourceMixPart: (source: string, count: string) =>
      `${source} (${count} events)`,
    uptCounts: (withEvents: string, operated: string) =>
      `Passenger counts were recorded on ${withEvents} of ${operated} operated trips.`,
    known: {
      total_groups: (n: string) => `Vehicle-trip groups in this period: ${n}.`,
      clean_position_share: (p: string) =>
        `${p}% of location reports belong to fully covered trips.`,
      gap_threshold_seconds: (n: string) =>
        `A trip was set aside when its location reports had a gap longer than ${n} seconds.`,
      coverage_threshold: (p: string) =>
        `This figure is only produced when coverage is at least ${p}%.`,
      layover_max_seconds: (n: string) =>
        `Waiting time between trips was counted up to ${n} seconds per wait.`,
      total_trips: (n: string) => `Trips in this period: ${n}.`,
      trips_excised: (n: string) =>
        `Trips set aside because of gaps in their location data: ${n}.`,
      blocks_touched: (n: string) =>
        `Vehicle work blocks affected by a set-aside trip: ${n}.`,
      layover_intervals_dropped: (n: string) =>
        `Between-trip waits not counted because a neighboring trip was set aside: ${n}.`,
      total_boardings_counted: (n: string) =>
        `Passenger boardings counted from the data: ${n}.`,
      operated_trips: (n: string) => `Trips operated in this period: ${n}.`,
      trips_with_events: (n: string) =>
        `Trips with passenger-count data: ${n}.`,
      missing_trips: (n: string) =>
        `Trips with no passenger-count data: ${n}.`,
      missing_share: (p: string) =>
        `${p}% of operated trips had no passenger counts.`,
      missing_trip_threshold: (p: string) =>
        `Federal rules allow adjusting for missing trips when ${p}% or fewer are missing.`,
      imbalance_threshold: (p: string) =>
        `Boarding and alighting counts are flagged for review when they differ by more than ${p}%.`,
      /** ---- ops detail vocabulary (handoff 0014): otp_v0 ---- */
      on_time_count: (n: string) =>
        `Observed passages on time (inside the configured window): ${n}.`,
      early_count: (n: string) =>
        `Observed passages earlier than the early tolerance: ${n}.`,
      late_count: (n: string) =>
        `Observed passages later than the late tolerance: ${n}.`,
      passages_considered: (n: string) =>
        `Observed passages with a usable scheduled time: ${n}.`,
      passages_unscheduled: (n: string) =>
        `Passages whose schedule row carries no time (counted, never interpolated): ${n}.`,
      deviation_mean_seconds: (n: string) =>
        `Average deviation from schedule: ${n} seconds (positive means later than scheduled).`,
      deviation_median_seconds: (n: string) =>
        `Median deviation from schedule: ${n} seconds.`,
      early_tolerance_seconds: (n: string) =>
        `Early tolerance: a passage up to ${n} seconds early counts as on time (a per-agency setting with recorded provenance).`,
      late_tolerance_seconds: (n: string) =>
        `Late tolerance: a passage up to ${n} seconds late counts as on time (a per-agency setting with recorded provenance).`,
      agency_timezone: (v: string) =>
        `Schedule times are anchored to the feed-declared agency timezone: ${v}.`,
      /** ---- ops detail vocabulary: headway_adherence_v0 (cvh) ---- */
      pairs_counted: (n: string) =>
        `Consecutive observed headway pairs measured: ${n}.`,
      stops_covered: (n: string) =>
        `Stops covered by at least one measured pair: ${n}.`,
      routes_covered: (n: string) => `Routes covered: ${n}.`,
      pairs_excluded_unscheduled: (n: string) =>
        `Pairs left out because one member has no scheduled time (counted, never silent): ${n}.`,
      pairs_excluded_inverted: (n: string) =>
        `Pairs left out for a non-positive headway (overtaking or a duplicate passage): ${n}.`,
      pairs_excluded_over_cap: (n: string) =>
        `Pairs left out because the scheduled headway exceeds the cap — a service gap, not a headway: ${n}.`,
      mean_scheduled_headway_seconds: (n: string) =>
        `Average scheduled headway across measured pairs: ${n} seconds.`,
      stddev_deviation_seconds: (n: string) =>
        `Spread of headway deviations (population standard deviation): ${n} seconds.`,
      max_scheduled_headway_seconds: (n: string) =>
        `Scheduled-headway cap for a usable pair: ${n} seconds.`,
    } as Record<string, (value: string) => string>,
    /**
     * The passage-derivation accounting every ops figure carries
     * (detail.derivation — the cadence evidence behind the number, handoff
     * 0014 design point 3). Refusals are the loud part: every count the
     * derivation refused is shown, never hidden. All numbers verbatim.
     */
    derivation: {
      method: (name: string, version: string) =>
        `Observed stop passages were derived by ${name} ${version} — a Headway-owned, versioned derivation (services/calc/OPS_DEFINITIONS.md).`,
      positions: (considered: string, deduplicated: string) =>
        `Vehicle position reports considered: ${considered} (${deduplicated} repeated reports collapsed).`,
      occurrences: (n: string, skipped: string, min: string) =>
        `Vehicle-trip runs observed: ${n} (${skipped} skipped with fewer than ${min} position reports).`,
      trips: (observed: string, unscheduled: string) =>
        `Trips observed: ${observed}; ${unscheduled} had no matching schedule (counted, never guessed).`,
      derived: (derived: string, considered: string) =>
        `Passages derived: ${derived} of ${considered} scheduled stop events considered.`,
      refusedNotReached: (n: string, radius: string) =>
        `${n} passages refused: the vehicle was never observed within ${radius} meters of the stop.`,
      refusedEndpoint: (n: string) =>
        `${n} passages refused: the closest approach was at the edge of the observed window, so the true passage may lie outside it.`,
      refusedCadenceGap: (n: string, gap: string) =>
        `${n} passages refused: cadence too sparse — position reports around the stop were more than ${gap} seconds apart.`,
    },
  },

  /**
   * The Receipt (handoff 0007, pillar 1): every displayed figure opens into
   * a five-part receipt — plain-language story, coverage meter with
   * exclusions, the verbatim FTA rule, flags, and the door to raw records.
   */
  receipt: {
    label: (metric: string, period: string) =>
      `Receipt for ${metric}, ${period}`,
    /** The plain-language story line. Every number in it is the API's string verbatim. */
    story: (value: string, unit: string, metric: string, period: string) =>
      `${value} ${unit} — ${metric}, ${period}.`,
    coverageHeading: "How complete is the data",
    coverageMeterLabel: (metric: string, period: string) =>
      `Data coverage for ${metric}, ${period}`,
    coverageNotReported:
      "The calculation reported no coverage information for this figure.",
    ruleHeading: "The FTA rule inside this number",
    ruleIntro: (calcName: string) =>
      `The federal definitions verified for the ${calcName} calculation, quoted word for word from the manual:`,
    ruleMissing: (calcName: string) =>
      `No verified FTA quote is on file for the ${calcName} calculation. This figure cannot yet be traced to a verified federal definition — treat it as unverified.`,
    flagsHeading: "Flags on this figure",
    noFlags: "No flags. This figure carries no warnings.",
    preVerificationNote:
      "This number comes from an early calculation that has not yet been checked against FTA rules. It is not a certifiable figure yet.",
    anomalyFlag: "Anomaly flagged",
    anomalyNote:
      "The calculation flagged something unusual about this figure. Review the details above before trusting it.",
    walkLink: "Walk this number to its raw records",
  },

  /**
   * Operations metrics (handoff 0014): the honesty boundary in the UI.
   * Every `category === "ops"` figure carries the badge, its receipt cites
   * an INDUSTRY basis (verbatim TCQSM quotes) plus explicitly Headway-owned
   * definitions — never an FTA manual — and nothing here is certifiable.
   */
  ops: {
    /** The badge, verbatim per the handoff — everywhere an ops figure shows. */
    badge: "Operations metric — not an NTD reported figure",
    badgeTooltip:
      "This number measures how the service ran. It is not a federal reporting figure: it can never be certified, never enters an NTD report or package, and its receipt cites an industry basis, not an FTA manual.",
    receipt: {
      basisHeading: "The industry basis inside this number",
      verifiedIntro: (calcName: string) =>
        `The industry definitions verified for the ${calcName} calculation, quoted word for word from the published manual cited below:`,
      basisMissing: (calcName: string) =>
        `No verified industry quote is on file for the ${calcName} calculation. Regenerate the quotes (npm run extract:quotes) — an operations figure must not ship without its basis.`,
      ownedHeading: "Headway's own definitions in this number",
      ownedIntro:
        "These are Headway's own operational definitions — versioned formulas we publish and stand behind. They are not federal rules and not industry quotes:",
      ownedLabel: "Headway-owned definition",
      ownedName: (name: string, version: string) => `${name} ${version}`,
      formulaLabel: (name: string) => `Formula for ${name}`,
      ownedReference: (path: string) =>
        `The full method, and the measured basis for every tolerance, is recorded in ${path}.`,
    },
    dashboard: {
      heading: "Operations metrics",
      intro:
        "How the service actually ran, measured from vehicle positions against the schedule. These are operations figures with an industry basis — never NTD reported figures: they cannot be certified and never enter a report package or the public certified feed.",
      agencyScope: "All routes (agency-wide)",
      routeScope: (routeId: string) => `Route ${routeId}`,
      /** The refusal accounting is shown on the card, never hidden. */
      refusalsHeading: "Refused by the derivation (counted per reason)",
      columns: {
        scope: "Route",
        value: "Value",
        provenance: "Provenance",
      },
      empty:
        "No operations metrics have been computed yet. They appear here after an ops run (they are computed separately from NTD figures).",
      otp: {
        heading: "On-time performance (OTP) by route",
        description:
          "The percent of observed stop passages inside the configured on-time window, exactly as the otp_v0 calculation computed it. The chart tracks the agency-wide figure over time; the table lists every route-level figure.",
        agencyStat: (value: string) =>
          `${value}% of observed passages were on time, agency-wide.`,
        breakdown: (onTime: string, early: string, late: string) =>
          `On time ${onTime} · early ${early} · late ${late} observed passages.`,
        windowLine: (early: string, late: string) =>
          `The window: up to ${early} seconds early to ${late} seconds late counts as on time (per-agency settings; the TCQSM basis is quoted in the figure's receipt).`,
        tableCaption:
          "Route-level on-time performance, exactly as computed. Values are percents.",
        empty: "No on-time performance figures have been computed yet.",
      },
      cvh: {
        heading: "Headway adherence (cvh) by route",
        description:
          "The coefficient of variation of headway deviations, exactly as the headway_adherence_v0 calculation computed it: the spread of observed-minus-scheduled headways divided by the average scheduled headway. Lower is steadier. Headway serves the number, never a grade — the formula and its industry basis are in the figure's receipt.",
        agencyStat: (value: string) =>
          `Agency-wide headway adherence (cvh): ${value}.`,
        formulaReference:
          "cvh = population standard deviation of (observed − scheduled headway) ÷ mean scheduled headway — the full definition is in services/calc/OPS_DEFINITIONS.md.",
        exclusions: (inverted: string, overCap: string, unscheduled: string) =>
          `Pairs left out and counted: ${inverted} non-positive (overtaking or duplicates) · ${overCap} over the scheduled-headway cap · ${unscheduled} without a scheduled time.`,
        tableCaption:
          "Route-level headway adherence (cvh), exactly as computed. Lower is steadier.",
        empty: "No headway adherence figures have been computed yet.",
      },
    },
  },

  simulated: {
    badge: "Simulated data",
    tooltip:
      "This number was computed from simulated test data. It must never be submitted.",
    reportBanner:
      "This report includes at least one figure computed from simulated test data. It must never be submitted.",
  },

  /**
   * Demand Response scope surfacing (handoff 0013, design point 5): the one
   * DR-specific affordance — the mode/TOS badge and the rule callouts on
   * receipts. These lead-ins are plain-language framing ONLY; the rules
   * themselves are always the verbatim tracker quotes placed right under
   * them (src/regulatory/drRules.ts + quotes.json), never a paraphrase
   * standing alone.
   */
  dr: {
    /** The mode badge on every DR-scoped figure. */
    modeBadge: "Demand response (DR)",
    /** The TOS badge when the scope covers the whole mode, not one TOS. */
    allTosBadge: "All types of service",
    /** Plain-language lead-ins for each rule callout, by drRules key. */
    calloutIntro: {
      txOnboard:
        "Taxi (TX) service counts only the time and distance with a passenger onboard. Waiting, empty travel between passengers, and no-show visits add nothing to this figure:",
      noDeadhead:
        "Travel without passengers to or from the garage or dispatching point (deadhead) is never reported for this type of service:",
      noShowRevenue:
        "A no-show still counts in this figure — driving to the pickup is revenue service even when the passenger never boards:",
      vomsAtypical:
        "Unlike the fleet-wide vehicle count, the demand response count includes atypical days:",
    } as Record<string, string>,
  },

  report: {
    heading: "Monthly ridership report",
    intro:
      "The vehicle miles, vehicle hours, and passenger trips Headway computed for one calendar month, shown exactly as computed — this page never recalculates or edits a number.",
    disclaimer:
      "Preview only. The official NTD Monthly Ridership submission format has not yet been verified against FTA's reporting system documentation.",
    monthLabel: "Month",
    yearLabel: "Year",
    monthNames: [
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December",
    ],
    tableCaption: (monthName: string, year: string) =>
      `Figures for ${monthName} ${year}, exactly as the calculation service computed them.`,
    columns: {
      metric: "Metric",
      value: "Value",
      unit: "Unit",
      calc: "Calculation",
      status: "Certification status",
      coverage: "How complete is the data",
      details: "Details",
      provenance: "Provenance",
    },
    noFigure: (metric: string) =>
      `No ${metric} figure has been computed for this month.`,
    coverageNotReported: "Not reported",
    /**
     * The server export replacing the retired client-side CSV assembly
     * (2026-07-14): same disclaimer-first file, now built by the API. The
     * note states the two differences OUT LOUD — extra columns and a wider
     * row set — because what users download must never change silently.
     */
    export: {
      label: "Download this month's computed figures",
      note:
        "The file is served by the API and covers every figure computed for this month — including any beyond the three ridership metrics shown above — with each figure's scope, category, and provenance id, and the preview disclaimer first.",
    },
    /**
     * The MR-20 package section (docket #2): a rendering of GET
     * /reports/mr20. Everything regulatory in it — the banner, the citation,
     * the caveats, every value and null-reason — is the API's text VERBATIM;
     * this catalog only holds the frame around it.
     */
    mr20: {
      sectionToggleLabel: "Report section",
      previewTab: "Monthly ridership preview",
      mr20Tab: "MR-20 package",
      heading: "MR-20 package",
      intro:
        "The Monthly Ridership (MR-20) figures assembled for this month, exactly as the API packaged them: fleet totals and one row per mode. Nothing here is recalculated, and the package says itself whether it may be reported.",
      tableCaption: (monthName: string, year: string) =>
        `MR-20 package for ${monthName} ${year}: fleet and per-mode figures, exactly as packaged by the API.`,
      columns: {
        mode: "Mode",
      },
      fleetRow: "Fleet (all modes)",
      /** NTD mode codes — the shared ntdModeLabels map (top of this file);
       *  unknown codes fall back to the raw code, honestly. */
      modeLabels: ntdModeLabels,
      /** Plain-language labels for cell flags; unknown flags shown raw. */
      flagLabels: {
        pending_d2: "Pending D-2",
      } as Record<string, string>,
      flagNotes: {
        pending_d2:
          "This rail figure is on hold until the D-2 form definition is verified.",
      } as Record<string, string>,
      cellCoverage: (percent: string) => `Coverage ${percent}%`,
      /** Fallback only — the API normally states a reason for a null cell. */
      noReason: "Not reported. The package gave no reason.",
      cellMissing: "Not included in this package.",
      caveatsToggle: (count: string) =>
        `Caveats (${count}) — read these before using the package`,
      download: "Download package (JSON)",
      /** The saved file is the fetched response, byte for byte. */
      downloadFileName: (month: string) => `headway-mr20-${month}.json`,
      /** The server CSV/XLSX export of the same package (design point 5):
       *  banner and caveats lead the file, values verbatim. */
      exportLabel: "Download the MR-20 package as a spreadsheet",
    },
  },

  /**
   * The public open-data page (/public — 2026-07-11 click-through, finding
   * 3): a human-readable rendering of GET /public/metrics/certified, the one
   * deliberately unauthenticated endpoint (handoff 0006, design point 8).
   * Every figure is the API's string verbatim; simulated flags are shown,
   * never stripped — transparency shows the flags, it never hides them.
   */
  publicData: {
    heading: "Public data: certified figures",
    intro:
      "These are the figures this agency's certifying official has attested to. Each number is shown exactly as it was certified — this page never recalculates or edits a figure, and anyone can read it without signing in.",
    /** The permanent disclaimer: rendered on every visit, empty state included. */
    disclaimer:
      "This page is the agency's public courtesy copy of its certified figures. It is not the official federal record: the agency's official submissions are filed with the Federal Transit Administration. Any figure computed from simulated test data is labeled below — the label is never removed.",
    empty:
      "No figures have been certified yet. Figures appear here as soon as the agency's certifying official attests to them.",
    machineReadable: "Machine-readable version of this data (JSON)",
    periodLabel: "Period",
    certifiedOnLabel: "Certified on",
    statusCertified: "Certified",
    calcLine: (name: string, version: string) =>
      `Calculated by ${name} (version ${version}).`,
    cardLabel: (metric: string, period: string) =>
      `Certified figure: ${metric}, ${period}`,
  },

  errors: {
    regionLabel: "Error",
  },

  /**
   * The comparison surface (/compare — handoff 0017, design point 1).
   * Every figure is the API's string verbatim, every cell opens the same
   * Receipt as every other surface, and every delta is SERVER-computed and
   * described sign-neutrally — a difference is a difference, not a win —
   * unless the metric's registry direction defines better/worse (coverage
   * only today).
   */
  compare: {
    heading: "Compare figures",
    intro:
      "Put two to four versions of the same figure side by side — different calculation versions of one period, or one calculation across periods. Every number is shown exactly as computed, every cell opens the figure's full receipt, and a difference is described as a difference, not as better or worse, unless the metric itself defines a direction.",
    loading: "Loading the figures available to compare…",
    empty:
      "No computed figures are available to compare yet. Figures appear here after the pipeline runs.",
    pickerHeading: "What to compare",
    metricLabel: "Which figure?",
    metricUnselected: "Choose a figure",
    modeLabel: "Compare across",
    modeVersions: "Calculation versions (one period)",
    modePeriods: "Periods (one calculation)",
    periodLabel: "Which period?",
    periodUnselected: "Choose a period",
    calcLabel: "Which calculation?",
    calcUnselected: "Choose a calculation",
    comparandsVersionsLabel: "Which calculation versions? Pick two to four.",
    comparandsPeriodsLabel: "Which periods? Pick two to four.",
    baselineHint:
      "The first comparand you tick is the baseline the others are measured against.",
    run: "Compare",
    reasonLabel: "Why the compare button is off",
    reasonCount: "Pick at least two and at most four comparands to compare.",
    comparing: "Comparing…",
    baselineTag: "Baseline",
    cardsHeading: "Side by side",
    cardLabel: (comparand: string) => `Comparison card for ${comparand}`,
    vsBaseline: "the baseline",
    vsPrevious: "the previous comparand",
    perModeHeading: "By mode",
    noFleetFigure: "No agency-wide figure in this comparand.",
    matrixHeading: "Detail matrix",
    matrixCaption: (metric: string) =>
      `${metric} by scope and comparand, exactly as computed. Each cell's button opens the figure's full receipt; each difference is against the baseline column.`,
    scopeColumn: "Scope",
    /** Scope display labels; unknown scopes fall back to the raw string. */
    scopeLabels: {
      agency: "Agency-wide",
      fleet: "Fleet (all modes)",
    } as Record<string, string>,
    modeScope: (modeLabel: string) => `Mode: ${modeLabel}`,
    cellReceipt: (metric: string, scope: string, comparand: string) =>
      `Receipt for ${metric}, ${scope}, ${comparand}`,
    receiptModalHeading: "Receipt",
    closeReceipt: "Close the receipt",
    cellMissing: "No figure.",
    /** Certified-vs-uncertified comparisons label BOTH (binding rule). */
    mixedBanner:
      "This comparison puts certified and uncertified figures side by side. Every figure carries its own certification status label — read them before drawing conclusions.",
    delta: {
      noChange: (versus: string) => `no change from ${versus}`,
      more: (magnitude: string, versus: string) =>
        `${magnitude} more than ${versus}`,
      less: (magnitude: string, versus: string) =>
        `${magnitude} less than ${versus}`,
      notComparable: (versus: string) => `No comparison against ${versus}.`,
      /** Only for registry-directed metrics — never color alone. */
      judgement: {
        better: "better",
        worse: "worse",
      },
    },
  },

  /**
   * The settings sandbox (/sandbox — handoff 0017, design point 6). The
   * HARD WALLS, restated where the user reads: a preview changes nothing,
   * is never certifiable, and applying a real change lives only in the
   * separate audited settings flow — this page has no apply button by
   * design. Every previewed figure and difference is computed by the
   * deterministic calculation runner and shown verbatim.
   */
  sandbox: {
    heading: "Settings sandbox",
    /** The prominent changes-nothing statement, on every visit. */
    banner:
      "Modeling preview — changes nothing. Figures on this page are what-if previews computed under proposed settings. They can never be certified, never enter a report package or the public feed, and nothing on this page changes any setting or any recorded figure.",
    intro:
      "Try a settings change before anyone makes it: propose new values for the calculation knobs below, pick a period, and Headway's deterministic calculation runner recomputes that period's figures under the proposed settings as a preview. The arithmetic is the calculation library's — never this page's.",
    applyNote:
      "Nothing here applies a change. Actually changing a setting happens only in Headway's separate, audited settings flow: a certifying official updates the setting, the change is audit-logged with who changed it and when, and the calculation runner reads the new value on its next real run. This page has no apply button on purpose.",
    settingsHeading: "Settings to model",
    settingsIntro:
      "Today's values come from the agency's recorded settings, shown exactly as stored. Propose a new value for at least one; leave the others blank to keep them as they are.",
    settingsLoading: "Loading the current settings…",
    settingsError:
      "Headway could not load the current settings, so the sandbox cannot state what today's values are. The error above says what the server reported.",
    noKnobs:
      "None of the calculation settings this sandbox models are present in the agency's settings. There is nothing to preview.",
    currentValue: (value: string) => `Today's value: ${value}`,
    proposedLabel: (key: string) => `Proposed value for ${key}`,
    descriptionToggle: "What this setting does",
    periodHeading: "Period to preview",
    run: "Run the preview",
    running: "Running the preview…",
    reasonLabel: "Why the preview button is off",
    reasonNothingProposed:
      "Propose a new value for at least one setting — a preview with nothing changed would only restate today's figures.",
    reasonPeriodMissing:
      "Pick the period to preview — both the from and the to date.",
    previewDone:
      "Preview computed. Nothing was changed — the impact rail below shows what would change.",
    railHeading: "What would change",
    railIntro:
      "Both columns below were computed fresh for this preview over the same recorded data: one under today's audited settings, one under your proposed values. Every figure and every difference is the deterministic calculation library's — never this page's — and none of it was stored anywhere.",
    railCaption: (periodStart: string, periodEnd: string) =>
      `Figures previewed for ${periodStart} to ${periodEnd}.`,
    previewTag: "Preview — changes nothing",
    /** Section headings: the ntd/ops split mirrors the honesty boundary. */
    ntdHeading: "NTD figures (what-if)",
    opsHeading: "Operations metrics (what-if)",
    columns: {
      figure: "Figure",
      current: "Under today's settings",
      preview: "Under the proposed settings",
      change: "Difference",
    },
    /** A refusing variant is a stated result; its findings are listed. */
    previewRefused:
      "The calculation refused to produce this figure — its reasons are listed below, word for word.",
    settingUsedLine: (key: string, current: string, proposed: string) =>
      `${key}: ${current} today → ${proposed} proposed`,
    inputsLine: (parts: string) =>
      `Rows the preview read (workflow counts): ${parts}.`,
    versus: "today's figure",
  },

  /**
   * The /dashboard view (handoff 0008, pillar B). Every figure shown in a
   * tile, tooltip, label, or table is the API's string VERBATIM — chart
   * geometry scales, displayed figures are never recomputed. Axis tick
   * values are chart scaffolding (scale annotations this UI draws), never
   * reported figures.
   */
  dashboard: {
    heading: "Dashboard",
    intro:
      "The agency's computed figures at a glance. Every number here is shown exactly as the calculation service computed it — the charts scale the picture, never the figures.",
    empty:
      "No computed values yet. Charts appear here after the pipeline runs.",
    tilesHeading: "Latest certified figures",
    tilesIntro:
      "The most recent figure of each kind that a certifying official has attested to.",
    noCertified: "No certified figure yet",
    noCertifiedDetail: (metric: string) =>
      `No ${metric} figure has been certified. Figures appear here once the certifying official attests to one.`,
    tileCertifiedTag: "Certified",
    tilePeriod: (start: string, end: string) => `${start} to ${end}`,
    explainLink: "How this number was made",
    /** Chart / table view toggle — the table is the WCAG-clean equivalent. */
    viewToggleLabel: (chart: string) => `How to show ${chart}`,
    chartView: "Chart",
    tableView: "Table",
    chartReaderHint:
      "Use the left and right arrow keys to read each point; the table view lists every value.",
    upt: {
      heading: "Unlinked passenger trips over time",
      description:
        "One point per reporting period, exactly as computed by the UPT calculation.",
      empty: "No UPT figures have been computed yet.",
      tableCaption:
        "Unlinked passenger trips per reporting period, exactly as computed.",
    },
    service: {
      heading: "Vehicle revenue miles and hours over time",
      description:
        "Two panels on separate scales — miles and hours are different units, so they are never drawn on one plot.",
      vrmPanel: "Vehicle Revenue Miles (VRM)",
      vrhPanel: "Vehicle Revenue Hours (VRH)",
      empty: "No VRM or VRH figures have been computed yet.",
      tableCaption:
        "Vehicle revenue miles and hours per reporting period, exactly as computed.",
      notComputed: "Not computed",
    },
    coverage: {
      heading: "Data coverage over time",
      description:
        "How complete the location data behind each VRM and VRH figure was, from each figure's calculation detail.",
      thresholdLabel: (percent: string) => `Coverage threshold (${percent}%)`,
      empty:
        "No coverage information has been reported yet. Coverage appears with figures from calculation version 0.2.0 onward.",
      tableCaption:
        "Data coverage per reporting period, from each figure's calculation detail.",
      notReported: "Not reported",
      seriesVrm: "VRM coverage",
      seriesVrh: "VRH coverage",
    },
    dq: {
      heading: "Unresolved data-quality issues by severity",
      description:
        "Counts of issues in the queue (workflow tallies, not regulatory figures). Blocking issues stop certification.",
      empty: "No unresolved data-quality issues. The queue is clear.",
      tableCaption:
        "Unresolved data-quality issues by workflow status and severity.",
      statusLabels: {
        open: "Open",
        owned: "Owned",
      } as Record<string, string>,
      segmentLabel: (severity: string, count: string, status: string) =>
        `${severity}: ${count} ${status} issue${count === "1" ? "" : "s"}`,
      totalColumn: "Total",
      goToQueue: "Go to the data-quality queue",
    },
    columns: {
      period: "Period",
      value: "Value",
      unit: "Unit",
      provenance: "Provenance",
      status: "Status",
    },
    pointLabel: (period: string, entries: string) => `${period}: ${entries}`,
    /**
     * The one filter row above the charts (dataviz interaction.md: filters
     * sit in a single row above everything they scope, and every chart and
     * table below re-renders against the same slice). Bucketing is date math
     * on period boundaries; figures are NEVER added together in the browser
     * (see src/reports/granularity.ts).
     */
    filters: {
      rowLabel: "Filter the charts",
      fromLabel: "From date",
      toLabel: "To date",
      granularityLabel: "Show periods as",
      granularityOptions: {
        hourly: "Hourly",
        daily: "Daily",
        weekly: "Weekly",
        monthly: "Monthly",
        quarterly: "Quarterly",
      } as Record<string, string>,
      /**
       * The honest coarse-bucket note: when the reported periods do not line
       * up with the selected granularity, the chart shows every reported
       * period as-is. Summing them client-side would invent a figure nobody
       * computed or certified — so Headway never does.
       */
      asReported: (count: string, granularityLabel: string) =>
        `Showing ${count} period${count === "1" ? "" : "s"} as reported. The reported periods do not line up with ${granularityLabel.toLowerCase()} periods, and Headway never adds figures together in the browser.`,
      /**
       * The DQ card obeys the same date slice as every chart below the
       * filter row, but an issue outside the range is never made to look
       * resolved or gone: the held-back count is always stated.
       */
      dqOutsideRange: (count: string) =>
        `${count} unresolved issue${count === "1" ? " falls" : "s fall"} outside the selected dates. The queue still holds ${count === "1" ? "it" : "them"} — go to the data-quality queue for the full list.`,
    },
  },

  /**
   * The branding settings page (/settings/branding — handoff 0008, pillar
   * C). The server is the accessibility gate: a brand color that fails WCAG
   * AA against the app surfaces is refused with a plain-language 422, and
   * this page surfaces that refusal VERBATIM.
   */
  branding: {
    heading: "Agency branding",
    intro:
      "Set the agency's display name, brand colors, and logo. Headway checks every color against its surfaces: a color that would not be readable is refused, with the measured contrast in the message. You can brand it; you cannot brand it unreadable.",
    notAllowed:
      "Only a certifying official can change the agency's branding. The current branding is applied across the app for everyone.",
    loadError:
      "Headway could not load the current branding. The form below starts from the defaults.",
    displayNameHeading: "Display name",
    displayNameLabel: "Agency display name",
    displayNameHint:
      "Shown in the app header in place of “Headway” for everyone who uses this instance.",
    saveDisplayName: "Save display name",
    displayNameSaved: (name: string) =>
      `Display name saved. The header now shows “${name}”.`,
    primaryLabel: "Primary brand color",
    accentLabel: "Accent brand color",
    colorHexLabel: (colorName: string) => `${colorName} (hex value)`,
    colorHint:
      "A six-digit hex color, for example #1a5fb4. Headway refuses colors that lack readable contrast against its surfaces.",
    saveColor: (colorName: string) => `Save ${colorName.toLowerCase()}`,
    colorSaved: (colorName: string, value: string) =>
      `${colorName} saved: ${value}.`,
    previewHeading: "Live preview",
    previewIntro:
      "How the header chrome would look with the values above. Saving is what makes it real — and the server, not this preview, decides whether a color is readable enough.",
    previewChartNote:
      "Charts keep their own validated palette: brand colors change the chrome, never the data encodings.",
    /** Branding v2 (handoff 0017, design point 7): the known per-mode
     *  limitation, stated where branding is edited — never silent. */
    chromeDarkNote:
      "Themed nav chrome follows the same per-mode rule: a chrome theme applies only in the mode whose readability check it passed. A theme with no dark variant keeps the neutral Headway chrome in dark mode.",
    previewSampleLink: "Sample link",
    previewSampleButton: "Sample action",
    logoHeading: "Agency logo",
    logoHint:
      "SVG or PNG, at most 512 KiB. The logo appears in the app header next to the display name.",
    logoLabel: "Logo file",
    uploadLogo: "Upload logo",
    logoNone: "No logo has been uploaded yet.",
    logoPresent: "A logo is uploaded and shown in the header.",
    logoUploaded: (bytes: string) =>
      `Logo uploaded (${bytes} bytes). It now appears in the header.`,
    logoAlt: (displayName: string) => `${displayName} logo`,
    chooseFileFirst: "Choose an SVG or PNG file first, then upload it.",
  },

  /**
   * The Safety & Security module (/safety — handoff 0010, design point 5).
   * Questions are plain language ("Was anyone taken directly from the scene
   * for medical care?", never "injury threshold"); the federal rule itself
   * is ALWAYS the verbatim tracker quote (src/regulatory/quotes.json,
   * sscls_v0) with its page citation — hints below only point at the rule
   * (manual + page), they never restate a regulatory definition from memory.
   * The classifier's verdict and explanation are the API's, shown verbatim:
   * this page never decides how an event classifies.
   */
  safety: {
    heading: "Safety & security",
    /**
     * Headway's canonical mode vocabulary (the transform's GTFS
     * route_type→mode map, services/transform gtfs_static.py — the SAME
     * vocabulary the sscls_v0 classifier's rail test uses). Plain labels;
     * an unknown code falls back to the raw code, honestly.
     *
     * Deliberately SEPARATE from the shared ntdModeLabels map (top of this
     * file): these are lowercase transform-vocabulary codes, not NTD codes.
     */
    modeLabels: {
      bus: "Bus",
      trolleybus: "Trolleybus",
      tram: "Tram, streetcar, or light rail",
      subway: "Subway or metro",
      rail: "Rail (commuter or intercity)",
      ferry: "Ferry",
      cable_tram: "Cable tram",
      aerial_lift: "Aerial lift (gondola or cable car)",
      funicular: "Funicular",
      monorail: "Monorail",
    } as Record<string, string>,
    intro:
      "Record safety and security events here, in plain language. Headway's deterministic classifier decides how each event classifies under the federal thresholds — never this page — and the deadlines panel tracks the reports each event puts on the calendar.",
    /** Honest scope (handoff 0010, design point 6): stated on every visit. */
    alphaBanner:
      "Alpha preview — not certified for submission. Headway records and classifies events but does not e-file anything: the NTD portal's filing format has not been verified. Commuter Rail and Alaska Railroad reporting nuances beyond the manual's Exhibit 1 are flagged in output, never silently applied. File your official reports with the FTA as you do today.",

    deadlines: {
      heading: "Reporting deadlines",
      intro:
        "Due dates computed by the API from the recorded events and the manual's timing rules. The days-remaining wording is this page's calendar arithmetic on those served dates.",
      loading: "Loading deadlines…",
      ss40Heading: "S&S-40 major event reports",
      ss40Intro:
        "One report per major event. The manual's timing rule, word for word:",
      ss40None:
        "No S&S-40 report is currently due. An S&S-40 appears here for every recorded major event.",
      ss40Item: (eventLabel: string, dueDate: string) =>
        `S&S-40 for ${eventLabel} — due ${dueDate}`,
      ss50Heading: "S&S-50 monthly summaries",
      ss50Intro:
        "One summary per mode and type of service, every month — a month with no events still owes its summary. The manual's rule, word for word:",
      ss50None:
        "No S&S-50 summary is currently listed. Monthly summaries appear here as reporting months close.",
      ss50MonthLine: (monthName: string, dueDate: string) =>
        `S&S-50 for ${monthName} — due ${dueDate}`,
      ss50ZeroModes: (count: string) =>
        `includes ${count} mode${count === "1" ? "" : "s"} with zero events`,
      ss50ModeCount: (count: string) =>
        `${count} non-major event${count === "1" ? "" : "s"}`,
      ss50ModeZero: "0 events — the summary is still due",
      /** The server CSV/XLSX export of the month's S&S-50 package
       *  (handoff 0017, design point 5). */
      ss50ExportLabel: (monthName: string) =>
        `Download the S&S-50 summary for ${monthName}`,
      ss50ExportNote:
        "The file is the API's S&S-50 preview package for this month: one row per mode and type of service, explicit zero-event rows included, with its not-reportable banner, citations, and excluded-event accounting first.",
      /** Urgency summary cards = filter toggles (handoff 0017 #2). Counts
       *  are workflow tallies of listed deadlines, never figures. */
      summaryLabel: "Deadlines at a glance — filter by urgency",
      urgencyCardLabels: {
        overdue: "Overdue",
        "due-soon": "Due within 7 days",
        upcoming: "Due later",
      } as Record<string, string>,
      filteredNote: (count: string) =>
        `${count} deadline${count === "1" ? " is" : "s are"} outside the pressed urgency filter — out of view here, never off the calendar. Press the card again to show everything.`,
      /** Urgency wording: text + icon + color, never color alone. */
      dueToday: "Due today",
      dueIn: (days: string) =>
        `Due in ${days} day${days === "1" ? "" : "s"}`,
      overdueBy: (days: string) =>
        `Overdue by ${days} day${days === "1" ? "" : "s"}`,
      /** The quote lookup failing is stated, never papered over. */
      ruleMissing:
        "The verified manual quote for this timing rule is not on file. Regenerate the quotes (npm run extract:quotes) — the rule must ship with the deadline.",
    },

    form: {
      heading: "Record an event",
      intro:
        "Answer what you know, in plain words. Recording an event creates Headway's permanent record and classifies it immediately — nothing is filed with the FTA from here.",
      notAllowed:
        "Only a data steward or above can record or correct safety events. You can still read every recorded event, its classification, and the deadlines on this page.",
      correctionHeading: (eventLabel: string) => `Correct: ${eventLabel}`,
      correctionIntro:
        "A correction never edits or deletes the original record. Headway records a new event with your corrected answers and links the two, so the audit trail keeps both.",
      occurredAt: "When did the event happen?",
      mode: "Which mode of service was involved?",
      modeUnselected: "Choose a mode",
      modeHint:
        "If more than one mode was involved, report the event in one mode per the manual's Predominant Use Rule (2026 S&S Policy Manual, p. 15): a rail mode wins over a non-rail mode; otherwise pick the mode that carried more passengers.",
      typeOfService: "Who operates this service?",
      typeOfServiceOptions: {
        "": "Not stated",
        DO: "The agency itself (directly operated)",
        PT: "A contractor (purchased transportation)",
      } as Record<string, string>,
      category: "What kind of event was it?",
      categoryUnselected: "Choose a category",
      /** Manual vocabulary (handoff 0010 schema enum), plain labels. */
      categoryLabels: {
        collision: "Collision",
        derailment: "Derailment",
        fire: "Fire",
        evacuation: "Evacuation",
        security: "Security event",
        assault: "Assault",
        cyber: "Cyber security event",
        other: "Something else",
      } as Record<string, string>,
      cyberHint:
        "Unauthorized access that disrupts operations can be a Cyber Security Major Event (2026 S&S Policy Manual, Scenario G, p. 19).",
      narrative: "Describe what happened",
      narrativeHint:
        "In your own words. The narrative is part of the permanent record.",
      location: "Where did it happen? (optional)",
      fatalities: "How many people died?",
      fatalitiesHint:
        "Count deaths confirmed within 30 days of the event, including suicides (Exhibit 5, p. 16). Do not count deaths from illness, overdose, or natural causes; a death of undetermined cause in a rail right-of-way that may be from collision or electrocution does count (p. 20). Enter 0 if no one died.",
      injuries:
        "Was anyone taken directly from the scene for medical care? How many people?",
      injuriesHint:
        "Count each person transported away from the scene for medical attention — by ambulance, transit or private vehicle, or stretcher — whether or not they appeared injured (p. 21). Do not count transport solely for illness, natural causes, exposure, intoxication, overdose, or an unrelated mental-health evaluation, or care sought later (p. 22). Enter 0 if no one was.",
      propertyDamage: "Estimated property damage, in dollars (optional)",
      propertyDamageHint:
        "Your best estimate as a plain amount, like 30000 or 30000.50. Sum the damage to ALL vehicles and property involved or affected — transit and non-transit — plus the cost of clearing wreckage (p. 25). Leave blank if not yet assessed: unknown damage is never treated as $0.",
      towed: "Was a vehicle towed away from the scene?",
      towedHint:
        "Any vehicle, transit or not. For a non-rail collision involving a transit revenue vehicle, a tow-away alone makes the event reportable; for a rail collision it indicates substantial damage (p. 17, p. 27).",
      evacuationLifeSafety: "Did people evacuate for life-safety reasons?",
      assaultOnWorker: "Was a transit worker assaulted?",
      assaultOnWorkerHint:
        "Answer yes even if no one was hurt — the manual's rule for assaults on transit workers is quoted on the classification (S&S-50 scope, p. 3).",
      involvesTransitVehicle: "Did the event involve a transit vehicle?",
      involvesTransitVehicleHint:
        "Answer yes whether or not the vehicle was in service at the time (p. 18).",
      /** Rail-only questions: disclosed only when the picked mode is rail. */
      railHeading: "Rail-only questions",
      railIntro:
        "These apply because the mode you picked is a rail mode. They come from the rail rows of Exhibit 5 (p. 16) and the rail rules on p. 17 of the 2026 S&S Policy Manual.",
      seriousInjury:
        "Did anyone have a serious injury under the rail criteria?",
      seriousInjuryHint:
        "The rail criteria (p. 21): hospitalization over 48 hours within 7 days; a broken bone (except simple fractures of fingers, toes, or the nose); severe bleeding or nerve, muscle, or tendon damage; internal organ injury; or serious burns. Answer yes even if the person was not transported from the scene — the verbatim rule is quoted on the classification.",
      substantialDamage: "Was a rail vehicle substantially damaged?",
      substantialDamageHint:
        "Substantial damage (p. 25) disrupts operations AND affects the vehicle enough that towing, rescue, on-site maintenance, or immediate removal is required. Do not count cracked windows; dents, bends, or small punctures; broken lights or mirrors; or a vehicle leaving under its own power for minor repair.",
      involvesSecondRailVehicle: "Was a second rail vehicle involved?",
      involvesSecondRailVehicleHint:
        "A collision between two rail vehicles is automatically reportable (p. 17).",
      gradeCrossing: "Did it happen at a grade crossing?",
      runawayTrain: "Did a rail vehicle move on its own (a runaway)?",
      runawayTrainHint:
        "Uncommanded, uncontrolled, or unmanned movement of a revenue rail vehicle — an incapacitated, sleeping, or absent operator, or an electrical, mechanical, or software failure — on the mainline, in a yard, or in a shop (p. 17).",
      evacuationToRailRow:
        "Did people evacuate onto the rail right-of-way?",
      evacuationToRailRowHint:
        "Evacuation to the controlled rail right-of-way counts, whether transit-directed or self-directed. Evacuation to a platform does not count unless it was for life safety (p. 17).",
      /** The supersede body's required audit reason. */
      reason: "Why is this entry being corrected?",
      reasonHint:
        "Kept permanently in the audit log next to both records. The original entry is never edited — this explains why the new one replaces it.",
      submit: "Record this event",
      submitCorrection: "Record the correction",
      cancelCorrection: "Cancel the correction",
      /** Client-side validation mirrors the API contract; the API's own
          refusals are still shown verbatim when they arrive. */
      validationHeading:
        "The event was not recorded. Fix the following and try again:",
      occurredAtRequired: "Enter when the event happened.",
      modeRequired: "Pick which mode of service was involved.",
      categoryRequired: "Pick what kind of event it was.",
      narrativeRequired: "Describe what happened — the narrative is required.",
      reasonRequired:
        "Say why this entry is being corrected — the reason is the permanent audit record.",
      countInvalid: (question: string) =>
        `“${question}” needs a whole number, 0 or more.`,
      damageInvalid:
        "Property damage must be a plain dollar amount, like 30000 or 30000.50 — or left blank.",
      recorded: (classificationLabel: string) =>
        `The event is recorded. The classifier's verdict: ${classificationLabel}. The full receipt is below.`,
      correctionRecorded: (classificationLabel: string) =>
        `The correction is recorded and the original is marked as corrected — both stay in the record. The new verdict: ${classificationLabel}.`,
    },

    classification: {
      /** Verdict labels; an unknown value falls back to the raw code. */
      labels: {
        major: "Major event",
        non_major: "Non-major event",
        not_reportable: "Not reportable",
      } as Record<string, string>,
      receiptLabel: (eventLabel: string) =>
        `Classification receipt for ${eventLabel}`,
      /** `classifier` is the API's combined name+version string
       *  ("sscls_v0 0.1.0"), displayed VERBATIM — never split or parsed. */
      decidedBy: (classifier: string) =>
        `Decided by classifier ${classifier} — deterministic, versioned calculation code. Neither this page nor an AI classifies events.`,
      /** A record with no classification on file is a LOUD condition. */
      missing:
        "No classification is on file for this event. That is a gap, not a verdict — do not treat the event as not reportable.",
      explanationHeading: "The classifier's explanation",
      thresholdsHeading: "Federal thresholds this event meets",
      thresholdsNone:
        "The classifier reported no federal major-event threshold met by this event.",
      nonMajorBasisHeading: "Why this belongs on the S&S-50 monthly summary",
      /**
       * Plain-language labels for the classifier's thresholds_met tokens
       * (threshold_id values in services/calc/headway_calc/sscls.py).
       * Unknown tokens are shown raw and loudly — never hidden.
       */
      thresholdLabels: {
        fatality: "A death",
        injury_immediate_transport:
          "Someone was taken directly from the scene for medical care",
        property_damage_25k:
          "Property damage at or over the federal threshold",
        injury_two_or_more:
          "Two or more people were taken directly from the scene for medical care",
        rail_serious_injury: "A serious injury under the rail criteria",
        rail_substantial_damage: "Substantial damage to a rail vehicle",
        rail_to_rail_collision: "A collision between rail vehicles",
        rail_collision_grade_crossing:
          "A rail collision at a grade crossing or intersection",
        rail_collision_vehicle_contact_assault:
          "An assault or homicide involving contact with a rail transit vehicle",
        collision_towaway:
          "A collision with a transit revenue vehicle where a vehicle was towed away",
        derailment: "A derailment",
        runaway_train: "A runaway train",
        evacuation_life_safety: "An evacuation for life safety",
        rail_evacuation_to_row: "An evacuation onto the rail right-of-way",
        cyber_substantial_damage:
          "A cyber security event that disrupted operations",
      } as Record<string, string>,
      thresholdUnknown: (token: string) =>
        `The classifier reported a threshold this version of Headway does not label yet (“${token}”). It is shown raw so nothing is hidden.`,
      quoteMissing: (token: string) =>
        `No verified manual quote is mapped to “${token}” yet. The threshold stands — the missing rule text is a gap in this page's mapping, stated rather than papered over.`,
      oneReportNote:
        "An event that meets one or more thresholds is one reportable event — thresholds never multiply reports (2026 S&S Policy Manual, p. 14).",
      /** Classifier notes that are not thresholds (e.g. Scenario E's
       *  assault-with-vehicle-contact-is-a-collision rule). */
      notesHeading: "The classifier also noted",
    },

    events: {
      heading: "Recorded events",
      /** Classification summary cards = filter toggles (handoff 0017 #2).
       *  Counts are workflow tallies of UNSUPERSEDED events. */
      summaryLabel: "Events at a glance — filter by classification",
      showingCount: (shown: string, total: string) =>
        `Showing ${shown} of ${total} recorded events. An event with no classification on file always stays visible, and no event leaves the record by being filtered out.`,
      clearFilter: "Show all events",
      loading: "Loading events…",
      empty:
        "No events recorded yet. Events appear here as they are recorded — and they stay here permanently: corrections add a new record instead of changing an old one.",
      /** "Collision on 2026-07-02 (Bus)" — heading + accessible names. */
      eventLabel: (category: string, date: string, mode: string) =>
        `${category} on ${date} (${mode})`,
      occurredLabel: "Happened",
      modeLabel: "Mode",
      typeOfServiceLabel: "Operated by",
      locationLabel: "Location",
      fatalitiesLabel: "Deaths",
      injuriesLabel: "People taken directly from the scene for medical care",
      damageLabel: "Estimated property damage",
      damageValue: (amount: string) => `$${amount}`,
      circumstancesLabel: "Circumstances",
      /** Yes-answers listed as short phrases; unanswered = not listed. */
      circumstances: {
        towed: "a vehicle was towed from the scene",
        evacuation_life_safety: "people evacuated for life safety",
        assault_on_worker: "a transit worker was assaulted",
        involves_transit_vehicle: "a transit vehicle was involved",
        involves_second_rail_vehicle: "a second rail vehicle was involved",
        grade_crossing: "it happened at a grade crossing",
        serious_injury: "someone had a serious injury under the rail criteria",
        substantial_damage: "a rail vehicle was substantially damaged",
        runaway_train: "a rail vehicle moved on its own (runaway)",
        evacuation_to_rail_row:
          "people evacuated onto the rail right-of-way",
      } as Record<string, string>,
      enteredLine: (by: string, at: string) => `Recorded by ${by} at ${at}`,
      receiptToggle: (eventLabel: string) =>
        `Why this classification — ${eventLabel}`,
      correctButton: (eventLabel: string) => `Correct this event: ${eventLabel}`,
      /** The audit story: the original stays visible, struck and linked. */
      supersededTag: "Corrected — see the replacement",
      supersededNote:
        "This record was corrected. It stays visible so the audit trail is complete; the replacement record is the one that counts.",
      supersededLink: (eventLabel: string) =>
        `Go to the correction of ${eventLabel}`,
      supersededBy: (id: string) => `Corrected by event ${id}`,
    },
  },

  /**
   * The PMT sampling module (/sampling — handoff 0012, design point 3).
   * Every regulatory rule shown is either the VERBATIM tracker quote
   * (src/regulatory/quotes.json: sampling_v0 / pmt_v0) with its citation,
   * or the API's own regulatory text (eligibility guidance, table-cell
   * citations, undersampling/oversampling citations, the estimate's
   * method label, citations, and caveats) rendered verbatim — never a
   * paraphrase presented as a quotation. Every sample size, count, ratio,
   * and estimate displayed is the API's own figure (sampling_v0,
   * deterministic calc code), shown verbatim: this page never computes a
   * sample size or an estimate.
   */
  sampling: {
    heading: "PMT sampling",
    intro:
      "For agencies that cannot count passenger miles on every trip: plan a ready-to-use sample from the FTA's NTD Sampling Manual, draw each period's units at random, hand the worksheet to a ride checker, record what they measured, and let Headway's deterministic calculation produce the estimate. Every size and figure on this page comes from that calculation — never from this page and never from an AI.",
    /** Honest scope (handoff 0012, design point 4): stated on every visit. */
    alphaBanner:
      "Alpha preview — not certified for submission. Headway covers the ready-to-use plans end to end for the averaging (APTL) option without route grouping. Base-option plans can be recorded, drawn, and measured, but their estimation (Sampling Manual Section 70) is deferred; the route-grouping option is reference-only. Template plans built from your own past samples (Section 50) are not mechanized, and certification of a custom technique by a qualified statistician (§57) is your agency's own workflow — Headway records plans and estimates but certifies nothing. Estimates here are sampled estimates, never computed passenger-mile figures.",

    optionsLoading: "Loading the sampling vocabulary…",
    optionsError:
      "Headway could not load the sampling vocabulary from the server. The plan wizard needs it, so planning is unavailable — the error above says what the server reported.",

    /** The shared ntdModeLabels map (top of this file) with ONE override:
     *  the Sampling Manual's Table 41.01 calls VP "Commuter vanpool" (its
     *  ready-to-use plans cover commuter vanpools only — §41.05(a)), so this
     *  page speaks that manual's vocabulary. The API serves which modes the
     *  table covers; this map only labels the served codes. */
    modeLabels: {
      ...ntdModeLabels,
      VP: "Commuter vanpool (VP)",
    } as Record<string, string>,
    unitLabels: {
      vehicle_days: "Vehicle-days",
      one_way_trips: "One-way trips",
      round_trips: "Round trips",
      one_way_car_trips: "One-way car trips",
      one_way_train_trips: "One-way train trips",
    } as Record<string, string>,
    optionLabels: {
      aptl: "Averaging option (APTL, without route grouping)",
      aptl_grouped: "Averaging option with route grouping",
      base: "Base option",
    } as Record<string, string>,
    frequencyLabels: {
      quarterly: "Quarterly",
      monthly: "Monthly",
      weekly: "Weekly",
    } as Record<string, string>,
    tosLabels: {
      DO: "The agency itself (directly operated, DO)",
      PT: "A contractor (purchased transportation, PT)",
    } as Record<string, string>,
    statusLabels: {
      created: "No sample drawn yet",
      active: "Sampling under way",
    } as Record<string, string>,
    /** "2026 — Bus (MB), one-way trips — Averaging option …, monthly" */
    planLabel: (
      reportYear: string,
      modeLabel: string,
      unitLabel: string,
      optionLabel: string,
      frequencyLabel: string,
    ) =>
      `${reportYear} — ${modeLabel}, ${unitLabel.toLowerCase()} — ${optionLabel}, ${frequencyLabel.toLowerCase()}`,

    wizard: {
      heading: "Plan a sample",
      intro:
        "Answer six questions and Headway's calculation looks up the required per-period and annual sample sizes, verbatim from the manual's tables. Nothing is estimated here — this step only fixes the plan you will sample under.",
      notAllowed:
        "Only a data steward or above can create sampling plans, draw period samples, or record measurements. You can still read every plan, worksheet, and progress meter on this page.",
      eligibilityHeading: "Is a ready-to-use plan right for your agency?",
      /** The API's guidance strings are rendered verbatim below this. */
      eligibilityIntro:
        "The calculation's own guidance, word for word — the manual's eligibility conditions (§41.01) and reuse limits (§41.03) are quoted inside it:",
      reportYear: "Which NTD report year is this plan for?",
      reportYearHint:
        "The report year the sample covers. Sampling must meet the FTA floor for each mode and type of service in the year it is reported.",
      mode: "Which mode are you sampling?",
      modeUnselected: "Choose a mode",
      tos: "Who operates this service?",
      tosUnselected: "Choose who operates it",
      unit: "What is one sampled unit of service?",
      unitUnselected: "Choose a unit",
      unitHint:
        "The manual fixes the unit per mode (NTD Sampling Manual, Table 41.01) — only the units the table allows for your mode are offered, exactly as the calculation serves them.",
      option: "How will you measure and estimate?",
      /** The manual's §41.07(c) options, quoted below the radios. */
      optionsRuleIntro:
        "The manual's own words for the three options, word for word:",
      optionAptlExplanation:
        "Ride checkers count boardings and passenger miles on a smaller sample, and the estimate combines the sample's average passenger trip length with your complete boarding count. This option REQUIRES a 100% count of unlinked passenger trips (every boarding, all year) — pick it only if your agency counts every boarding.",
      optionBaseExplanation:
        "Ride checkers count boardings and passenger miles on a larger sample, and both figures are estimated from the sample alone. No 100% boarding count is needed, but the required samples are the largest — and Headway v0 can record a Base plan, its draws, and its measurements, but cannot yet run the Base-option estimate (Sampling Manual Section 70 is deferred; the estimate button will say so).",
      optionGroupedExplanation:
        "Bus routes are split into two groups by route length and each group is sampled and estimated separately, which can shrink the total sample. Not available yet: Headway v0 does not mechanize per-group sampling or the grouped estimate, so this option cannot be picked — its table cells remain readable for reference.",
      frequency: "How often will you sample?",
      frequencyUnselected: "Choose a frequency",
      frequencyHint:
        "Ready-to-use plans spread the sample across the year — quarterly, monthly, or weekly. The manual's required sizes differ by frequency, so the calculation needs your choice to look up the right table cell.",
      submit: "Create this plan",
      validationHeading:
        "The plan was not created. Fix the following and try again:",
      reportYearInvalid:
        "Enter the NTD report year as a four-digit year, like 2026.",
      modeRequired: "Pick which mode you are sampling.",
      tosRequired: "Pick who operates this service.",
      unitRequired: "Pick what one sampled unit of service is.",
      frequencyRequired: "Pick how often you will sample.",
      created: (annual: string) =>
        `The plan is created. Required sample size, from the manual's table: ${annual} units for the year. The full plan receipt is below.`,
    },

    /** The plan receipt: the required sizes with their table citation. */
    planReceipt: {
      label: (planLabel: string) => `Plan receipt for ${planLabel}`,
      /** The wizard's copy of the receipt: a DISTINCT accessible name, so
       *  the two landmarks (here and on the plan card) stay unique. */
      newLabel: (planLabel: string) => `New plan receipt for ${planLabel}`,
      requiredLine: (annual: string) =>
        `Required sample size: ${annual} units for the year.`,
      perPeriodLine: (perPeriod: string, frequencyLabel: string) =>
        `${perPeriod} units per ${frequencyLabel.toLowerCase()} period — both sizes are the manual's own table rows, never derived from each other.`,
      citationIntro:
        "Where these sizes come from, as cited by the calculation:",
      lookedUpBy: (selectorVersion: string) =>
        `Sizes looked up by ${selectorVersion} — deterministic, versioned calculation code. Neither this page nor an AI computes a required sample size.`,
      guidanceHeading: "Guidance from the calculation, word for word",
      floorIntro:
        "The estimation floor the ready-to-use plans are designed to meet (2026 NTD Policy Manual, p. 149), word for word:",
    },

    plans: {
      heading: "Sampling plans",
      /** The in-row progress bar (handoff 0017, design point 3): value +
       *  label text first, bar as the visual echo — never bar-alone. */
      rowMeterLabel: (planLabel: string) =>
        `Sampling progress for ${planLabel}`,
      readyTag: "Ready to estimate",
      loading: "Loading sampling plans…",
      empty:
        "No sampling plans yet. Create one above — the plan fixes the unit, option, frequency, and required sample sizes before any unit is drawn.",
      statusUnknown: (status: string) =>
        `This plan has a status this version of Headway does not label yet (\u201c${status}\u201d). It is shown raw so nothing is hidden.`,
      createdLine: (by: string, at: string) => `Created by ${by} at ${at}`,
      detailError: (message: string) =>
        `Headway could not load this plan's draws, measurements, or progress: ${message}`,
    },

    draw: {
      heading: "Draw a period's sample",
      intro:
        "One draw per period, at the plan's frequency. List every service unit you expect to operate in the period — trippers, shuttles, and special operations included — and Headway's deterministic drawer selects the required number at random, without replacement. The seed is recorded so the same list and seed always reproduce the same sample.",
      periodLabel: "Which period is this draw for?",
      periodHint:
        "Name the period at the plan's frequency, for example 2026-Q1, 2026-01, or 2026-W14. Each period is drawn exactly once.",
      unitsLabel: "Service units expected this period (one per line)",
      unitsHint:
        "The list must cover the period's entire expected service — a unit left out can never be selected, which breaks the randomness the manual requires. Qualify unit ids with their period or date (for example 2026-01-15/trip-5012) so an id never repeats across periods.",
      seedLabel: "Random seed (optional)",
      seedHint:
        "Leave blank and Headway generates one from a cryptographic randomness source. If you provide your own, use at least 8 characters. Either way the seed is recorded with the draw, so anyone can re-run it and get the same sample.",
      oversampleLabel: "Extra units to draw beyond the required size (optional)",
      oversampleHint:
        "Oversampling is allowed only when the extra units are selected randomly — Headway draws them from the same seeded random order and flags them on the draw record. Leave 0 to draw exactly the required per-period size.",
      submit: "Draw this period's sample",
      validationHeading:
        "The sample was not drawn. Fix the following and try again:",
      periodRequired: "Name which period this draw is for.",
      unitsRequired:
        "List at least one service unit for the period — one per line.",
      seedTooShort:
        "A seed you provide yourself needs at least 8 characters — or leave it blank and Headway generates one.",
      oversampleInvalid:
        "Extra units must be a whole number, 0 or more.",
      drawn: (count: string, period: string) =>
        `The sample for ${period} is drawn: ${count} units were selected at random, without replacement. The worksheet is below.`,
      /** The drawer's documented procedure (DrawCreated.method), verbatim. */
      methodIntro:
        "How the drawer selected this list — the recorded procedure, word for word:",
    },

    worksheet: {
      heading: (period: string) => `Ride-checker worksheet — ${period}`,
      intro:
        "Hand this list to the ride checker. Each selected unit needs its boardings (UPT) and passenger miles (PMT) measured on board.",
      printButton: "Print the worksheets",
      seedLine: (seed: string) =>
        `Random seed recorded for reproducibility: ${seed}`,
      frameLine: (frame: string) =>
        `Drawn from the period's full list of ${frame} service units.`,
      oversampleLine: (count: string) =>
        `Includes ${count} randomly drawn extra unit(s) beyond the required size (flagged on the draw record).`,
      ruleIntro:
        "How this list was selected — the manual's rule, word for word:",
      columns: {
        position: "Draw order",
        unit: "Service unit",
        upt: "Boardings observed (UPT)",
        pmt: "Passenger miles observed (PMT)",
        recorded: "Recorded",
      },
      notMeasured: "Not yet measured",
      measuredLine: (by: string, at: string) => `${by}, ${at}`,
      /** The server CSV/XLSX export of the plan's worksheet (handoff 0017,
       *  design point 5): every drawn unit across the plan's draws with
       *  its measured state, the requirement and retention note first. */
      exportLabel: (planLabel: string) =>
        `Download the worksheet for ${planLabel}`,
      drawnLine: (by: string, at: string, version: string) =>
        `Drawn by ${by} at ${at} using ${version}.`,
    },

    measure: {
      heading: "Record a measurement",
      intro:
        "Enter what the ride checker observed on one selected unit: the boardings counted and the passenger miles measured. Every drawn unit must be measured — the progress meter below tracks how far along the sample is.",
      unitLabel: "Which selected unit was measured?",
      unitUnselected: "Choose a selected unit",
      allMeasured:
        "Every drawn unit has a recorded observation. Draw the next period when its service list is ready.",
      uptLabel: "Boardings observed (UPT)",
      uptHint:
        "A whole number of boardings the checker counted on this unit.",
      pmtLabel: "Passenger miles observed (PMT)",
      pmtHint:
        "The passenger miles measured on this unit, like 128.4. Entered by hand from the ride check — the estimate will say so.",
      dayTypeLabel: "What type of service day was it? (optional)",
      dayTypeUnselected: "Not recorded",
      dayTypeHint:
        "Weekday, Saturday, or Sunday. Only needed if you later want estimates broken out by type of service day.",
      dateLabel: "When was the ride check performed? (optional)",
      notesLabel: "Notes (optional)",
      submit: "Record this measurement",
      validationHeading:
        "The measurement was not recorded. Fix the following and try again:",
      unitRequired: "Pick which selected unit was measured.",
      uptInvalid: "Boardings observed needs a whole number, 0 or more.",
      pmtInvalid:
        "Passenger miles observed must be a plain number, like 128.4.",
      recorded: (unitId: string) =>
        `Measurement recorded for ${unitId}. The progress meter below is updated from the record.`,
      progressHeading: "Sample progress",
      /** API-served workflow counts, shown beside the meter. */
      progressLine: (measured: string, required: string) =>
        `${measured} of ${required} required units measured.`,
      meterLabel: (planLabel: string) => `Measured units for ${planLabel}`,
      perDrawLine: (period: string, measured: string, selected: string) =>
        `${period}: ${measured} of ${selected} drawn units measured`,
      /** The API's no-undersampling citation is rendered verbatim below. */
      underTargetIntro:
        "The sample is below its required size. Why an estimate cannot be made yet, in the API's own words:",
      /** The API's oversampling citation is rendered verbatim below. */
      oversampledIntro:
        "More units are measured than the plan requires. The rule that makes that acceptable, in the API's own words:",
    },

    estimate: {
      heading: "Run the estimate",
      intro:
        "When every required unit is measured, Headway's deterministic calculation expands the sample to an annual passenger-mile estimate: your 100% boarding count \u00d7 the sample's average passenger trip length. This page only asks for the input — the arithmetic is the calculation's, never the browser's.",
      notAllowed:
        "Only a report preparer or above can run the estimate. The plan, worksheets, and progress stay readable here, and measurements can still be recorded by a data steward.",
      expansionLabel: "Annual 100% boarding count (UPT)",
      expansionHint:
        "The averaging option's expansion factor is your complete unlinked-passenger-trips count for the year (NTD Sampling Manual \u00a783.01) \u2014 the 100% count the option requires. Use the agency's computed UPT figure, exactly as reported; the estimate's caveats say Headway does not cross-check it in v0.",
      submit: "Run the estimate",
      /** The always-visible reason line AT the button (house pattern). */
      reasonLabel: "Why the estimate button is off",
      reasonBase:
        "The estimate is off because this is a Base-option plan: Base-option estimation (Sampling Manual Section 70) is deferred in this version of Headway. The plan's draws and measurements stay on file for when it lands.",
      reasonUnderTarget: (measured: string, required: string) =>
        `The estimate is off because only ${measured} of ${required} required units are measured. The manual does not allow estimating from an under-target sample \u2014 the rule is stated above the meter, in the API's own words.`,
      reasonExpansionMissing:
        "The estimate is off until you enter the annual 100% boarding count \u2014 the averaging option cannot expand a sample without it.",
      expansionInvalid:
        "The annual 100% boarding count must be a plain number, like 12750000.",
      done: "The estimate is computed. The receipt is below.",

      receipt: {
        label: (planLabel: string) => `Estimate receipt for ${planLabel}`,
        /** The provenance tag — a sampled ESTIMATE, never computed PMT. */
        estimateTag: "Sampled estimate",
        estimateLine: (value: string) =>
          `${value} passenger miles (annual, sampled estimate).`,
        distinctNote:
          "This is a sampled estimate with estimation provenance. It is not a computed passenger-miles figure, it is never shown as one, and it is not stored among Headway's computed figures.",
        methodIntro:
          "The calculation's own provenance label, word for word:",
        componentsHeading: "How the estimate was put together",
        expansionTerm:
          "100% boarding count (the expansion factor, \u00a783.01)",
        aptlTerm:
          "Sample average passenger trip length (sample APTL, \u00a783.05)",
        sampleUptTerm: "Sample total boardings (UPT)",
        samplePmtTerm: "Sample total passenger miles (PMT)",
        unitsTerm: "Units measured, of required",
        unitsValue: (measured: string, required: string) =>
          `${measured} of ${required}`,
        oversampleTerm: "Measured beyond the required size",
        oversampleValue: (count: string) =>
          `${count} unit(s) \u2014 acceptable only because the extra units were drawn randomly (see the caveats below)`,
        expansionRuleIntro:
          "The expansion-factor rule (\u00a783.01), word for word:",
        ratioRuleIntro:
          "How the sample APTL must be formed \u2014 a ratio of totals, never an average of per-unit ratios (\u00a783.05), word for word:",
        multiplyRuleIntro:
          "How the annual estimate is formed (\u00a783.07), word for word:",
        byDayHeading: "Estimates by type of service day",
        byDayBlockLabel: (scope: string) => `${scope} estimate`,
        citationsHeading: "Citations from the calculation",
        caveatsHeading: "Read this before using the estimate",
      },
    },

    /** The quote lookup failing is stated, never papered over. */
    ruleMissing:
      "The verified manual quote for this rule is not on file. Regenerate the quotes (npm run extract:quotes) \u2014 the rule must ship with this screen.",
  },
} as const;
