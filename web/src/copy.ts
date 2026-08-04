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
    // Named explicitly rather than left to the `?? session.role` fallback in
    // Layout.tsx. "auditor" happens to read correctly as a bare enum string;
    // the next role added might not, and would reach a user looking like
    // `certifying_official` (handoff 0047).
    auditor: "auditor",
  } as Record<string, string>,

  nav: {
    today: "Today",
    map: "Live map",
    dashboard: "Dashboard",
    metrics: "Metrics",
    /** The calculations room (handoff 0026): plain words, not "calc runs".
     *  Linked for data_steward+ (UX; the API enforces the role on POST). */
    calcRuns: "Compute figures",
    compare: "Compare",
    reports: "Monthly ridership",
    safety: "Safety & security",
    sampling: "PMT sampling",
    dq: "Data quality",
    /** The revenue review queue (handoff 0040): every signed-in role can
     *  read it; classifying is data-steward-grade (UX only — the API
     *  enforces the role on the classify call). */
    revenueReview: "Boardings to review",
    sandbox: "Settings sandbox",
    attestations: "Attestations",
    certifications: "Certifications",
    certify: "Certify",
    /** The reviewer's own room (handoff 0047): shown to read-only roles,
     *  who land there instead of /today. Any signed-in role may open it —
     *  it is composed entirely of reads the API already allows everyone. */
    review: "Review",
    /** The admin hub (handoff 0025): certifying official only (UX; the API
     *  enforces the role on every admin call). */
    admin: "Admin",
    /** Visible signed-in AND signed-out: the public page needs no account. */
    publicData: "Public data",
    signIn: "Sign in",
  },

  /**
   * THE CONTROL-ROOM SHELL (handoff 0044, outputs 1 and 5).
   *
   * A compact command bar — brand, agency, the room you are in, and an "as
   * computed" run stamp — over ONE dense navigation row. The long tail of
   * rooms sits in named groups rather than in a command palette: the
   * handoff's open question weighed a palette against grouped menus for an
   * audience one week into Linux, and grouped menus won on discoverability.
   *
   * Every group is a real disclosure button (aria-expanded + aria-controls)
   * over a list of ordinary links, so the keyboard path is the same one
   * everything else in this app uses.
   */
  shell: {
    /** The room you are in, named in the bar (screen-reader prefix only —
     *  sighted users read the page's own h1). */
    contextLabel: "Current page",
    /** Named groups for the navigation tail. */
    groups: {
      reports: "Reports",
      records: "Records",
      tools: "Tools",
    } as Record<string, string>,
    groupHint: (group: string) => `${group} pages`,
    groupCurrentHint: (group: string) =>
      `${group} pages, and the page you are on is in this group`,
    /**
     * The "as computed" stamp: the newest calculation run on record, read
     * from GET /calc-runs. It is a STAMP, never a figure — it says when
     * this installation last computed, and says plainly when it cannot
     * tell rather than showing a comforting blank.
     */
    stamp: {
      label: "As computed",
      checking: "reading the run record…",
      /** No run has ever been recorded on this installation. */
      none: "no calculation run on record",
      /** A run is queued or running right now. */
      inProgress: "a calculation run is in progress",
      /** The run record could not be read — said, never hidden. */
      unavailable: "run record unavailable",
      /** Accessible description of the whole stamp. */
      describe: (state: string) => `Last calculation run: ${state}`,
      statusLabels: {
        succeeded: "succeeded",
        refused: "refused",
        failed: "failed",
        running: "running",
        queued: "queued",
      } as Record<string, string>,
    },
  },

  /**
   * Progressive disclosure (handoff 0044, output 5).
   *
   * The rule this app follows: an EXPLANATION may fold away behind a
   * closed-by-default disclosure — it is never shortened when it moves —
   * but an ADMISSION never folds. A refusal, a held or excluded count, a
   * cap, a staleness warning, a scope receipt, an "operations metrics are
   * not an NTD reported figure" boundary: those stay on screen at all
   * times, whatever is open or closed.
   */
  disclosure: {
    what: "What this shows",
    how: "How this works",
    /** Screen-reader suffix so the control's purpose is never ambiguous. */
    expandHint: (label: string) => `${label} — full explanation`,
  },

  /**
   * THE PROVENANCE TERMINAL (handoff 0044, output 4).
   *
   * A dense, monospace stream of what this installation actually did.
   * EVERY ROW IS A REAL RECORDED EVENT, read from endpoints that already
   * exist: GET /calc-runs (runs and their per-figure outcomes) and
   * GET /dq/issues (findings raised). Nothing here is synthesised, and no
   * decorative tick is ever emitted to make the panel look busy — when
   * there is nothing on record the panel says so.
   *
   * A row says WHAT HAPPENED. It never says a figure is good or bad: a
   * computed figure carries the neutral rail, and the semantic ok/watch/
   * alert set is used only where the platform itself assigned a severity.
   */
  terminal: {
    heading: "Provenance terminal",
    live: "Live",
    /** The cadence, labelled (handoff 0044 open question: v0 POLLS the
     *  existing endpoints and says how often, rather than adding a
     *  streaming surface before the composition is proven). */
    cadence: (seconds: string) =>
      `Polls the calculation-run and data-quality records every ${seconds} seconds.`,
    sources: "Every line is an event Headway recorded — a calculation run, a figure computed or refused, or a finding raised. Nothing on this panel is generated to fill space.",
    loading: "Reading the event record…",
    /** The honest empty state: no invented activity, ever. */
    empty:
      "No events on record yet. Headway would rather show an empty stream than invent activity — the first calculation run or data-quality finding appears here.",
    error: (message: string) =>
      `The event record could not be read: ${message}`,
    /** Row tags — the word carries the meaning; the rail only echoes it. */
    tags: {
      computed: "COMPUTED",
      refused: "REFUSED",
      raised: "RAISED",
      failed: "FAILED",
      running: "RUNNING",
      queued: "QUEUED",
      stale: "STALE",
    } as Record<string, string>,
    /** Row messages. Ids and figures are the server's strings, verbatim. */
    rows: {
      figureComputed: (metric: string, scope: string, value: string) =>
        `${metric} · ${scope} · ${value}`,
      figureRefused: (metric: string, scope: string, blocking: string) =>
        `${metric} · ${scope} · refused over ${blocking} blocking finding${blocking === "1" ? "" : "s"}`,
      runFinished: (period: string, persisted: string, refused: string) =>
        `run ${period} · ${persisted} computed, ${refused} refused`,
      runFailed: (period: string, error: string) =>
        `run ${period} · ${error}`,
      runOpen: (period: string) => `run ${period}`,
      runStale: (period: string) =>
        `run ${period} · state unknown past the staleness bound`,
      findingRaised: (severity: string, title: string) =>
        `${severity} · ${title}`,
    },
    /** Column headers for the readable table equivalent of the stream. */
    columns: {
      time: "Time",
      event: "Event",
      kind: "Kind",
    },
    /** The stream is capped so the panel stays readable — cap stated. */
    cap: (cap: string) =>
      `The newest ${cap} events are shown. Older events stay on their own pages: the calculation runs room and the data-quality queue.`,
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
    /* Single sign-on (handoff 0046). The provider is whatever the agency
       configured — Entra ID, Google, Okta or Keycloak — so nothing here
       names one or draws its logo, and no wording implies a particular
       product. The words ON the button are the administrator's own
       (`button_label`); `button` below is only the fallback for an
       installation that left them blank, and it matches the server's own
       default so the two never disagree. */
    sso: {
      button: "Sign in with single sign-on",
      /* The break-glass promise, restated where someone would need it. */
      hint: "Your Headway username and password above always work too, whether or not your agency uses single sign-on.",
      starting: "Taking you to your identity provider to sign in.",
      finishingHeading: "Signing you in",
      finishing: "Finishing your sign-in with your identity provider.",
      /* Shown when the sign-in cannot even be attempted: nothing usable came
         back from the provider, or this browser is not the one that started
         it. A refusal from the API carries the API's own message instead,
         shown verbatim — ONE generic sentence for every federated failure,
         on purpose, with the real reason in Headway's audit trail. */
      failed:
        "Headway could not sign you in with single sign-on. Please try again, or sign in with your Headway username and password.",
    },
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
    /** Teaching empty state (handoff 0021, design point 4): one warm
     *  sentence + the concrete first action — never a blank. Since handoff
     *  0026 the first action is the Compute figures room, not a CLI line
     *  (developer invocation, for the curious: `python -m
     *  headway_calc.runner --period-start <start> --period-end <end>` —
     *  documented in services/api/README.md, never shown on a user
     *  surface). */
    empty:
      "Nothing computed yet — that is the honest state of a fresh Headway, not an error. Figures appear here the moment the calculation service produces one.",
    emptyActionAuthorized:
      "The first figures are one step away: pick a period and start a calculation run.",
    emptyDoor: "Compute figures",
    emptyActionViewer:
      "Figures are computed from the Compute figures page by a data steward, report preparer, or certifying official. Your viewer account sees every figure the moment one lands here.",
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
   * The calculations room (/calc-runs — handoff 0026): ask the server to
   * run the deterministic calculation service over a period, watch the run,
   * and read every run's honest outcome. NOTHING on this page computes a
   * number: the server dispatches the same versioned calculation runner the
   * CLI runs, and every figure, count, and id shown here is the runner's
   * own value served verbatim. Refusals are first-class: a run that
   * withheld every figure over blocking data-quality findings is the
   * product working, and this page says so in the house voice.
   */
  calcRuns: {
    heading: "Compute figures",
    intro:
      "This page asks Headway's calculation service to compute the reporting figures — vehicle miles, vehicle hours, passenger trips, passenger miles — over a period you pick. The service is deterministic and versioned; this page only starts it and shows what it reported. No number is ever computed or edited here.",
    refusalTeachingIntro:
      "If the recorded data cannot support a certifiable figure, the calculation refuses and says exactly why. A refusal is Headway working as designed — never an error to hide.",

    periodHeading: "Pick the period",
    periodHint:
      "Periods are half-open: the start date is included, the end date is not. “June 2026” means June 1 up to (not including) July 1.",
    monthLabel: "Calendar month",
    customOption: "Custom date range…",
    customStartLabel: "First day (included)",
    customEndLabel: "Day after the last day (not included)",

    runButton: "Compute figures for this period",
    runningButton: "A run is in progress…",
    reasonLabel: "Why the run button is unavailable",
    reasonPickPeriod: "Pick a calendar month or enter both custom dates first.",
    reasonRunLive:
      "A calculation run is already in progress. Headway runs one at a time — when it finishes, this button opens up again.",
    /** Viewers: the read-only surface says who can compute, plainly. */
    viewerNote:
      "Your viewer account can read every run on this page. Starting a run is done by a data steward, report preparer, or certifying official.",

    startedToast: "Calculation run started.",

    historyHeading: "Runs",
    historyIntro:
      "Every run ever requested, newest first, with its honest outcome. A run keeps reporting here even if you leave the page or the server restarts.",
    historyEmpty:
      "No calculation runs yet. The first one you start will appear here with its outcome.",
    tableCaption:
      "Calculation runs, newest first. Each run shows its status, timing, and the per-calculation outcomes exactly as the calculation service reported them.",

    /** Status labels: text carries the meaning (never color alone). */
    statusLabels: {
      queued: "Queued",
      running: "Running",
      succeeded: "Figures produced",
      refused: "Refused — figures withheld",
      failed: "Failed",
    } as Record<string, string>,
    statusExplanations: {
      queued: "Waiting to start.",
      running: "The calculation service is working.",
      succeeded: "At least one figure was produced and recorded.",
      refused:
        "Every calculation withheld its figure because blocking data-quality findings stand in the way. The reasons are recorded in the data-quality queue.",
      failed: "The run stopped before finishing. No figure was invented.",
    } as Record<string, string>,

    requestedLine: (by: string, at: string) => `Requested by ${by} at ${at}.`,
    periodLine: (start: string, end: string) =>
      `Period ${start} up to (not including) ${end}.`,
    /** Honest liveness: a wall-clock start time, never a progress bar. */
    runningSince: (time: string) => `Running since ${time}.`,
    queuedAt: (time: string) => `Queued at ${time}.`,
    /** Duration is the difference of two recorded timestamps. */
    durationLine: (seconds: string) => `Took ${seconds}.`,

    outcomesHeading: "What each calculation reported",
    outcomeTableCaption: (period: string) =>
      `Per-calculation outcomes for the run over ${period}, verbatim from the calculation service.`,
    outcomeColumns: {
      calc: "Calculation",
      scope: "Scope",
      outcome: "Outcome",
      figure: "Figure",
      links: "Where to look",
    },
    outcomePersisted: "Figure produced",
    outcomeRefused: "Refused",
    /** Identical re-run (persist dedupe): the figure was NOT duplicated —
     *  say so, or a re-run reads as a second figure on the record. */
    outcomeAlreadyOnRecord:
      "Same result as the figure already on record — not duplicated",
    coverageLine: (coverage: string) => `Coverage: ${coverage}`,
    /** Refusal detail: name the count and link the EXACT issues. */
    refusedIssuesLead: (count: number) =>
      count === 1
        ? "1 blocking data-quality finding explains why:"
        : `${count} blocking data-quality findings explain why:`,
    refusedIssueLink: (n: number) => `Open blocking finding ${n}`,
    persistedMetricsLink: "See it on the metrics page",
    persistedReceiptLink: "How this number was made",

    /** The first-run teaching moment (handoff 0026 design 3): shown when a
     *  run ends refused — house voice, walks the user to the DQ queue. */
    refusedTeachingHeading: "This refusal is Headway working as designed",
    refusedTeachingBody:
      "The calculation service looked at the recorded data and found it cannot support certifiable figures for this period — so it refused, and wrote down exactly why. Nothing was invented to fill the gap, and nothing was silently dropped. Each reason is a data-quality finding with an owner and a resolution path: resolve the findings and run the period again.",
    refusedTeachingDoor: "Go to the data-quality queue",

    failedLead:
      "What went wrong, in the dispatcher's words (recorded with the run):",
    outputTailToggle: "Show the runner's output (technical)",
    outputTailLabel: "Runner output tail",

    summaryCounts: (persisted: number, refused: number) =>
      `${persisted} figure${persisted === 1 ? "" : "s"} produced, ${refused} calculation${refused === 1 ? "" : "s"} refused.`,
    summaryContext: (positions: string, events: string) =>
      `Inputs read for the period: ${positions} vehicle positions, ${events} passenger events.`,
    thresholdContext: (threshold: string, source: string) =>
      `Coverage threshold in force: ${threshold} (from ${source === "settings" ? "the agency's audited settings" : source === "default" ? "the calculation library's default" : source}).`,

    /** v0 honest scope, stated on the page (handoff 0026 design 4). */
    scopeNote:
      "This page runs the standard calculation set over one period, one run at a time. Scheduled nightly runs, per-calculation selection, and canceling a run are on the roadmap — none of them is quietly pretended here. There is no progress percentage because Headway will not show a made-up one: a live run shows its real start time.",

    /** Staleness (server-computed note rendered verbatim beside it). */
    staleTag: "State unknown",
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
    warningsHeading: "Read this before you sign",
    simulatedWarning:
      "You are about to attest to figures computed from simulated test data. Simulated figures must never be submitted to the FTA. Certifying them would put your name on numbers that do not come from real service.",
    preVerificationWarning:
      "You are about to attest to figures from an early calculation that has not yet been checked against FTA rules. They are not certifiable figures yet.",
    acknowledgeLabel:
      "I have read these warnings and I understand what certifying these figures would mean.",
    acknowledgeHint:
      "The certify button stays off until you confirm the warning above.",
    nothingSelected:
      "Select at least one figure to certify. Use the checkbox above each receipt.",

    /**
     * The signing ceremony (handoff 0019, design 5): the cockpit's final
     * step is a signature block — the signer types their full name and
     * title against the intent statement, with everything the signature
     * covers listed above it. The API canonicalizes, signs, and stores;
     * this page never records anything locally.
     */
    sign: {
      heading: "Sign and certify",
      coversHeading: "What your signature covers",
      coversIntro:
        "Your signature will cover exactly the figures and acknowledgments listed here — nothing more, nothing less.",
      coversEmpty:
        "No figures are selected yet. Tick a figure above to bring it under your signature.",
      figureSummary: (
        metric: string,
        period: string,
        value: string,
        unit: string,
        calc: string,
      ) => `${metric}, ${period}: ${value} ${unit} — calculated by ${calc}`,
      /** Receipt hashes exist only inside the signed document — stated. */
      receiptHashPending:
        "Receipt hash: computed and recorded by the server when it signs.",
      /** A covered figure that relies on a statistician attestation. The
       *  figure's simulated/pre-verification flags travel inside its
       *  signed detail; the warnings panel above gates the acknowledgment. */
      attestationReliance: (id: string) =>
        `This figure relies on statistician attestation #${id}.`,
      /**
       * The intent statement itself is SERVER text (GET
       * /certifications/intent), rendered verbatim — never this bundle's
       * words. These two strings only explain its absence.
       */
      intentLoading:
        "Headway is still loading the signing statement from the server. Signing stays off until it arrives — you can only sign against the exact words the server will record.",
      intentUnavailable:
        "Headway could not load the signing statement from the server, so there is nothing to sign against. Signing is off until it loads.",
      nameLabel: "Your full name",
      nameHint: "Type your full legal name, exactly as it should appear on the certificate.",
      titleLabel: "Your title",
      titleHint: "Your role at the agency, e.g. “Chief Executive Officer” or “NTD Certifying Official”.",
      submit: "Sign and certify",
      reasonLabel: "Why the sign-and-certify button is off",
      nameMissing: "Type your full name. The signature must carry it.",
      titleMissing: "Type your title. The signature must carry it.",
      /** The server records the signature; the UI then shows the certificate. */
      recordedNote:
        "When you sign, the server builds the signed record, signs it with the installation's signing key, and stores it. You will then see the certificate.",
    },
  },

  /**
   * The certificate view (/certifications/:id — handoff 0019, design 5–8):
   * the signature block front and center, the covered figures, and the
   * backend's honest-scope statement rendered VERBATIM — never paraphrased.
   */
  certificate: {
    heading: "Certification certificate",
    /** The breadcrumb's first crumb: the index room (list → certificate). */
    crumbList: "Certifications",
    crumbSelf: (id: string) => `Certificate ${id}`,
    intro:
      "This is the permanent record of one certification: who signed, what the signature covers, and the digital signature the server recorded. Nothing on this page is recalculated — it is the stored record.",
    signatureHeading: "Signature",
    signedBy: (name: string, title: string) => `Signed by ${name}, ${title}`,
    /** Pre-signature records carry only the account that certified. */
    certifiedByOnly: (username: string) =>
      `Certified by the account ${username}.`,
    signedAt: (timestamp: string) => `Signed at ${timestamp}`,
    fingerprintLabel: "Signing key fingerprint",
    signatureLabel: "Digital signature (Ed25519)",
    verifyButton: "Verify this signature",
    verifying: "Asking the server to re-verify the signature…",
    /** Lead-ins only; the server's own message renders verbatim after
     *  them (the unsigned-legacy verdict has no lead — the server's
     *  message stands alone). */
    verifiedLead: "Signature verified.",
    failedLead: "SIGNATURE VERIFICATION FAILED.",
    mismatchLead: "SIGNATURE NOT CHECKABLE.",
    scopeHeading: "What this signature covers — and what it does not",
    /** LOUD absence: the honest-scope statement lives inside the signed
     *  document; a signed record without one is stated, never papered. */
    scopeMissing:
      "The signed record does not contain the server's statement of what this signature covers. Without it, this certificate cannot describe the signature's meaning — treat the signature's scope as unstated.",
    statementHeading: "The statement that was signed",
    coveredHeading: "Figures this signature covers",
    /** Degraded-but-honest: a legacy record has no signed figure list. */
    coveredIdsOnly:
      "This record holds only the identifiers of the covered figures, not a signed figure list. Each identifier links to its figure's provenance.",
    coveredFigure: (
      metric: string,
      period: string,
      value: string,
      unit: string,
      calc: string,
    ) => `${metric}, ${period}: ${value} ${unit} — calculated by ${calc}`,
    receiptHash: (hash: string) => `Receipt hash: ${hash}`,
    provenanceLink: "How this number was made",
    attestationsHeading: "Statistician attestations the figures relied on",
    attestationLine: (id: string, statistician: string) =>
      `Attestation #${id} — ${statistician}`,
    attestationsLink: "See the attestations page",
    loadErrorLead:
      "Headway could not load this certificate. The server said:",
  },

  /**
   * The certifications index (/certifications — the "list → certificate"
   * follow-up recorded in handoff 0019's frontend evidence). Every row is
   * the API's record verbatim, oldest first; digitally signed records and
   * records that predate signatures are both listed honestly — history is
   * never hidden, and legacy records are never backfilled.
   */
  certifications: {
    heading: "Certifications",
    intro:
      "Every certification on record, oldest first: who put their name on which figures, when, and — for digitally signed records — the signing-key fingerprint. Each entry opens its full certificate, where the signature can be verified.",
    /** Teaching empty state (handoff 0021 #4): warm + the first action
     *  (the Certify door renders for the certifying official). */
    empty:
      "No certifications are on record yet — records appear here the moment a certifying official signs figures, and they stay forever.",
    emptyActionOfficial:
      "When figures are ready, the Certify page shows exactly what your signature would cover before it arms.",
    emptyDoor: "Go to the Certify page",
    loading: "Loading the certifications on record…",
    /** Summary cards = filter toggles (handoff 0017 #2). Counts are
     *  workflow tallies of records in the list, never figures. */
    summaryLabel: "Certifications at a glance — filter by signature state",
    cardLabels: {
      signed: "Digitally signed",
      legacy: "Recorded before signatures",
    } as Record<string, string>,
    /** Filtering hides nothing silently: the held-back count is stated. */
    filteredNote: (count: string) =>
      `${count} certification record${count === "1" ? " is" : "s are"} outside the pressed filter — out of view here, never off the record. Press the card again to show everything.`,
    listLabel: "Certifications on record",
    recordLabel: (id: string) => `Certification ${id}`,
    signedTag: "Signed",
    /** The honest state of a pre-signature record — never a blank. */
    legacyTag: "No digital signature",
    legacyNote:
      "Recorded before digital signatures existed in Headway — no signature fingerprint. Honest history, never backfilled.",
    signerLine: (name: string, title: string) =>
      `Signed by ${name}, ${title}`,
    certifiedByLine: (username: string) =>
      `Certified by the account ${username}.`,
    certifiedAtLabel: "Certified at",
    fingerprintLabel: "Signing key fingerprint",
    /** metric_value_ids.length — a workflow count of covered figures. */
    coversLine: (count: string) =>
      `Covers ${count} figure${count === "1" ? "" : "s"}.`,
    viewCertificate: (id: string) => `Open certificate ${id}`,
  },

  /**
   * THE REVIEW SURFACE (/review — handoff 0047).
   *
   * Where a read-only role lands instead of /today. The control room asks
   * "what should I do now?"; a reviewer asks a different question — "what
   * was filed, and does it hold up?" — so this room is a WORKLIST OF
   * CERTIFICATIONS and nothing else. No queue, no tallies waiting to be
   * cleared, nothing asking to be acted on: a reviewer has no work to clear
   * in someone else's system, and a screen that implies otherwise teaches
   * them to distrust it.
   *
   * Three things are said out loud here that a reader would otherwise have
   * to discover by hitting a wall: that their own reading is recorded, what
   * this account cannot open and why, and that a withheld record is drawn as
   * withheld rather than left blank.
   */
  review: {
    heading: "Review",
    intro:
      "Every certification this agency has made, in the order Headway recorded them. A certification is the moment a named person put their name to a set of figures, so it is where a review starts. Open one to see the figures it covers, each figure's receipt, and the trail from any figure back to the raw records it was built from.",
    loading: "Reading the certifications on record…",
    loadErrorLead: "Headway could not load the certifications. The server said:",
    /** No records is a fact about a young installation, not a gap. */
    empty:
      "No certifications are on record yet. When a certifying official signs a set of figures, the record appears here and stays permanently.",

    tableLabel: "Certifications on record",
    tableCaption:
      "Certifications on record, oldest first — the order Headway serves them in, unchanged.",
    columns: {
      certification: "Certification",
      period: "Period covered",
      signer: "Signed by",
      signedAt: "Signed at",
      figures: "Figures covered",
      verification: "Signature check",
    },
    rowLink: (id: string) => `Certification ${id}`,
    signerLine: (name: string, title: string) => `${name}, ${title}`,
    /** A record with no typed name says so rather than showing a blank. */
    signerAccountOnly: (username: string) =>
      `The account ${username} — no typed name on this record.`,

    /** Period and verdict both arrive with the certificate itself. */
    detailChecking: "Reading this certificate…",
    periodUnknown:
      "Not recorded. This certification predates the signed document that carries each figure's period.",
    /** The certificate itself could not be read — said, never left blank,
     *  and worded apart from the signature verdict beside it. */
    periodUnavailable: "Could not be read",
    /** A signed document that lists no figures: an anomaly, not history. */
    periodNoFigures: "The signed document lists no figures.",
    /** The four verdicts the server can return, plus the honest fifth: the
     *  check could not be made at all, which is never shown as a pass. */
    verdictLabels: {
      verified: "Signature verified",
      failed: "SIGNATURE CHECK FAILED",
      key_mismatch: "Cannot be checked with the current key",
      unsigned_legacy: "No digital signature",
    } as Record<string, string>,
    verdictUnknown: "Unrecognised result",
    verdictUnavailable: "Could not be checked",
    verdictNote:
      "Every result in the signature-check column is the server's own. Headway re-reads each stored certificate and re-checks its signature while this page loads; nothing here is worked out in your browser.",

    /** The reader is told they are recorded — plainly, once, on entry. */
    recordHeading: "You are on the record here",
    recordBody:
      "Headway records reading, not only changing. Every time the audit trail is read, Headway writes down who read it, which filters they used and how many entries came back — never the entries themselves. Those notes cannot be edited or deleted by anyone, including an administrator.",
    recordWhy:
      "This protects you as much as the agency: the care you took is on the record too.",
    recordNoWrites:
      "This account cannot change what it is reviewing. Headway refuses changes from it at the server, not merely on this screen.",
    /**
     * The ONE exception, named here rather than discovered. The rule above is
     * no longer absolute — handoff 0047 opened a single route to this role —
     * and an unstated exception is precisely the shape of contradiction this
     * surface was built to remove.
     */
    recordVerify:
      "There is one deliberate exception, and it is the reason this account exists: you may ask Headway to re-read a raw record's stored bytes and re-check its fingerprint. Doing so alters nothing under review. It records that you checked, and — if the bytes no longer match what was received — raises a data-quality finding for the agency to answer. That finding is the most valuable thing a review can produce, so it goes on the record where the people who must act on it will see it, under your name.",

    /** What this account cannot open, said here instead of in a 403. */
    scopeHeading: "What this account cannot open",
    scopeIntro:
      "Three parts of Headway are limited to the certifying official. This is not a gap in the record — it is the line between reviewing the figures and running the installation:",
    scopeItems: [
      "The list of Headway accounts and the role each one has.",
      "Single sign-on settings — how the agency connects Headway to its identity provider.",
      "Machine keys — the credentials other systems use to send data into Headway.",
    ],
    scopeAsk:
      "If your review needs any of these, ask the agency's certifying official. Headway refuses the whole page rather than showing a partial version of it.",
    /** The withholding rule, stated before a reader meets it in the wild. */
    scopeWithheldHeading: "Withheld contents are marked, never blank",
    scopeWithheld:
      "Raw records that carry rider pickup and dropoff addresses stay closed to every role below data steward, this one included — a paratransit trip record can disclose a rider's home and their disability status. Where that applies, the record shows the reason in place of its contents. A withheld record is never drawn as an empty one, because an empty one reads as missing data.",

    /** Orientation, not a call to action: where the rest of it lives. */
    moreHeading: "Where the rest of the record is",
    moreCalcRuns:
      "Which calculation produced a figure, which version of it ran, and what it refused to compute",
    moreCalcRunsLink: "Calculation runs",
    moreDq:
      "Every data-quality finding Headway has raised — open, resolved, and closed under a statistician attestation",
    moreDqLink: "Data quality",
    moreMetrics:
      "Every computed figure, each with its receipt and its trail back to raw records",
    moreMetricsLink: "Metrics",
  },

  /**
   * Statistician attestations (/attestations — handoff 0019, design A).
   * The p. 146 rule permits factoring beyond the 2% missing-trip line only
   * under a statistician-approved method; this room records that approval
   * (its existence and an external document pointer — never the document)
   * and shows every recorded attestation, revoked ones included.
   */
  attestations: {
    heading: "Statistician attestations",
    intro:
      "When more than 2% of trips are missing passenger counts, federal rules allow the figures to be adjusted up only if a qualified statistician has approved the adjustment method. This page records that approval so the calculation can apply it — and lists every approval on record. The federal rule, word for word:",
    /** What recording one does — and the calc behavior either way. */
    behaviorNote:
      "Without a matching attestation on record, Headway refuses to adjust figures with more than 2% of trips missing — exactly as before. With one, the calculation applies the approved method within the attestation's declared scope and stamps the attestation number into the figure's receipt.",
    limitsHeading: "What an attestation can never do",
    /** Statements of Headway behavior (handoff 0019, design 3's hard
     *  limits, pinned by calc tests) — regulatory rules themselves are
     *  always shown as verbatim quotes where they apply. */
    limits: [
      "It never unblocks an undersampled PMT sampling plan. Undersampling stays refused — the sampling pages quote the manual's own no-undersampling rule.",
      "It never touches the simulated-data flag. Simulated figures stay marked simulated everywhere.",
      "It never applies outside its declared scope — the metric, the mode and type of service, and the period range recorded with it.",
      "It never affects operations metrics. Those are not NTD reported figures and take no adjustments.",
    ],
    listHeading: "Attestations on record",
    empty:
      "No attestations are on record. Figures with more than 2% of trips missing will be refused until a statistician-approved method is recorded here.",
    /** Every record stays visible — revocation is a state, not a deletion. */
    revokedTag: "Revoked",
    revokedNote: (timestamp: string, by: string) =>
      `Revoked ${timestamp} by ${by}. Revoked attestations stay on record — nothing here is ever deleted.`,
    revokedReason: (reason: string) => `Reason: ${reason}`,
    attestationLabel: (id: string) => `Attestation #${id}`,
    /** Revocation (certifying official; audited; append-only). */
    revoke: {
      heading: "Revoke this attestation",
      note: "Revoking stops FUTURE calculation runs from factoring under this approval. Figures already computed under it keep its record permanently, and the attestation itself stays on this page — revoked, never deleted.",
      reasonLabel: (id: string) => `Reason for revoking attestation #${id}`,
      button: (id: string) => `Revoke attestation #${id}`,
      reasonMissing:
        "Write the reason for revoking. It is kept in the record and the audit log.",
      reasonHint: "Kept in the record and the audit log.",
      toast: "Attestation revoked and audit-logged. It stays on record below.",
    },
    statisticianLine: (name: string, credentials: string) =>
      `Approved by ${name} — ${credentials}`,
    methodHeading: "Approved method",
    scopeHeading: "Scope of the approval",
    scopeMetric: (metric: string) => `Metric: ${metric}`,
    scopePattern: (pattern: string) => `Applies to: ${pattern}`,
    scopePeriod: (start: string, end: string) =>
      `Period: ${start} to ${end}`,
    documentLine: (reference: string) =>
      `Approval document: ${reference} (Headway stores this pointer, never the document itself)`,
    enteredLine: (username: string, timestamp: string) =>
      `Recorded by ${username}, ${timestamp}`,

    /** The audited entry form (authorized role; server-enforced). */
    form: {
      heading: "Record a new attestation",
      intro:
        "Record an approval a qualified statistician has already given. You are recording that the approval exists and where its document lives — Headway never stores the document itself. This entry is audit-logged and permanent: an attestation can later be revoked, never deleted.",
      notAllowed:
        "Only a certifying official can record an attestation. You can still read every attestation on record below.",
      statisticianLegend: "The statistician",
      nameLabel: "Statistician's full name",
      credentialsLabel: "Credentials",
      credentialsHint:
        "Their qualification and affiliation, e.g. “PhD, Statistics — State University; independent consultant”.",
      methodLegend: "The approved method",
      methodLabel: "Method description",
      methodHint:
        "In plain words, the adjustment method the statistician approved, e.g. “Factor up by route-level average boardings from the surrounding four weeks”.",
      documentLabel: "Approval document reference",
      documentHint:
        "Where the signed approval lives — a file path, records-system number, or document id. Headway stores this pointer only.",
      scopeLegend: "Scope of the approval",
      metricLabel: "Metric",
      metricHint:
        "The reported figure the approval covers. Only figures built from 100% counts can carry one.",
      patternLabel: "Mode and type of service",
      patternHint:
        "Which figure scopes the approval covers, exactly as scopes appear on the Metrics page: “agency” for the agency-wide figure, a scope like “mode:DR”, a pattern like “mode:DR:tos:*” for every DR type of service, or “*” for every scope.",
      periodStartLabel: "Covers periods from",
      periodEndLabel: "Up to (not including)",
      submit: "Record attestation",
      reasonLabel: "Why the record button is off",
      missingField: (field: string) => `Fill in “${field}”.`,
      toast:
        "Attestation recorded and audit-logged. It appears in the list below.",
      success: (id: string, auditEventId: string) =>
        `Attestation #${id} recorded. Audit event ${auditEventId}.`,
    },
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
    /**
     * The end of the trail, but no longer a dead end (handoff 0035). It used
     * to read "raw source record as received — the end of the trail", and a
     * UAT auditor's verdict on that was exact: "It doesn't really provide any
     * data to validate or verify." The leaf now opens.
     */
    rawLeaf: "raw source record, exactly as Headway received it",
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

  /**
   * The raw-record inspector (handoff 0035): the label, the integrity
   * button and the window on the last link in the chain of custody. Plain
   * language throughout — the reader is an auditor or an operations
   * manager, not a data engineer.
   */
  rawRecord: {
    openLabel: (id: string) => `Open the raw source record ${id}`,
    open: "Open this record",
    close: "Close this record",
    loading: "Reading this record's label…",
    /** Field labels on the label itself. */
    source: "Source",
    connector: "Collected by",
    fetchedAt: "Received",
    landedAt: "Stored",
    contentType: "File type",
    size: "Size",
    parseStatus: "Read on arrival",
    parseOk: "Read successfully",
    parseMalformed: "Could not be read",
    storedAt: "Bytes held",
    sizeUnknown: "measured when you open the contents",
    /** The hash: still here, deliberately demoted to a footnote. */
    fingerprintHeading: "Fingerprint (SHA-256)",
    inspect: "Look inside",
    hideInspect: "Hide the contents",
    verify: "Verify integrity",
    verifying: "Re-reading the bytes and re-computing the fingerprint…",
    download: "Download the exact bytes",
    downloading: "Preparing the download…",
    verdictMatch: "Integrity verified",
    verdictMismatch: "INTEGRITY CHECK FAILED",
    verdictMissing: "The bytes are missing",
    verdictUnavailable: "Could not be checked",
    verdictDigests: "Fingerprints compared",
    verdictExpected: "This record's id (the fingerprint of the bytes as received)",
    verdictActual: "The fingerprint of the bytes stored right now",
    verdictIssue: (id: string) => `Data-quality finding raised: ${id}`,
    verdictIssueLink: "Open the finding",
    verifiedAt: (when: string) => `Checked ${when}`,
    withheldHeading: "Contents withheld",
    previewHeading: "Inside this record",
    previewLoading: "Reading the contents…",
    entitiesHeading: "Vehicles and updates in this message",
    feedHeading: "Feed message",
    feedVersion: "GTFS-Realtime version",
    feedIncrementality: "Message type",
    feedTimestamp: "Feed timestamp",
    feedEntities: "Records inside",
    entityVehicle: "Vehicle",
    entityRoute: "Route",
    entityTrip: "Trip",
    entityPosition: "Position",
    entityTime: "Reported at",
    entityStatus: "Status",
    entityStop: "Stop",
    entityOccupancy: "Occupancy",
    entityDelay: "Delay (seconds)",
    entityStopUpdates: "Stop updates",
    entityAlert: "Service alert",
    absent: "not reported",
    rowsHeading: "First rows of the file",
    linesHeading: "First lines of the file",
    noColumns: "Columns are shown without names",
    undecodedHeading: "Headway cannot show this file's contents",
    error: "Headway could not read this record.",
  },

  dq: {
    heading: "Data-quality issues",
    intro:
      "Every gap, conflict, or failed check in the data is listed here until a person resolves it. Issues marked “Blocking” stop certification: no figure can be certified while one is open.",
    empty: "No data-quality issues. New issues appear here as pipelines run.",
    /** Deep link from another room (handoff 0026: a calculation refusal
     *  links straight to the exact finding that blocked it — /dq?issue=id). */
    linked: {
      heading: "Finding opened from a link",
      intro:
        "You followed a link to this exact finding — usually from a calculation run it blocked. The full queue is below.",
      notFound: (issueId: string) =>
        `The link pointed at finding ${issueId}, but no finding with that id is in the queue. It may have been recorded in a different Headway installation, or the link may be stale. The full queue is below.`,
    },
    severityLabels: {
      blocking: "Blocking",
      warning: "Warning",
      info: "Info",
    } as Record<string, string>,
    statusLabels: {
      open: "Open",
      owned: "Owned",
      resolved: "Resolved",
      /** Migration 0029: closed by a statistician attestation (p. 146). */
      attested: "Attested",
    } as Record<string, string>,
    /**
     * The queue-at-a-glance cards (2026-07-11 click-through, finding 2).
     * Counts are of ISSUES IN THE QUEUE — workflow tallies, not regulatory
     * figures. Since handoff 0024 they come from GET /dq/issues/counts,
     * which counts in the database over the WHOLE queue; since handoff
     * 0030 the list beneath them serves one page at a time, so the copy
     * has to keep that distinction visible in words. A card that silently
     * meant "of the 50 issues loaded" would be exactly the kind of quiet
     * lie this project refuses.
     */
    summaryHeading: "Queue at a glance",
    /** Said once, under the cards, so the distinction is never implied. */
    summaryScope: (total: string) =>
      `These counts cover all ${total} issues in the queue, not just the page shown below.`,
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
    /**
     * The page line (handoff 0030). The queue is read one page at a time —
     * before this, /dq downloaded all 98,497 issues (850 MB, 17 seconds,
     * and a frozen tab). Three facts, always together: which issues are on
     * screen, how many match in total, and that the counts above are the
     * whole queue rather than this page.
     */
    showingRange: (from: string, to: string, matching: string) =>
      `Showing issues ${from}–${to} of ${matching} that match. The rest are still in the queue — use Next to read on, or the cards above to narrow it.`,
    showingRangeUnfiltered: (from: string, to: string, total: string) =>
      `Showing issues ${from}–${to} of ${total} in the queue. The rest are still there — use Next to read on, or the cards above to narrow it.`,
    /** Plain page controls: no infinite scroll, no hidden loading. */
    pageNext: "Next page",
    pagePrevious: "Previous page",
    pageNavLabel: "Data-quality queue pages",
    pageLoading: "Loading the next page…",
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

    /**
     * The provenance disclosure (handoff 0030). The raw-record ids are the
     * lineage chain from a finding back to the feed messages it was raised
     * over — they did not go anywhere, they moved off the queue listing
     * (716 MB of an 850 MB response) onto the finding itself, fetched when
     * someone actually asks for them. Every row keeps the path.
     */
    sourceRecords: {
      toggle: "Source records: the raw data behind this finding",
      intro:
        "The exact raw records Headway raised this finding over. Fetched for this finding only — copy them when you are working a ticket or querying the data directly.",
      loading: "Loading the source records for this finding…",
      count: (count: string) =>
        `${count} raw ${count === "1" ? "record" : "records"}`,
      /** A finding about a run as a whole cites no individual record. */
      none:
        "This finding is about the calculation run as a whole, so it cites no individual raw records.",
      failed:
        "The source records for this finding could not be loaded. The finding itself is unchanged.",
      retry: "Try loading the source records again",
    },

    /**
     * What the finding is ABOUT, said the way the agency says it (handoff
     * 0029). First-agency UAT, on a real blocking finding: "staff/users
     * will need an easier way to know what exact block they are looking
     * for that had the issue." So the headline is blocks, routes and times
     * of day; the raw identifiers move into a collapsed disclosure where
     * they stay copyable for anyone working a ticket.
     *
     * NOTHING here invents a label. Where the feed carries no block, no
     * route name, or no scheduled time, the copy SAYS that — it never
     * substitutes a plausible-looking stand-in.
     */
    subject: {
      heading: "Which trips this affects",
      intro: (total: string, groups: string) =>
        `${total} affected ${total === "1" ? "trip" : "trips"}, grouped into ${groups} ${groups === "1" ? "block" : "blocks"}. Blocks are listed in the order their first trip is scheduled to leave.`,
      /** Stated cap — the count above always covers everything. */
      groupCap: (shown: string, total: string) =>
        `Showing the first ${shown} of ${total} blocks. Nothing is dropped: the trip and block counts above cover every affected trip, and the full list of identifiers is in the technical detail below.`,
      columns: {
        block: "Block",
        trips: "Trips",
        routes: "Route(s)",
        span: "Scheduled times",
      },
      tableCaption: "Affected trips grouped by block",
      /** The feed carries no block for these trips — a fact, not a gap
       *  we paper over with a made-up id. */
      blockAbsent: "No block in the schedule feed",
      blockAbsentHint:
        "These trips run without a block identifier in the agency's published schedule. Headway shows no block for them rather than guessing one.",
      /** A route with no short name: the id is all that exists. */
      routeIdOnly: (routeId: string) => `${routeId} (route id — the feed carries no route name)`,
      routesNone: "No route in the schedule feed",
      routesMore: (shown: string, total: string) =>
        `${shown} of ${total} routes`,
      spanAbsent: "No scheduled time in the feed",
      /** GTFS counts from the start of the service day, so 25:10 means
       *  1:10 a.m. the next morning — said plainly, not wrapped silently. */
      spanNote:
        "Times are from the published schedule, counted within the service day: an hour of 24 or more means after midnight.",
      tripCount: (count: string) =>
        `${count} ${count === "1" ? "trip" : "trips"}`,
      /** Trips Headway saw operating that are not in the schedule feed. */
      unmatchedHeading: "Trips not in the schedule feed",
      unmatchedBody: (count: string) =>
        `${count} affected ${count === "1" ? "trip is" : "trips are"} not in the published schedule, so Headway has no block, route, or time for ${count === "1" ? "it" : "them"}. That usually means the trip was added by dispatch after the schedule was published.`,
      /**
       * A block the agency's own mapping names (handoff 0038): the
       * operational name is the headline in the table, and the feed's
       * identifier stays one disclosure away — the 0032 vehicle-label
       * presentation. Never shown unless the mapping stated it.
       */
      technicalBlockLabeled: (label: string, blockId: string) =>
        `${label} — feed block id ${blockId}`,
      /** The forensic disclosure: collapsed, never removed. */
      technicalToggle: "Technical detail: trip identifiers",
      technicalIntro: (cap: string) =>
        `The internal trip identifiers behind the blocks above — useful when working a ticket or querying the data directly. Up to ${cap} identifiers are listed per block; each block's trip count above is the real total.`,
      technicalIdsLabel: (block: string) => `Trip identifiers for ${block}`,
    },
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

    /**
     * The attest closure (handoff 0019 follow-up: POST
     * /dq/issues/{id}/attest gets its UI room). Offered ONLY on the
     * p. 146 refusal class — no other gap has a statistician cure — and
     * gated in UX at data_steward+, mirroring the API's enforced rule
     * exactly (the same rule as every resolution). The p. 146 rule itself
     * always renders as the verbatim quote beside these words.
     */
    attest: {
      button: (title: string) => `Attest: ${title}`,
      dialogHeading: "Close this issue under a statistician attestation",
      /** Plain-language framing ONLY — the rule renders verbatim below. */
      intro:
        "This issue is Headway's refusal to adjust a figure because more than 2% of its trips are missing passenger counts. Federal rules allow that adjustment when a qualified statistician has approved the adjustment method. Closing this issue records that a statistician's approval already on record covers this gap: the issue moves to the permanent “attested” state (closed, never deleted), and the calculation applies the approved method on its next run — stamping the attestation into the figure's receipt. The rule, word for word:",
      pickLabel: "Which recorded attestation covers this gap?",
      pickHint:
        "Only standing (unrevoked) attestations are offered. The server checks that the one you pick actually covers this issue's metric, scope, and period — a mismatch is refused, and the refusal is shown here word for word.",
      optionLabel: (
        id: string,
        statistician: string,
        metric: string,
        pattern: string,
        start: string,
        end: string,
      ) =>
        `#${id} — ${statistician} — ${metric}, ${pattern}, ${start} to ${end}`,
      noneAvailable:
        "No standing attestation is on record, so this issue cannot be closed this way yet. Record the statistician's approval on the Attestations page first — this dialog only references approvals that already exist.",
      attestationsLink: "Go to the Attestations page",
      loadingAttestations: "Loading the attestations on record…",
      pickRequired:
        "Pick the recorded attestation that covers this issue.",
      submit: "Close this issue as attested",
      cancel: "Cancel",
      success: (title: string) =>
        `“${title}” is closed as attested. The resolution names the attestation permanently.`,
    },
  },

  /**
   * The revenue review queue (handoff 0040): the boardings Headway refused to
   * guess about, and the note an analyst writes when they decide one.
   *
   * Written for someone who runs a transit agency, not a database. No
   * sentence here says "unassigned", "no-run", "revenue_classification" or
   * "passenger event" — it says what happened on a bus and what it means for
   * a number the agency has to report. The two things every screen must make
   * unmissable: nothing here is counted until somebody decides it, and
   * deciding it does not change any figure until the figures are worked out
   * again.
   */
  revenueReview: {
    heading: "Boardings to review",
    intro:
      "These riders were counted by a bus while nobody was logged into a run. That usually means staff getting on during prep or clean-up, which is not public ridership — but it can also mean an extra bus sent out to catch up a late route, carrying real riders. Headway will not guess between the two, so it is holding these out of your ridership figure until you say which they are.",
    /** The inviting empty state — the queue being empty is GOOD news. */
    empty: {
      heading: "Nothing is waiting on you",
      body: "Every boarding Headway could not work out on its own has been decided. Your ridership figure is not holding anything back for review.",
      hint: "If a future day has boardings recorded off-run, they will appear here after the figures are worked out for that period.",
    },
    /** The header cards. Rows and boardings are different numbers. */
    cards: {
      pending: "Waiting on a decision",
      pendingBoardings: "Riders held out of the figure",
      classified: "Decided so far",
      classifiedRevenue: "Ruled real ridership",
      classifiedNonRevenue: "Ruled not ridership",
    },
    cardsScope: (rows: string) =>
      `Counted across the whole queue (${rows}), not just this page.`,
    /** The two tabs. */
    filterPending: "Waiting on a decision",
    filterClassified: "Already decided",
    filterLabel: "Which boardings to show",
    showingRange: (from: string, to: string, total: string) =>
      `Showing ${from}–${to} of ${total}.`,
    pageNext: "Next page",
    pagePrevious: "Previous page",
    pageNavLabel: "Review queue pages",
    pageLoading: "Loading the next page…",
    loadFailed:
      "The review queue could not be loaded. Nothing was changed.",
    retry: "Try again",

    /** One row's heading and facts. */
    rowHeading: (vehicle: string, when: string) =>
      `${vehicle} — ${when}`,
    vehicleLabel: (vehicle: string) => `Vehicle ${vehicle}`,
    vehicleUnknown: "Vehicle not recorded",
    ridersLabel: "Riders counted",
    ridersValue: (count: string) =>
      count === "1" ? "1 rider" : `${count} riders`,
    serviceDayLabel: "Service day",
    recordedAtLabel: "Recorded at",
    routeLabel: "Route and run",
    routeNone:
      "None — that is exactly why this boarding is here. The bus was not logged into a run, so there is no route, no trip and no stop on this record.",
    whyLabel: "Why Headway could not decide",
    suggestionLabel: "Headway's own reading",
    suggestionPending:
      "No suggestion. Headway will not guess this one — the federal manual has no rule that tells prep apart from a catch-up bus, so only a person who knows what dispatch did that day can say.",
    heldNote:
      "Held out of the ridership figure while it waits. It is not counted, and it is not thrown away.",
    flaggedByLabel: "Flagged by",
    flaggedByValue: (calc: string, version: string, when: string) =>
      `${calc} ${version}, first flagged ${when}`,
    periodLabel: "Reporting period",
    technicalToggle: "Show the record identifiers",
    technicalIntro:
      "The identifiers below are the provenance — they are what an auditor follows back to the original file. You do not need them to make the decision.",
    technicalEventLabel: "Boarding record",
    technicalSourceLabel: "Original source record",

    /** The decision form. */
    decideButton: (vehicle: string, when: string) =>
      `Decide: ${vehicle}, ${when}`,
    decideHeading: "What were these riders?",
    verdictLabel: "Your decision",
    verdictRevenue: "Real ridership — count them",
    verdictRevenueHint:
      "Choose this when the bus was carrying the public, even though it was not logged into a run — an extra bus sent to recover a late route is the usual case.",
    verdictNonRevenue: "Not ridership — leave them out",
    verdictNonRevenueHint:
      "Choose this when the count was staff, maintenance, prep or clean-up, a bus running empty to reposition, or a counter that misfired.",
    verdictRequired: "Choose one of the two decisions before saving.",
    justificationLabel: "Why (required)",
    justificationHint:
      "Write what you checked and what you found, in your own words. This becomes part of the figure's receipt: it is what lets the agency defend the correction in a federal review instead of just asserting it. Example: “Extra bus sent at 15:10 to recover the route after the 14:40 ran late; dispatch confirms these are real riders.”",
    justificationRequired:
      "Write down why. A decision with no reason cannot be defended later, so Headway will not record one.",
    submit: "Record this decision",
    cancel: "Cancel",
    /** Said at the moment of deciding, not buried in a footnote. */
    recomputeWarning:
      "Saving this records your decision. It does not change any figure that has already been worked out — the ridership number moves the next time the figures are worked out for a period that includes this day.",
    recomputeLink: "Go and work the figures out again",
    success: (vehicle: string) =>
      `Decision recorded for ${vehicle}. The ridership figure will reflect it the next time the figures are worked out.`,
    failed: "The decision was not recorded. Nothing was changed.",

    /** The decided rows (the history, and the receipt trail). */
    decidedRevenue: "Ruled real ridership",
    decidedNonRevenue: "Ruled not ridership",
    decidedByLabel: "Decided by",
    decidedByValue: (who: string, when: string) => `${who}, ${when}`,
    decidedWhyLabel: "Reason given",
    decidedFindingLabel: "Data-quality finding closed",
    decidedFindingNone:
      "No open data-quality finding was found for this boarding, so none was closed.",
    /** Shown on the "already decided" tab so nobody expects a live figure. */
    decidedRecomputeNote:
      "These decisions apply to figures worked out after they were made. A figure computed earlier still shows what it showed then — that is on purpose, so a number never changes quietly under a signature.",
    /** The refusal a certified period earns, restated for the list. */
    certifiedRefusalHint:
      "If a boarding falls inside a period somebody has already certified, Headway will refuse the decision and say so. A certified number keeps meaning what it meant when it was signed.",

    /**
     * The receipt side (handoff 0040, design point 2). A corrected ridership
     * figure has to be DEFENSIBLE, and a correction is only defensible if
     * you can see who made each judgment call, when, and why. These strings
     * put the human decisions inside "explain this number".
     */
    receipt: {
      heading: "Judgment calls behind this number",
      intro:
        "Some boardings were recorded while no bus was logged into a run, and Headway could not tell prep activity from real riders. It did not guess. A person decided each one and wrote down why, and that is recorded here permanently.",
      countedLine: (riders: string) =>
        `${riders} counted into this figure because a person ruled they were real ridership.`,
      excludedLine: (riders: string) =>
        `${riders} left out of this figure because a person ruled they were not ridership.`,
      heldLine: (riders: string) =>
        `${riders} still waiting on a decision, and held OUT of this figure until somebody makes one.`,
      autoExcludedLine: (riders: string) =>
        `${riders} left out automatically: recorded outside the hours the schedule says this service ran, which is prep, pull-out or pull-in rather than ridership.`,
      policyLine:
        "Headway's rule while a boarding is undecided: leave it out. A boarding nobody has classified must never quietly inflate or deflate a number an agency signs for.",
      verdictRevenue: "Counted as ridership",
      verdictNonRevenue: "Not ridership",
      entrySummary: (vehicle: string, when: string, riders: string) =>
        `${vehicle}, ${when} — ${riders}`,
      decidedBy: (who: string, when: string) => `Decided by ${who}, ${when}`,
      /** No paraphrase, ever: the analyst's words are the evidence. */
      reasonLabel: "In their words",
      frozenNote:
        "These decisions were read when this figure was worked out and were written into it. Decisions made since then apply to the next time the figures are worked out, not to this one — so a number never changes quietly under a signature.",
    },
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
    /** The statistician-attestation provenance line (handoff 0019). */
    attestationLine: (id: string, method: string | null) =>
      method
        ? `Adjusted under statistician attestation #${id} — approved method: ${method} (see the Attestations page).`
        : `Adjusted under statistician attestation #${id} (see the Attestations page).`,
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

    /**
     * The attested-figure callout (handoff 0019, design 2): a figure
     * factored beyond the 2% missing-trip threshold under a
     * statistician-approved method. A JUSTIFIED EXCEPTION, visually
     * distinct — labeled and bordered so it never reads as either a normal
     * figure or an error. The statement wording is the handoff's, verbatim;
     * the rule itself is the verbatim p. 146 quote placed beneath it.
     */
    attested: {
      tag: "Statistician-approved exception",
      statement: (id: string) =>
        `This figure was factored beyond the 2% threshold under a statistician-approved method — attestation #${id}.`,
      statistician: (name: string) => `Approved by ${name}.`,
      method: (summary: string) => `The approved method: ${summary}`,
      /** Honest absence: the calc served an attestation id but no summary. */
      methodMissing:
        "The calculation did not include the approved method's summary with this figure.",
      detailsLink: (id: string) =>
        `Read attestation #${id} on the Attestations page`,
      /** The p. 146 rule must be on file for an attested figure. */
      quoteMissing: (calcName: string) =>
        `No verified quote of the statistician-approval rule (manual p. 146) is on file for the ${calcName} calculation. Regenerate the quotes (npm run extract:quotes) — an attested figure must not ship without the rule that permits it.`,
    },
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
     * The monthly agency workbook (handoff 0020, design point 3): the
     * familiar hand-assembled monthly workbook, assembled by the API
     * instead — a receipt behind every cell. The note states coverage in
     * the handoff's own terms; absent figures are stated, never invented.
     */
    workbook: {
      label: "Download the monthly agency workbook",
      note:
        "One workbook for the picked month, assembled by the API: ridership by mode and operations figures (clearly badged as operations metrics), each data cell carrying its figure's provenance id, with a read-first notes sheet leading. A figure Headway has not computed is stated as absent — never invented, never zero-filled.",
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
    /** The signature fingerprint (handoff 0019, design 7) — the public
     *  feed serves it without any certifier identity. */
    fingerprintLabel: "Signature key fingerprint",
    fingerprintLegacy:
      "Certified before digital signatures existed in Headway — no signature fingerprint.",
    /**
     * The public verify affordance (handoff 0019 follow-up): the button
     * asks the SERVER's public verify endpoint — no account, no token —
     * and the verdict renders verbatim, verified or FAILED. Only these
     * frame words are this page's own.
     */
    verifyButton: (metric: string, period: string) =>
      `Verify this signature — ${metric}, ${period}`,
    verifying: "Asking the server to verify the signature…",
    verifyNote:
      "Anyone can run this check, without an account: the server re-checks the stored certificate against its digital signature and reports the verdict.",
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
    /** The audited flow's real room (handoff 0025): Admin → Settings.
     *  Rendered only for the certifying official, beside applyNote. */
    settingsDoor: "Open Settings (Admin) to make an audited change.",
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
    /** Handoff 0044: the always-visible one-liner. `intro` below moves,
     *  VERBATIM and unshortened, into the "What this shows" disclosure. */
    summary:
      "Figures shown exactly as computed — the charts scale the picture, never the figures.",
    intro:
      "The agency's computed figures at a glance. Every number here is shown exactly as the calculation service computed it — the charts scale the picture, never the figures.",
    /** Handoff 0044: the compact control strip that replaces three stacked
     *  paragraph-wrapped blocks above the figures. */
    controls: {
      label: "Figure controls",
      explain: "How these controls work",
    },
    /** Teaching empty state (handoff 0021 #4): warm + the first action —
     *  since handoff 0026, the Compute figures room, not a CLI line. */
    empty:
      "No charts yet, because nothing has been computed yet — an empty dashboard is a truthful one. The first calculation run fills this page in.",
    emptyActionAuthorized:
      "To produce the first figures, pick a period and start a calculation run.",
    emptyDoor: "Compute figures",
    emptyActionViewer:
      "Figures are computed from the Compute figures page by a data steward, report preparer, or certifying official.",
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
      /**
       * Handoff 0030: the tallies are the server's whole-queue counts (the
       * same ones /dq and /today read). The date filter slices the charts,
       * not this card — said in words whenever a date filter is active, so
       * the card is never read as "issues in the selected dates".
       */
      wholeQueueNote:
        "These tallies always cover the whole data-quality queue. The date filter above narrows the charts, not this card — go to the data-quality queue to work the list.",
      /**
       * The honest attention flag (handoff 0041): the card FRAME carries an
       * alert rail when a blocking issue is open, because that is the one
       * thing on this page that genuinely needs a human. It is a shape + a
       * sentence + a rail — never a rail alone, and never a treatment on a
       * figure (glow says "look here", not "this number is big").
       */
      blockingFlag: (count: string) =>
        `${count} blocking issue${count === "1" ? "" : "s"} ${count === "1" ? "is" : "are"} open. Blocking issues stop certification — this card needs a person.`,
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

    /**
     * Audience lenses (handoff 0024, design point 2): NAMED LENS
     * CONFIGURATIONS — grouping and framing only. A preset picks a calendar
     * grouping for the trend sparklines and an order for the sections;
     * nothing is recomputed, added together, or hidden. The grouping itself
     * is the server's (/metrics/history bucket labels), and the server's
     * own grouping_note renders verbatim beside these words.
     */
    lens: {
      rowLabel: "Audience lens",
      intro:
        "A lens arranges this page for its reader — it changes the calendar grouping of the trend lines and the order of the sections, nothing else. Every figure stays exactly as computed; no lens ever adds numbers together or hides one.",
      presets: {
        board: "Board",
        executive: "Executive",
        operations: "Operations",
      } as Record<string, string>,
      presetHints: {
        board:
          "Board lens: trends grouped by quarter, certified figures leading. The same figures, framed for a board packet.",
        executive:
          "Executive lens: trends grouped by month — the reporting rhythm.",
        operations:
          "Operations lens: trends grouped by day, operations cards first.",
      } as Record<string, string>,
      bucketLabel: "Group trends by",
      bucketOptions: {
        day: "Day",
        week: "Week",
        month: "Month",
        quarter: "Quarter",
      } as Record<string, string>,
      /** Lead-in only: the server's grouping_note renders verbatim after. */
      groupingIntro: "How the grouping works, in the server's own words:",
      historyUnavailable: (message: string) =>
        `The trend history could not be loaded: ${message}`,
    },

    /**
     * The Mode selector (handoff 0041, design points 1–4). Binding rules
     * restated where the copy lives:
     *
     * - DATA-DRIVEN: the options are the distinct `mode:*` scopes that
     *   actually carry persisted figures. No mode is named in this catalog
     *   as an option — a hardcoded mode that could only ever show zero
     *   would be a lie.
     * - RE-SCOPE, NEVER DERIVE: picking a mode filters to that mode's own
     *   persisted rows, verbatim, each with its metric_value_id receipt.
     *   Nothing on this page adds, averages, or synthesizes a per-mode
     *   number — not even a total across the modes.
     * - INVITING EMPTY STATES: a mode with nothing computed yet says so
     *   warmly and says why. A fabricated zero is never shown.
     */
    mode: {
      rowLabel: "Mode",
      allModes: "All modes (agency)",
      /** The lowercase-vocabulary bucket for a record with no mode. */
      unknownMode: "Mode not identified",
      tosLabel: (mode: string, tos: string) => `${mode} — ${tos}`,
      intro:
        "Pick a mode to read that mode's own figures. Headway shows the rows the calculation service already stored for that mode, exactly as computed — it never adds the modes up, averages them, or makes a per-mode number of its own.",
      /** Why the list is short — said out loud, so it never reads as a bug. */
      dataDrivenNote:
        "Only modes that already have computed figures are listed here. A mode joins the list the day its calculation wave lands; a mode that could only ever show a zero is never offered.",
      /** The scope receipt: the persisted scope string, shown verbatim. */
      scopeReceipt: (scope: string) => `Figure scope: ${scope}`,
      agencyNote:
        "Showing the agency-wide rollup — the figure the calculation service stored at scope “agency”, not a total this page added up from the modes.",
      selectedNote: (modeLabel: string, scope: string) =>
        `Showing ${modeLabel} only. Every figure below is a stored figure at scope “${scope}”, exactly as computed, and every one still opens its own receipt.`,
      /** A mode with no figures at all in the current dates. */
      emptyHeading: (modeLabel: string) => `No figures for ${modeLabel} yet`,
      emptyBody: (modeLabel: string) =>
        `Nothing has been computed for ${modeLabel} in the selected dates. Figures appear here the moment the calculation service stores one for this mode — Headway would rather show you an empty page than a number nobody computed.`,
      emptyWiden:
        "Widening the date range above, or switching back to all modes, will show what does exist.",
      /** One card with nothing for this mode (the mode itself has data). */
      cardEmpty: (what: string, modeLabel: string) =>
        `No ${what} for ${modeLabel} in these dates yet. Headway shows a mode's figures only once they have been computed and stored — never a zero standing in for one.`,
      cardEmptyWhat: {
        upt: "unlinked passenger trips",
        service: "vehicle revenue miles or hours",
        coverage: "coverage information",
      } as Record<string, string>,
      /** Operations metrics carry no mode dimension — stated, never faked. */
      opsNote: (modeLabel: string) =>
        `Operations metrics are computed per route, not per mode, so this section is NOT narrowed to ${modeLabel} — it keeps showing every route. Narrowing it here would mean inventing a per-mode operations figure nobody computed.`,
      /** DQ tallies count issues, not figures — also no mode dimension. */
      dqNote: (modeLabel: string) =>
        `These tallies always cover the whole data-quality queue. They are NOT narrowed to ${modeLabel}: the queue counts issues, and no issue tally has been counted per mode.`,
      /** The tiles' heading gains the scope so a mode slice never passes
       *  for the whole agency. */
      tilesFor: (modeLabel: string) => `Latest certified figures — ${modeLabel}`,
    },

    /**
     * KPI sparklines (handoff 0024, design point 2): every point is a
     * PERSISTED figure served by /metrics/history, one click from its full
     * receipt; a calendar bucket with no figure renders as a visible gap —
     * the line breaks, and nothing is ever interpolated across it.
     */
    sparkline: {
      label: (metric: string) =>
        `Trend of persisted ${metric} figures. Each point is a real figure — press it to open its receipt.`,
      pointLabel: (value: string, unit: string, period: string, status: string) =>
        `${value} ${unit}, ${period} (${status}) — open the receipt`,
      /** Gaps are stated in words as well as drawn. */
      gapsNote: (count: string) =>
        `${count} ${count === "1" ? "bucket in this range has" : "buckets in this range have"} no figure — drawn as a gap, never filled in.`,
      pointCap: (cap: string, total: string) =>
        `Showing the ${cap} most recent of ${total} figures in this trend — nothing is summarized away; the Metrics page lists every figure.`,
      empty: "No history yet for this figure.",
      closeReceipt: "Close the receipt",
    },
  },

  /**
   * The Today briefing home (/today — handoff 0021, design point 1): the
   * product greets you with YOUR situation, composed client-side from
   * existing endpoints. Binding rules restated where the copy lives:
   * every number on a card keeps its receipt door (a figure opens its
   * Receipt; a workflow tally links to exactly the list it was counted
   * over); a card with nothing to say says so warmly and never invents
   * urgency; deltas are SERVER-computed and sign-neutral unless the
   * metric's registry defines a direction.
   */
  today: {
    heading: "Today",
    intro:
      "Your agency's situation right now. Every number on this page is shown exactly as computed or counted by the server — and every one opens into its receipt.",
    /** The month label for workflow lines ("July 2026"). */
    monthLine: (monthLabel: string) => `${monthLabel} so far`,
    takeTourLink: "Take the tour",

    /** ---- certification briefing (certifying official leads) ---- */
    certification: {
      heading: "Certification",
      /** "July figures: N awaiting your signature, M blockers open." */
      readyLine: (monthLabel: string, ready: string) =>
        `${monthLabel} figures: ${ready} computed and not yet certified.`,
      blockersLine: (count: string) =>
        `${count} blocking data-quality issue${count === "1" ? "" : "s"} open — certification stays off until ${count === "1" ? "it is" : "they are"} resolved.`,
      noBlockersLine:
        "No blocking data-quality issues are open. Certification is allowed.",
      certifiedLine: (count: string) =>
        `${count} certification${count === "1" ? "" : "s"} on record.`,
      /** Warm empty: nothing pending is a fine morning, not a gap. */
      empty: (monthLabel: string) =>
        `Nothing is waiting for your signature for ${monthLabel}. When the pipeline computes new figures, they appear here with their receipts.`,
      door: "Go to the Certify page",
      recordDoor: "See the certifications on record",
      blockersDoor: "Review the blocking issues",
    },

    /** ---- DQ briefing (data steward leads) ---- */
    dq: {
      heading: "Data-quality queue",
      /** Counts are the server's own, over exactly the rows /dq serves. */
      openLine: (open: string, owned: string) =>
        `${open} open and ${owned} owned issue${owned === "1" ? "" : "s"} in the queue.`,
      blockingLine: (count: string) =>
        `${count} of the unresolved issues ${count === "1" ? "is" : "are"} blocking — ${count === "1" ? "it stops" : "they stop"} certification until resolved.`,
      noBlockingLine: "None of the open issues are blocking. Certification is not being held up by the queue.",
      attestedLine: (count: string) =>
        `${count} issue${count === "1" ? "" : "s"} closed under a recorded statistician attestation.`,
      resolvedLine: (count: string) =>
        `${count} resolved issue${count === "1" ? "" : "s"} on record.`,
      /** Warm empty — a clear queue is a good day, said plainly. */
      empty:
        "The data-quality queue is empty. New gaps and conflicts surface here as pipelines run — none are open right now.",
      door: "Go to the data-quality queue",
    },

    /** ---- safety briefing (certifier + steward) ---- */
    safety: {
      heading: "Safety & security",
      monthCounts: (monthLabel: string, total: string, major: string) =>
        `${total} event${total === "1" ? "" : "s"} recorded for ${monthLabel} — ${major} major.`,
      monthNone: (monthLabel: string) =>
        `No safety events recorded for ${monthLabel}. If the month stays event-free, the zero-event S&S-50 summary is still due — the deadline below covers it.`,
      ss40Line: (count: string) =>
        `${count} S&S-40 major-event report${count === "1" ? "" : "s"} due (30 days from each event).`,
      ss50Line: (count: string, dueDate: string) =>
        `S&S-50 monthly summaries: ${count} mode${count === "1" ? "" : "s"} due by ${dueDate} — zero-event months included.`,
      door: "Go to Safety & security",
    },

    /** ---- report readiness + sampling (report preparer leads) ---- */
    report: {
      heading: "Monthly report readiness",
      /** measuresWithFigures of measuresTotal is a workflow tally over
       *  which measures have any figure — never a sum of figures. */
      readiness: (monthLabel: string, have: string, total: string) =>
        `${have} of the ${total} monthly report measures (VRM, VRH, UPT, VOMS) have a computed figure for ${monthLabel}.`,
      empty: (monthLabel: string) =>
        `No ${monthLabel} figures have been computed yet for the monthly report measures. The report preview and exports fill in as the pipeline runs.`,
      door: "Open the monthly ridership report",
      workbookNote:
        "The agency workbook and CSV/XLSX exports are on the report page — every export carries its provenance column.",
    },
    sampling: {
      heading: "PMT sampling progress",
      planLine: (plan: string) => `Plan ${plan}`,
      progressText: (measured: string, required: string) =>
        `${measured} of ${required} required units measured.`,
      meterLabel: (plan: string) => `Sampling progress for plan ${plan}`,
      readyTag: "Ready to estimate",
      morePlans: (count: string) =>
        `${count} more plan${count === "1" ? "" : "s"} on the sampling page.`,
      /** Warm empty + the concrete first action. */
      empty:
        "No sampling plans yet. When passenger miles need a statistical sample, the sampling page walks you through creating the first plan — the required sample sizes come straight from the manual's own tables.",
      door: "Go to PMT sampling",
    },

    /** ---- KPI cards (everyone) ---- */
    kpi: {
      heading: "Latest figures",
      intro:
        "The newest computed figure of each kind, with its certification status. Differences are computed by the server in exact arithmetic — this page never subtracts two figures.",
      /** The receipt door ON the figure: the number is the button. */
      receiptToggle: (metric: string, period: string) =>
        `Receipt for ${metric}, ${period}`,
      periodLine: (start: string, end: string) => `${start} to ${end}`,
      /** Names the compared period EXPLICITLY: periods of different
       *  lengths do get compared (the server compares what exists), and
       *  the reader must see that at a glance, not discover it. */
      vsPrevious: (start: string, end: string) =>
        `the previous period (${start} to ${end})`,
      firstFigure:
        "First figure of its kind — nothing earlier to compare against.",
      deltaUnavailable: (message: string) =>
        `The server could not compare this period with the previous one: ${message}`,
      /** Warm empty per metric — no urgency invented. */
      empty: (metric: string) =>
        `No ${metric} figure has been computed yet. When the pipeline runs, the newest figure appears here with its receipt.`,
      emptyAll:
        "No figures have been computed yet — that is the honest state of a fresh Headway, not an error. Once a data source is connected, the first calculation run produces them.",
      /** Handoff 0026: the first action is the Compute figures room, not a
       *  CLI line. Shown to data_steward+ (viewers see emptyAllViewer). */
      emptyAllDoor: "Compute figures",
      emptyAllViewer:
        "Figures are computed from the Compute figures page by a data steward, report preparer, or certifying official.",
      metricsDoor: "See every computed figure",
    },

    /** ---- ops cards (everyone; always badged) ---- */
    ops: {
      heading: "Operations pulse",
      intro:
        "How the service ran, measured from vehicle positions. Operations figures are never NTD reported figures — each carries its badge and its industry-basis receipt.",
      otpLine: (value: string) =>
        `${value}% of observed passages were on time, agency-wide.`,
      cvhLine: (value: string) =>
        `Agency-wide headway adherence (cvh): ${value}. Lower is steadier.`,
      /** Warm empty: ops runs are separate; absence is stated plainly. */
      empty:
        "No operations metrics have been computed yet. They come from a separate ops run and appear here with their receipts when one lands.",
      door: "See the operations dashboard",
    },
  },

  /**
   * The living map (/map — handoff 0024, design point 1). Everything drawn
   * comes from Headway's own API: stops and schematic route lines from the
   * /geometry endpoints, live vehicles from /ops/vehicles/latest. The page
   * makes NO external requests — no tiles, no fonts, no sprites — and every
   * honesty statement the server sends (staleness note, schematic geometry
   * note, ops boundary note) is rendered VERBATIM; only the frame words
   * here are this page's own.
   */
  map: {
    heading: "Live map",
    /** Handoff 0044: the always-visible one-liner. `intro` below moves,
     *  VERBATIM and unshortened, into the "What this shows" disclosure. */
    summary:
      "Positions observed, never interpolated. Nothing on this page is fetched from outside this installation.",
    /** The eyebrow over the hero — what this canvas is. */
    eyebrow: "Network",
    intro:
      "Your system, drawn from your own data: every stop and route from the agency's schedule, and each vehicle's last reported position. Nothing on this page comes from an outside map service — no tiles, no external fonts, and no request ever leaves this installation.",
    /** Handoff 0044: the compact control strip in the map chrome. */
    controls: {
      label: "Map controls",
      /** Named so the disclosure holding the control explanations reads as
       *  being about the controls, not about the figures. */
      explain: "How these controls work",
    },
    /** Handoff 0044: the persistent rail beside the canvas. */
    rail: {
      label: "Map readout",
      noticesLabel: "What the server said about this data",
      readoutHeading: "Fleet readout",
      /** Readout cards — counts of what is on this canvas right now. Each
       *  is the server's own count, shown verbatim, never a figure this
       *  page derived. */
      vehicles: "Vehicles reporting",
      vehiclesUnit: "with a position",
      findings: "Open blocking findings",
      findingsUnit: "need a person",
      modes: "Modes on this map",
      modesUnit: "from schedule data",
      /** Every readout card states the window or scope it counted over. */
      windowReceipt: (label: string) => `Window: ${label}`,
      findingsReceipt: "Scope: open, blocking, whole queue",
      modesReceipt: "Joined from this agency's own routes",
      /** No number yet — said, never drawn as a zero. */
      pending: "—",
      pendingNote: "Not read yet",
    },
    /** The canvas' accessible name; the readable equivalents (chip, counts,
     *  vehicle list) live outside the canvas. */
    canvasLabel:
      "Map of the agency's stops, schematic route lines, and last reported vehicle positions. Use the arrow keys to pan and the plus and minus keys to zoom; the vehicle list below the map carries the same information as text.",
    loading: "Loading the map data…",

    /** ---- the staleness chip: fresh vs quiet, never faked ---- */
    chip: {
      /** Fresh: at least one vehicle reported inside the window. */
      live: (time: string) => `Live — newest position at ${time}`,
      /** Quiet: the feed has gone quiet — said plainly; the server's own
       *  note renders verbatim beside this. The duration is date math on
       *  the server's own two timestamps, never a guess. */
      quiet: (duration: string) =>
        `No vehicle positions in the last ${duration}`,
      /** No position on record at all (a fresh install). */
      none: "No vehicle positions on record",
      /** While a poll is in flight the last honest state stays visible. */
      checking: "Checking for new positions…",
    },
    /** The poll cadence, stated (the endpoint's own guidance: the upstream
     *  feed updates about every 30 seconds). */
    pollNote:
      "Positions refresh about every 20 seconds. A vehicle's dot moves only when a new position is reported — Headway never animates a guess.",
    refresh: "Refresh positions now",
    /** While the refresh is in flight: visible to sighted users too (UAT
     *  2026-07-28: a silent button "doesn't appear to work"). */
    refreshing: "Refreshing…",
    /** "Checked" is the API round-trip, deliberately distinct from data
     *  freshness (the chip): "I looked just now and this is still the
     *  latest" must be visibly different from "nothing happened". */
    lastChecked: (time: string) => `Last checked ${time}.`,
    vehiclesCount: (shown: string) =>
      `${shown} vehicle${shown === "1" ? "" : "s"} with a position in the selected window.`,

    /** ---- the staleness window control ---- */
    window: {
      label: "Show each vehicle's last position from",
      /** Option labels; the value is the max_age_seconds sent. */
      live: "The last 5 minutes (live)",
      hour: "The last hour",
      day: "The last 24 hours",
      note:
        "Widening the window shows the LAST KNOWN position of each vehicle inside it — useful when the feed is quiet. Every vehicle states how old its position is, and a dot never moves without a new report.",
    },

    /** ---- legend (the schematic honesty is VISIBLE here) ---- */
    legend: {
      heading: "What the map shows",
      stops: "Stop (from the agency's schedule data)",
      routes: "Route line — schematic",
      vehicles: "Vehicle's last reported position",
      /** Lead-in only: the server's geometry_note renders verbatim after. */
      schematicIntro: "About the route lines, in the server's own words:",
    },

    /** ---- vehicle details (click a dot, or pick from the list) ---- */
    vehicle: {
      panelHeading: (id: string) => `Vehicle ${id}`,
      close: "Close vehicle details",
      /** age_seconds verbatim from the response that carried the vehicle. */
      ageLine: (seconds: string) =>
        `Position as of ${seconds} seconds ago (at the last refresh).`,
      recordedLine: (timestamp: string) => `Reported at ${timestamp}.`,
      routeLine: (routeId: string) => `Route ${routeId}`,
      tripLine: (tripId: string) => `Trip ${tripId}`,
      unassigned:
        "Not assigned to a route or trip in this report — served unassigned, never guessed.",
      sourceLine: (source: string) => `Source feed: ${source}`,
      positionLine: (lat: string, lon: string) =>
        `Position: ${lat}, ${lon}`,
    },

    /** ---- the accessible list equivalent of the dots ---- */
    list: {
      toggle: "List the vehicles",
      heading: "Vehicles in the selected window",
      caption:
        "Each vehicle's last reported position in the selected window — the same information the dots on the map carry.",
      columns: {
        vehicle: "Vehicle",
        route: "Route",
        age: "Position age (seconds)",
        source: "Source",
      },
      unassigned: "Not assigned",
      /** The render cap, STATED (house rule) — nothing silently dropped. */
      cap: (cap: string, total: string) =>
        `Showing the first ${cap} of ${total} vehicles in the window. Nothing is dropped from the map or the counts — narrow the window to shorten the list.`,
      select: (id: string) => `Show vehicle ${id} on the map`,
    },

    /** ---- teaching empty states (handoff 0021 pattern) ---- */
    empty: {
      /** No geometry at all: a fresh install. */
      geometry:
        "No stops or routes to draw yet — the map draws itself from your agency's own schedule data (GTFS static), and none has been ingested. That is the honest state of a fresh Headway, not an error.",
      geometryAction:
        "To draw the system, ingest the agency's GTFS static feed; stops and route lines appear the moment the pipeline lands them.",
      /** No vehicles in window: the server's note renders verbatim above
       *  this teaching line. */
      vehiclesAction:
        "Vehicle dots appear when a live vehicle-positions feed (GTFS-Realtime) is connected and reporting. If a feed is connected and this stays quiet, that silence is worth investigating — it is shown, never papered over.",
    },

    /** Truncation honesty (cap fields from the envelopes), lead-in only —
     *  the server's own note renders verbatim. */
    truncatedIntro: "The server sent a bounded set, in its own words:",

    /**
     * The self-hosted basemap (handoff 0027). The street map is an
     * OpenStreetMap-derived PMTiles archive for THIS agency's own service
     * area, downloaded ONCE by an administrator with stated consent
     * (install.sh --download-basemap) and served from this installation —
     * the map page itself still makes zero external requests. Attribution
     * is non-negotiable (ODbL): the credit is visible on the map whenever
     * street tiles render.
     */
    basemap: {
      /** ON the canvas whenever tiles render (ODbL requires the credit;
       *  Protomaps built the archive format + daily extract source). */
      attribution: "© OpenStreetMap contributors · Protomaps",
      /** Street style — deliberately INDEPENDENT of the app theme (first
       *  agency UAT 2026-07-29: dark streets under dark chrome were hard
       *  to read). Light is the default in both themes; the choice is the
       *  user's and persists in this browser. Handoff 0043 re-authored
       *  BOTH styles against a measured contrast bar, so the note now
       *  says what the dark option actually promises. */
      style: {
        label: "Street style",
        light: "Light",
        dark: "Dark",
        note: "The street background has its own setting, separate from the light/dark theme of the rest of Headway — pick whichever makes streets, routes and vehicles easiest for you to see. Both settings are contrast-checked before release: street lines are held to at least 3:1 against the ground behind them and every place and street name to at least 4.5:1, so the network stays readable either way. Light is the starting point; the dark map is drawn with light streets on a near-black ground for low-light control rooms. Saved in this browser.",
      },
      /** Legend entries for the basemap-present state. */
      legendLine:
        "Street map background — OpenStreetMap data stored on this computer; no request leaves this installation to draw it.",
      /** Names the street style actually drawing and the legibility
       *  promise it keeps (handoff 0043 — the ITS manager's report that a
       *  dark theme buried the streets is answered here, in the legend). */
      legendStyleLine: (styleName: string) =>
        `Street style in use: ${styleName}. Both street styles are drawn by Headway, not taken as-is from the map data, and both are measured before release — street lines to at least 3:1 contrast against the ground they sit on and every name to at least 4.5:1, with a halo behind each name so it never dissolves into the map.`,
      legendCredit:
        "Map data © OpenStreetMap contributors (Open Database License), extracted via Protomaps. Full credit: openstreetmap.org/copyright",
      /** The recorded v0 limitation, stated where people look (sprites are
       *  not vendored; labels use one vendored typeface). */
      legendLimit:
        "This first version shows streets and place names, without point-of-interest icons. Route lines stay schematic — the streets underneath are context, not the path vehicles drive.",
      /** Quiet teaching line — certifying officials only, basemap absent:
       *  names the installer command an administrator would run. */
      teachingAbsent:
        "Want streets under this map? An administrator can add an OpenStreetMap background for your service area — one consented download, stored on this computer — by running: ./install/install.sh --download-basemap",
      /** Fail-loudly: a file exists at /basemap/region.pmtiles but cannot
       *  be used. Stated plainly, never silently ignored. */
      unusable:
        "A basemap file exists on this installation but could not be used: the server did not answer a byte-range request with the expected map-archive format. The map falls back to the plain canvas. An administrator can re-run ./install/install.sh --download-basemap to replace the file.",
    },

    /**
     * Mode-aware vehicle marks (handoff 0043, design point 4).
     *
     * The vehicle-positions feed does not report a mode; the mode shown
     * here is joined from the agency's OWN schedule data through the route
     * the feed named. Every string below has to survive that: the map may
     * never imply it knows a mode it was not told.
     */
    marks: {
      /** Plain-language mode names. They mirror the GTFS Schedule
       *  Reference's routes.txt route_type descriptions (gtfs.org) as the
       *  transform's route_type→mode map applies them — the UI never
       *  invents a mode definition. A mode string outside this list is
       *  shown verbatim rather than renamed. */
      modeLabels: {
        bus: "Bus",
        trolleybus: "Trolleybus",
        rail: "Rail",
        subway: "Subway or metro",
        tram: "Tram, streetcar or light rail",
        monorail: "Monorail",
        ferry: "Ferry",
        cable_tram: "Cable tram",
        funicular: "Funicular",
        aerial_lift: "Aerial lift (gondola or cable car)",
        unknown: "Mode not known",
      } as Record<string, string>,
      legendHeading: "Vehicle marks by mode",
      /** The honesty line under the mode legend: what a mode IS here. */
      legendNote:
        "The position feed does not say what kind of vehicle is reporting. Each mark takes its mode from the agency's own schedule data, through the route the feed named for that vehicle — so the mode is the ROUTE's mode, never a guess about the vehicle.",
      /** Shape before colour, said in words. */
      legendChannels:
        "The shape of a mark is the kind of service; the colour separates modes of the same kind. Nothing on this map is signalled by colour alone — the vehicle list below names every vehicle's mode in words.",
      legendKey: (label: string, glyph: string) => `${glyph} ${label}`,
      /** Vehicles the join could not resolve, counted and explained. */
      unknownNoRoute: (count: string) =>
        `${count} vehicle${count === "1" ? "" : "s"} reported no route, so no mode could be looked up. Drawn as a hollow ring and listed as “not assigned”.`,
      unknownRouteMissing: (count: string) =>
        `${count} vehicle${count === "1" ? "" : "s"} named a route this installation holds no schedule data for, so no mode could be looked up. Drawn as a hollow ring — worth checking, because the feed and the schedule disagree.`,
      /** The list column added for the mode (the readable equivalent). */
      listColumn: "Mode",
      listUnknown: "Not known",
    },

    /**
     * The mode filter (handoff 0043, design point 6). Highlighting only:
     * it repaints what is already on the map and never asks the server
     * again, and it never removes anything from the map or the counts.
     */
    modeFilter: {
      label: "Highlight one mode",
      all: "All modes",
      note: "Highlighting dims the other modes so one stands out. Nothing is removed from the map, the counts, or the list, and nothing is fetched again — this only changes how the map is painted.",
      empty:
        "No route in this agency's schedule data carries a mode yet, so there is nothing to highlight.",
    },

    /**
     * The flagged-findings layer + its accessible entry point (handoff
     * 0043, design points 6 and 7).
     */
    findings: {
      legendKey: "Open blocking data-quality finding",
      /** The single most important honesty line on this surface. */
      legendNote:
        "A data-quality finding has no recorded location — it is about a set of trips, not a place. A flag is drawn ON the schematic line of a route the finding names, so you can find the route; where it sits along that line means nothing.",
      listHeading: "Needs investigation",
      listIntro:
        "Open findings that are blocking a certifiable figure and that nobody has taken on yet. This list is the way to reach every flag from the keyboard — the map canvas itself cannot be read by a screen reader.",
      listEmpty:
        "Nothing is flagged for investigation right now: no open finding is blocking a figure. That is the honest state, not an empty screen.",
      listLoading: "Checking for findings that need a person…",
      /** The meta line under a flag that IS on the map: which route it was
       *  anchored to, and how many other routes it also names. */
      onMap: (label: string) => `Flagged on route ${label} — drawn on the map`,
      onMapAlso: (count: string) =>
        ` · also on ${count} other route${count === "1" ? "" : "s"}`,
      countLine: (flagged: string, drawn: string) =>
        `${flagged} finding${flagged === "1" ? "" : "s"} need a person. ${drawn} of them are drawn on the map.`,
      capNote: (cap: string) =>
        `The map draws at most ${cap} flags at once so the flagged marks stay meaningful. Every finding is in the list above, whether or not it has a flag.`,
      /** Why a finding has no flag — one honest sentence each. */
      gapNoSubject:
        "No flag: this finding is about the calculation run as a whole, not about identifiable trips, so there is no route to anchor it to.",
      gapNoRoute:
        "No flag: this finding's trips are not attributed to any route, so there is no line to anchor it to.",
      gapRouteNotDrawn:
        "No flag: the routes this finding names have no line on this map — the schedule data has no drawn geometry for them.",
      gapOverCap:
        "No flag: the map's flag limit was already reached. The finding is fully readable here.",
      error: (message: string) =>
        `Headway could not load the findings for this map: ${message}`,
    },

    /**
     * The relationship inspector (handoff 0043, design point 7): the
     * finding, and everything the API can honestly connect it to.
     */
    inspector: {
      label: "Finding details",
      heading: (title: string) => title,
      close: "Close finding details",
      /** The visible label; the full sentence above is the accessible name,
       *  so the control is never an unlabeled icon and never a wrapped
       *  three-line block in a narrow panel. */
      closeShort: "Close",
      openedFromMap: "Opened from the map.",
      severityLabel: "Severity",
      statusLabel: "Status",
      raisedLabel: "Raised",
      idLabel: "Finding id",
      chainHeading: "What this finding connects to",
      chainIntro:
        "Everything below was served by Headway — the blocks and routes come from the finding's own record of what it was about, frozen when it was raised, and the calculations are the runs that named this finding themselves. Nothing here is inferred.",
      blocksHeading: "Blocks",
      blockLine: (label: string, trips: string) =>
        `Block ${label} — ${trips} trip${trips === "1" ? "" : "s"}`,
      blockUnnamed: "Trips with no block in the feed",
      blockWindow: (first: string, last: string) =>
        `First departure ${first}; last departure ${last}.`,
      routesHeading: "Routes",
      routeLine: (name: string, mode: string) => `${name} — ${mode}`,
      routeNotDrawn: "no line on this map",
      routeModeUnknown: "mode not known",
      calcsHeading: "Calculations that named this finding",
      calcLine: (calc: string, version: string, metric: string) =>
        `${calc} ${version} — ${metric}`,
      calcOutcomeRefused:
        "The calculation refused to produce this figure over this finding.",
      calcOutcomePersisted:
        "The calculation produced this figure and recorded this finding alongside it.",
      calcPeriod: (start: string, end: string) =>
        `Period ${start} up to (not including) ${end}.`,
      calcsEmpty:
        "No calculation run on record names this finding. That does not mean none did — this page reads the most recent runs only.",
      ownerHeading: "Owner",
      ownerNone:
        "No owner yet. An open finding with no owner is nobody's job until someone takes it — that is what this list is for.",
      ownerNamed: (owner: string) => `Owned by ${owner}.`,
      recordsHeading: "Raw records behind this finding",
      recordsNone:
        "This finding records no source-record ids. Findings raised about a run as a whole often do not have any.",
      recordsLoading: "Loading the raw-record ids…",
      queueLink: "Work this finding in the data-quality queue",
      relatedNote:
        "The routes named above are lit on the map while this panel is open.",
      subjectCapped:
        "The finding's own record of what it covered is capped — it lists a sample of trips, and states the true count beside it. Both are shown exactly as served.",
      unmatchedTrips: (count: string) =>
        `${count} trip${count === "1" ? "" : "s"} in this finding could not be attributed to a block. Counted, never dropped.`,
    },
  },

  /**
   * The first-run guided tour (handoff 0021, design point 3): a hand-rolled,
   * focus-managed overlay that teaches THE THESIS — every number can prove
   * itself. Skippable at every step (button + Escape), keyboard-accessible,
   * restartable from the nav. Plain language throughout.
   */
  tour: {
    label: "Guided tour",
    stepCount: (current: string, total: string) =>
      `Step ${current} of ${total}`,
    next: "Next",
    back: "Back",
    skip: "Skip the tour",
    finish: "Done",
    /** Announced with the panel; also the Escape hint. */
    escapeHint: "Press Escape to leave the tour at any time.",
    steps: {
      today: {
        title: "This page is your briefing",
        body:
          "Today greets you with your agency's situation: the newest figures, what needs attention, and what is due. Nothing here is decoration — every number is shown exactly as the server computed or counted it.",
      },
      receipt: {
        title: "Every number opens into a receipt",
        body:
          "The figure itself is a button. Its receipt shows the coverage behind the number, what was excluded and why, and the flags it carries. A number in Headway is never just a number.",
        /** Honest fallback when the board has no figure yet. */
        noTarget:
          "There is no computed figure on the board yet, so there is no receipt to open right now — but every figure that ever appears here will have one.",
      },
      quote: {
        title: "The federal rule, word for word",
        body:
          "Inside the receipt is the rule the calculation implements — quoted verbatim from the published FTA manual, with its page citation. Headway never paraphrases a rule and never lets a model write one.",
        noTarget:
          "When a figure is on the board, its receipt quotes the exact federal rule it implements, with the page citation.",
      },
      lineage: {
        title: "Walk the number to its raw records",
        body:
          "This is one step of the walk: the figure connects to the computation that produced it, and onward to the immutable raw records it came from. Nothing in between is hidden.",
        noTarget:
          "Every figure carries a “walk this number” door that traces it back to the raw records that produced it.",
      },
      done: {
        title: "Every number here can prove itself",
        body:
          "Now you know how to check: open the receipt, read the rule, walk the lineage. That works on every figure in Headway — and it always will, or the figure refuses to exist.",
      },
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
    logoPresent: "This logo is shown in the header right now:",
    /* Replace/remove (handoff 0025 #3 — the first-UAT report: with a logo
       uploaded, there was no clear way to replace it, and a replacement
       stayed invisible behind the cached URL). The replace flow has its own
       labeled file field and save button; remove exists; and after either,
       the page re-reads GET /branding so the change is visible at once. */
    replaceLogoLabel: "New logo file (SVG or PNG)",
    replaceLogo: "Replace logo",
    logoReplaced: (bytes: string) =>
      `Logo replaced (${bytes} bytes). The header and the preview above now show the new logo.`,
    removeLogo: "Remove logo",
    logoRemoved:
      "The logo has been removed. The header shows the agency name alone.",
    logoUploaded: (bytes: string) =>
      `Logo uploaded (${bytes} bytes). It now appears in the header.`,
    logoAlt: (displayName: string) => `${displayName} logo`,
    currentLogoAlt: "The current agency logo",
    chooseFileFirst: "Choose an SVG or PNG file first, then upload it.",
  },

  /**
   * The admin area (handoff 0025 — built from the first real agency UAT:
   * "Why isn't there an admin page where you can add and connect your data
   * sources, manage users, connect to SSO?"). Honesty rules are binding:
   * the SSO and Updates cards state what exists and what does not — no
   * toggles, no buttons that pretend; the data-sources room has NO
   * add-source form because no add-source API exists.
   */
  admin: {
    heading: "Admin",
    intro:
      "Manage this Headway installation: user accounts, the data sources feeding it, its branding, and its policy settings. Server rules decide what is allowed — this page shows refusals word for word.",
    notAllowed:
      "Only a certifying official can use the admin area. If you need an account changed or a data source connected, ask the person who administers Headway at your agency.",
    backToHub: "Back to Admin",
    cards: {
      users: {
        title: "Users",
        description:
          "Create accounts, reset passwords, change roles, and deactivate or reactivate people. Every change is recorded in the audit trail.",
        link: "Manage users",
      },
      sources: {
        title: "Data sources",
        description:
          "What each connected source has delivered — latest data, recent volume, and anything refused at ingest. Read-only: connecting a source happens on the server today.",
        link: "View data sources",
      },
      branding: {
        title: "Branding",
        description:
          "The agency name, brand colors, and logo shown across the app. Colors that would be unreadable are refused.",
        link: "Edit branding",
      },
      settings: {
        title: "Settings",
        description:
          "The calculation policy knobs — thresholds and windows the calculation runs read. Every change is audited with the old and new value.",
        link: "Edit settings",
      },
      sso: {
        title: "Single sign-on",
        /* This card was an HONEST CARD for weeks: "designed (ADR-0011), not
           built". Handoff 0046 built it, so the card is now real — a live
           status and a way into the configuration below. The honesty rule is
           unchanged: the status line says what is actually true right now,
           and nothing here pretends to work before it has been tested. */
        description:
          "Let people sign in with your agency's own identity provider — Microsoft Entra ID, Google, Okta, or Keycloak. Their accounts, passwords and multi-factor sign-in stay where your IT team already manages them.",
        localAlwaysWorks:
          "Headway accounts keep working alongside single sign-on, always. If your identity provider is unreachable, or the settings below are wrong, you can still sign in here with a Headway username and password.",
        statusNotConfigured: "Not set up yet",
        statusOff: "Set up, but turned off",
        statusOn: "On",
        statusDisabledByServer: "Turned off on the server",
        configure: "Set up single sign-on",
        hide: "Hide single sign-on settings",
        link: "Set up single sign-on",
      },
      updates: {
        title: "Updates",
        /* HONEST CARD: updating happens on the server, by an administrator.
           No update button in a browser — a web session must never be able
           to replace the software it runs in (same reasoning family as the
           SSO card: nothing pretends, nothing acts from here). */
        body: [
          "Updating Headway happens on the server, by an administrator — not from this page. Depending on how this installation was set up, it follows either the source code or signed releases.",
          "On the server, an administrator runs one of these in the Headway folder:",
        ],
        commandSourceLabel: "Installations that follow the source code:",
        commandSource: "./install/install.sh --update-from-source",
        commandReleaseLabel: "Installations that follow signed releases:",
        commandRelease:
          "./install/install.sh --check-updates   (then --upgrade to apply)",
        whyNoButton:
          "There is deliberately no update button here: a web session must never be able to replace the software it runs in.",
        status: "Updated on the server by an administrator",
      },
    },

    /* ------------------------------------------------------------------
       Single sign-on (handoff 0046). Written for someone who has never
       configured OIDC and has no database access: every field says where
       to find its value, and every refusal says what to do next.
       ------------------------------------------------------------------ */
    sso: {
      heading: "Single sign-on",
      intro:
        "Headway signs people in directly against your identity provider. You register Headway there once, paste three values here, then say which of your groups gets which Headway role.",
      loadError: "Could not load the single sign-on settings.",
      /* Role names live here rather than in the shared label list, so this
         screen owns its own words (Wave F does not edit shared blocks). */
      roleLabels: {
        viewer: "Viewer",
        data_steward: "Data steward",
        report_preparer: "Report preparer",
        certifying_official: "Certifying official",
        auditor: "Auditor",
      } as Record<string, string>,
      settingsHeading: "Your identity provider",
      discoveryLabel: "Discovery address",
      discoveryHint:
        "The address your provider publishes for its own settings. It almost always ends in /.well-known/openid-configuration. Microsoft Entra ID: use the one containing your tenant id, not the shared 'common' address.",
      clientIdLabel: "Application (client) id",
      clientIdHint:
        "The id your provider gave Headway when you registered it as an application.",
      clientSecretLabel: "Client secret",
      clientSecretHintUnset:
        "The secret your provider gave Headway. It is stored encrypted and never shown again — keep your own copy until sign-in works.",
      clientSecretHintSet:
        "A client secret is stored. Leave this blank to keep it. Type a new one only to replace it — Headway cannot show you the stored one, because it is encrypted and never displayed again.",
      clientSecretPlaceholderSet: "Stored — leave blank to keep it",
      clientSecretUnavailable:
        "This server has nowhere safe to keep a secret yet, so Headway will refuse to save one. Ask whoever runs the server to set HEADWAY_SECRET_ENCRYPTION_KEY (or HEADWAY_SECRET_ENCRYPTION_KEY_FILE) and restart Headway.",
      redirectLabel: "Sign-in return address",
      redirectHint:
        "Where your provider sends people back to after they sign in. Register this exact address at your provider — every character must match, including https:// and the path.",
      groupsClaimLabel: "Group claim",
      groupsClaimHint:
        "The name of the field your provider uses to list a person's groups. Entra ID, Okta and Keycloak usually call it 'groups'; some installations use 'roles' or 'wids'. Whatever yours is called, type it here — nothing is assumed.",
      usernameClaimLabel: "Username field",
      usernameClaimHint:
        "The field Headway reads to get a person's name. Usually 'preferred_username'; Entra ID installations sometimes use 'upn'. This is the name that appears in the audit trail beside everything they do.",
      skewLabel: "Clock difference allowed (seconds)",
      skewHint:
        "How far apart this server's clock and your provider's clock may be before a sign-in is refused. 120 seconds suits almost everyone. Raise it only if sign-ins fail with clock errors — the real fix is to run a time service on this server.",
      caBundleLabel: "Certificate authority file (optional)",
      caBundleHint:
        "Leave blank unless your network inspects encrypted traffic. If it does, put your organisation's certificate file on the Headway server and give its full path here. Headway will not skip certificate checking: that would let anyone on the network impersonate your provider.",
      buttonLabelLabel: "Words on the sign-in button",
      buttonLabelHint:
        "What staff will see on the sign-in page — for example 'Sign in with County SSO'.",
      enabledLabel: "Turn single sign-on on",
      enabledHint:
        "Leave this off until the test below passes. Turning it on only adds a button to the sign-in page; Headway usernames and passwords keep working either way.",
      save: "Save settings",
      saved: "Settings saved.",
      test: "Test this configuration",
      testing: "Testing…",
      testHeading: "Test results",
      testIntro:
        "Headway just did everything a real sign-in does, short of opening your provider's sign-in page: it read your provider's settings, read its signing keys, and proved your client id and secret are accepted. Nobody was signed in.",
      testPassed: "Everything Headway can check by itself is working.",
      testFailed:
        "Something is not right yet. Each step below says what to do about it.",
      stepOk: "Working",
      stepFailed: "Needs attention",
      mappingsHeading: "Who gets which role",
      mappingsIntro:
        "A person is allowed in only if one of their groups appears below. If none of them do, they are refused and no account is created for them — Headway never guesses. Use the groups your directory already has; there is no group Headway expects to find, and no name it requires.",
      mappingsEmpty:
        "No groups are mapped yet. Until at least one is, every single sign-on attempt is refused and no accounts are created.",
      mappingsTable: {
        claim: "Group from your provider",
        role: "Headway role",
        note: "Note",
        addedBy: "Added by",
        actions: "Actions",
      },
      addMappingHeading: "Add a group",
      claimValueLabel: "Group value",
      claimValueHint:
        "Exactly as your provider sends it — no wildcards, and capital letters matter. Microsoft Entra ID usually sends a group's object id (a long code); Okta and Keycloak usually send the group's name.",
      /* An EXAMPLE, labelled as one. Deliberately a name an agency might
         already have in its own directory, and deliberately NOT anything
         that looks like a naming convention this product requires: use the
         groups you already have, do not create new ones for us. */
      claimValueExample:
        "Example: transit-data-stewards — but use whatever your groups are already called. Headway does not require any particular naming, and you never need to create a group for it.",
      claimValuePlaceholder: "your-directory-group-name",
      mappingRoleLabel: "Headway role for this group",
      mappingRoleHint:
        "What everyone in this group may do in Headway. 'Auditor' can read everything and change nothing.",
      noteLabel: "Note (optional)",
      noteHint:
        "For your own reference — for example 'Finance team' beside a group code that means nothing to a human.",
      addMapping: "Add group",
      mappingAdded: (claim: string, role: string) =>
        `Anyone in '${claim}' will sign in as a ${role} from now on.`,
      removeMapping: "Remove",
      removeMappingLabel: (claim: string) => `Remove the mapping for ${claim}`,
      mappingRemoved: (claim: string) =>
        `'${claim}' no longer grants any access. Accounts it already created are unchanged — manage them under Users.`,
      certifyingOfficialNote:
        "Certifying official is deliberately missing from this list. Certifying is a legal attestation that figures sent to the federal government are correct, so who may do it is decided here in Headway and recorded in Headway's audit trail — not by a group membership changed elsewhere. Map people to another role here, then make the specific people who certify into certifying officials under Users. They still sign in through your identity provider.",
      /* Was an honest "not wired up yet" note while the sign-in screen had
         no button. The sign-in screen has one now, so the note says what
         turning single sign-on on actually changes for staff — including
         the half that does not change. */
      loginButtonLive:
        "While single sign-on is on, the sign-in page shows this button under the Headway username and password fields. Both ways in keep working: nobody is forced through your identity provider, and a Headway password is still the way back in if this configuration ever stops working.",
    },

    users: {
      heading: "Users",
      intro:
        "Everyone who can sign in to this Headway installation. Passwords are stored only as one-way hashes; nobody — including administrators — can read one back.",
      loadError: "Headway could not load the user list.",
      table: {
        caption: "User accounts on this Headway installation",
        username: "Username",
        role: "Role",
        status: "Status",
        created: "Created",
        actions: "Actions",
      },
      statusActive: "Active",
      statusDeactivated: "Deactivated",
      youMarker: (username: string) => `${username} (you)`,
      create: {
        heading: "Add a user",
        usernameLabel: "Username",
        usernameHint:
          "Letters, numbers, dots, hyphens or underscores — no spaces.",
        roleLabel: "Role",
        passwordLabel: "Temporary password",
        passwordHint:
          "At least 8 characters. Share it with the person privately; they cannot change it themselves yet, but you can reset it here any time.",
        submit: "Create user",
        created: (username: string, roleLabel: string) =>
          `Account '${username}' created as ${roleLabel}.`,
      },
      resetPassword: {
        button: (username: string) => `Reset password for ${username}`,
        buttonShort: "Reset password",
        passwordLabel: (username: string) =>
          `New password for ${username}`,
        submit: "Save new password",
        cancel: "Cancel",
        done: (username: string) =>
          `Password for '${username}' has been reset. Share the new password privately.`,
      },
      role: {
        label: (username: string) => `Role for ${username}`,
        submit: "Change role",
        /** The server's note (session keeps its old role briefly) renders
         *  verbatim beside this confirmation. */
        changed: (username: string, roleLabel: string) =>
          `'${username}' is now a ${roleLabel}.`,
      },
      deactivate: {
        button: (username: string) => `Deactivate ${username}`,
        buttonShort: "Deactivate",
        /** Client-side statement of the SERVER's lockout fail-safe, shown
         *  at the aria-disabled control. Clicking still asks the server,
         *  whose refusal renders verbatim — the server is the rule. */
        lastAdminReason:
          "This is the last active certifying official. Headway refuses to deactivate or demote the last one, so the agency can never lock itself out. Make another account a certifying official first.",
        done: (username: string) => `'${username}' has been deactivated.`,
      },
      reactivate: {
        button: (username: string) => `Reactivate ${username}`,
        buttonShort: "Reactivate",
        done: (username: string) =>
          `'${username}' has been reactivated. They sign in with the password they already had.`,
      },
    },

    sources: {
      heading: "Data sources",
      intro:
        "What this Headway installation has actually received, per source and connector — straight from the ingest record. Read-only by design.",
      loadError: "Headway could not load the data-source status.",
      asOf: (timestamp: string) => `As of ${timestamp} (server clock).`,
      table: {
        caption: "Data delivered per source and connector",
        source: "Source",
        connector: "Connector",
        latest: "Latest data",
        inWindow: (hours: number) => `Received (last ${hours} h)`,
        refused: (hours: number) => `Refused (last ${hours} h)`,
        total: "Received (all time)",
        refusedTotal: "Refused (all time)",
      },
      refusedHint:
        "“Refused” rows failed parsing and were quarantined loudly — Headway never drops data silently.",
      canonicalHeading: "Live feed freshness",
      teaching: {
        heading: "How connecting works today",
        /* The honest teaching panel (binding: no fake add-source form).
           The API's connecting_note renders verbatim above these. */
        items: [
          "Real-time and schedule feeds (GTFS, GTFS-Realtime): set the feed URLs in the deployment's .env file on the server.",
          "Passenger counts (APC / TIDES): drop export files into the watched folder on the server, or push them over the machine-key API.",
          "Vendor exports (SQL Server, data lakes, vendor files): the vendor adapters convert them; machine keys authenticate pushes.",
          "The step-by-step guide, including machine keys, is docs/connecting-your-data.md in your Headway installation.",
        ],
      },
    },

    blockLabels: {
      title: "Block names",
      description:
        "Findings name a block the way your GTFS feed does, which is often an internal number nobody says out loud. Upload your scheduling system's trip-to-block export and Headway will use your run board's names instead.",
      link: "Upload block names",

      heading: "Block names",
      intro:
        "Your GTFS feed identifies each block with an internal id. Your dispatchers, drivers and run board use a different name for the same block. Upload the export that lists both and Headway will show the name your staff actually use.",
      notAllowed:
        "Only a certifying official can load block names, because these names appear on findings an auditor reads.",

      howToHeading: "Getting the file out of your scheduling system",
      howTo: [
        "Run the query your Headway contact gave you against your scheduling database. It returns two columns: the trip name and the block name.",
        "In the results grid, right-click and choose Save Results As, then save it as a CSV file.",
        "Upload that file below. A header row is fine, and an extra column such as the service day is ignored.",
      ],
      excelWarning:
        "Do not open the file in Excel before uploading it. Excel silently turns block names like 1-1 into dates (1-Jan), and Headway cannot tell a real name from a mangled one — so a name it changed would end up on a federal report.",

      fileLabel: "Your trip-to-block export",
      fileHint:
        "A CSV file: trip name in the first column, block name in the second. Up to 16 MB.",
      chooseFirst: "Choose a file first.",
      previewButton: "Check this file",
      previewBusy: "Reading the file…",
      loadButton: "Save these block names",
      loadBusy: "Saving…",
      startOver: "Upload a different file",

      resultHeading: "What is in this file",
      readLabel: "Rows read",
      matchedLabel: "Rows matched to a scheduled trip",
      ambiguousLabel: "Rows matching more than one block",
      unmatchedLabel: "Rows with no matching scheduled trip",
      unparseableLabel: "Rows whose trip name could not be read",
      derivedLabel: "Blocks that would be named",
      derivedLabelSaved: "Blocks now named",
      conflictsLabel: "Blocks two rows disagreed about",

      nothingToSave:
        "No block names could be derived from this file, so there is nothing to save. The rows below say why.",
      partialNote: (derived: number, read: number) =>
        `${derived} block ${derived === 1 ? "name" : "names"} came out of ${read} rows. A partial mapping is normal and safe: blocks Headway could not name keep the id your feed uses, and no name is ever guessed.`,

      scheduleDateLabel: "Which schedule period does this export cover? (optional)",
      scheduleDateHint:
        "Your GTFS feed holds every schedule period at once, so a service day like 'Saturday Service' can match more than one of them. Naming any date inside the period this export covers tells Headway which one you mean. Leave it blank to start — the report below will say if it would have helped.",
      scheduleDateNudge:
        "Some service days below could not be matched to a schedule period. If this export covers one particular period, enter a date inside it above and check the file again.",

      serviceDaysHeading: "How your service days were used",
      serviceDaysIntro:
        "Your file names a service day on each row. Where Headway could tell which schedule a service day refers to, it used it to separate blocks that run the same route at the same time on different days. Where it could not, it says so and nothing was narrowed — the rows were treated exactly as they would have been without the column.",
      serviceDayUsed: "Used",
      serviceDayNotUsed: "Not used",
      columnServiceDay: "Service day",
      columnUsed: "Used to separate blocks",
      columnTripsNamed: "Trips it names",
      columnWhy: "Why",
      serviceDayTrips: (n: number) =>
        `${n.toLocaleString("en-US")} trip${n === 1 ? "" : "s"} named`,

      conflictsHeading: "Blocks left out because two rows disagreed",
      conflictsIntro:
        "Each of these blocks was given more than one name in your file. Headway leaves them out rather than picking one, because the wrong name on a finding is worse than no name.",

      problemsHeading: "Rows Headway could not use",
      capNote: (cap: number) =>
        `The counts above are complete. Only the first ${cap} examples of each kind are listed here.`,
      columnLine: "Line",
      columnTrip: "Trip name",
      columnBlock: "Block name",
      columnReason: "Why it was left out",

      whatHappensNext:
        "Saving affects findings raised from now on. Findings already raised keep the names they were raised with — Headway does not rewrite history.",

      // The last mile. Saving the mapping changes NOTHING a person can see
      // until a calculation runs and they open the right screen, and the
      // first operator to use this went looking on the certification screen
      // — where block names do not appear and never will. Saying "findings
      // raised from here on" was true and useless; it named neither the
      // screen nor the step.
      nextStepsHeading: "Two more steps before you see the new names",
      nextSteps: [
        "Run the calculation for the period you are working on. Block names attach to findings when they are raised, so a finding that already exists keeps the name it was raised with.",
        "Then open Data Quality. This is the only screen that shows block names — they do not appear on the certification screens, which report figures rather than the buses behind them.",
      ],
      nextStepsCalcLink: "Go to Calculations",
      nextStepsDqLink: "Go to Data Quality",
      nextStepsNoData:
        "If nothing new appears after a calculation run, check Data sources first — a block name can only reach a finding that something raised, and no finding is raised from data that never arrived.",
      loadError: "Headway could not read that file.",
    },

    settings: {
      heading: "Settings",
      intro:
        "The policy knobs this installation's calculations read, each with its basis. Changing one is an audited act — the old and new values are recorded, and the next calculation run uses the new value. Values are shown exactly as stored.",
      brandingNote:
        "Branding (agency name, colors, logo) has its own room — see Branding in Admin.",
      loadError: "Headway could not load the settings.",
      valueLabel: (key: string) => `Value for ${key}`,
      save: (key: string) => `Save ${key}`,
      saved: (key: string, value: string) =>
        `'${key}' is now ${value}. The change is recorded in the audit trail; the next calculation run reads it.`,
      updatedBy: (by: string, at: string) => `Last changed by ${by} on ${at}.`,
      sandboxHint:
        "Want to see what a change would do before making it? Model it in the Settings sandbox first — it changes nothing.",
      sandboxLink: "Open the Settings sandbox",
    },
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
      /** Teaching empty state (handoff 0021 #4): warm + first action,
       *  role-aware (the steward's action vs the reader's orientation). */
      empty:
        "No events recorded yet — an empty log is a good month, stated plainly. Events stay here permanently once recorded: corrections add a new record instead of changing an old one.",
      emptyActionSteward:
        "When something happens, record it with the form above — the classifier answers with the federal rule it applied, word for word.",
      emptyActionReader:
        "A data steward records events; each one appears here with the federal rule its classification came from, word for word.",
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
      /** Teaching empty state (handoff 0021 #4): warm + first action,
       *  role-aware (stewards create; everyone else reads). */
      empty:
        "No sampling plans yet — nothing needs sampling until passenger miles call for a statistical estimate.",
      emptyActionSteward:
        "Create the first plan above: it takes a minute, and the required sample sizes come straight from the manual's own tables — you never pick a number.",
      emptyActionReader:
        "A data steward creates the first plan; everything they record — draws, seeds, measurements — becomes readable here.",
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
