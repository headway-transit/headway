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
    metrics: "Metrics",
    dq: "Data quality",
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
    columns: {
      select: "Select",
      metric: "Metric",
      unit: "Unit",
      period: "Period",
      value: "Value",
      calc: "Calculation",
      status: "Certification status",
      provenance: "Provenance",
    },
    selectRow: (metric: string, period: string) =>
      `Select ${metric}, ${period}, for certification`,
    alreadyCertified: "Already certified",
    certifySelected: "Certify selected figures",
    nothingSelected:
      "Select at least one figure to certify. Use the checkboxes in the first column.",
    certifySuccess: (count: number, certificationId: string) =>
      `Certification recorded for ${count} figure${count === 1 ? "" : "s"}. Certification ID ${certificationId}. The API has audit-logged who certified and when.`,
    reviewDqLink: "Review the data-quality issues",
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
  },

  errors: {
    regionLabel: "Error",
  },
} as const;
