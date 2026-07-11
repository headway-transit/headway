/**
 * Copy catalog: every user-facing string the frontend OWNS lives here so it
 * can be plain-language reviewed (plainlanguage.gov) and is i18n-ready.
 * Adopting a full i18n framework (react-intl / i18next) is a later increment;
 * centralizing the strings now keeps that a mechanical move.
 *
 * API error messages are NOT here on purpose: the API writes plain-language
 * errors and the UI shows them verbatim.
 */

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
    reports: "Monthly ridership",
    dq: "Data quality",
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
    summaryBlockingOpen: (count: string) => `${count} blocking open`,
    summaryWarningsOpen: (count: string) =>
      `${count} warning${count === "1" ? "" : "s"} open`,
    summaryInfoOpen: (count: string) => `${count} info open`,
    summaryResolved: (count: string) => `${count} resolved`,
    severityFilterLabel: "Show issues by severity",
    statusFilterLabel: "Show issues by status",
    filterAllSeverities: "All severities",
    filterAllStatuses: "All statuses",
    showingCount: (shown: string, total: string) =>
      `Showing ${shown} of ${total} issues. The counts above always cover the whole queue.`,
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
    } as Record<string, (value: string) => string>,
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

  simulated: {
    badge: "Simulated data",
    tooltip:
      "This number was computed from simulated test data. It must never be submitted.",
    reportBanner:
      "This report includes at least one figure computed from simulated test data. It must never be submitted.",
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
    exportCsv: "Download CSV (preview only)",
    exportFileName: (year: string, month: string) =>
      `headway-monthly-ridership-${year}-${month}-preview.csv`,
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
      /** NTD mode codes; unknown codes fall back to the raw code, honestly. */
      modeLabels: {
        MB: "Bus (MB)",
        RB: "Bus rapid transit (RB)",
        CB: "Commuter bus (CB)",
        DR: "Demand response (DR)",
        LR: "Light rail (LR)",
        HR: "Heavy rail (HR)",
        CR: "Commuter rail (CR)",
        SR: "Streetcar rail (SR)",
        YR: "Hybrid rail (YR)",
        FB: "Ferryboat (FB)",
        TB: "Trolleybus (TB)",
        VP: "Vanpool (VP)",
      } as Record<string, string>,
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
} as const;
