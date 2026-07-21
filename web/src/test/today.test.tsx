/**
 * /today — the role-aware briefing home (handoff 0021, design point 1).
 * Pinned:
 *  - post-login landing: "/" redirects to /today and the nav links it;
 *  - role-aware composition: the certifying official leads with
 *    certification state + safety deadlines, the data steward with the DQ
 *    queue, the report preparer with report readiness + sampling
 *    progress, the viewer goes straight to the figures — and each role's
 *    briefing fetches ONLY what its cards need (an unrouted fetch fails
 *    the test loudly);
 *  - the handoff-0017 counts endpoints are consumed (server-side counts,
 *    never a downloaded queue);
 *  - EVERY figure keeps its receipt door (the figure is a button that
 *    discloses the full Receipt, with the lineage walk link inside);
 *  - deltas are the server's signed strings verbatim (GET /metrics/compare)
 *    and their absence is stated, never blank;
 *  - empty cards are warm honest statements — no invented urgency;
 *  - axe reports zero violations, cards loaded and skeletons alike.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RouteHandler } from "./helpers";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import {
  opsCvhAgencyValue,
  opsOtpAgencyValue,
  samplingPlanCr,
  samplingProgressUnder,
  signedCertificationRecord,
  uptValue,
  vrmValue,
  vrhValue,
  certifiedValue,
} from "./fixtures";
import type { MetricValue } from "../api/types";

/** Pin "today" so month math is stable no matter when the suite runs. */
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-07-20T12:00:00Z"));
  // The tour auto-offers on a first visit; these tests cover the page, so
  // mark it seen (tour.test.tsx covers the tour itself).
  window.localStorage.setItem("headway-tour-seen", "1");
});
afterEach(() => {
  vi.useRealTimers();
});

/** A July VRM figure (the current pinned month) awaiting certification. */
const julyVrm: MetricValue = {
  ...vrmValue,
  metric_value_id: "mv-vrm-jul",
  period_start: "2026-07-01",
  period_end: "2026-07-31",
  value: "13000.10",
  computed_at: "2026-08-01T06:00:00Z",
};

const dqCountsOpen = {
  total: 1000,
  by_severity: { blocking: 4, warning: 300, info: 696 },
  by_status: { open: 1000 },
};
const dqCountsOwned = {
  total: 200,
  by_severity: { blocking: 2, warning: 100, info: 98 },
  by_status: { owned: 200 },
};
const dqCountsAttested = {
  total: 10,
  by_severity: { warning: 10 },
  by_status: { attested: 10 },
};
const dqCountsResolved = {
  total: 30,
  by_severity: { blocking: 5, warning: 25 },
  by_status: { resolved: 30 },
};

/** Counts endpoint handler: the status filter picks the body. An
 *  UNFILTERED call fails the test loudly — the live 41k-issue queue made
 *  the unfiltered count a ~5s query, so /today must never issue one. */
const dqCountsRoute: RouteHandler = (call) => {
  const status = new URL(call.url, "http://x").searchParams.get("status");
  const body =
    status === "open"
      ? dqCountsOpen
      : status === "owned"
        ? dqCountsOwned
        : status === "attested"
          ? dqCountsAttested
          : status === "resolved"
            ? dqCountsResolved
            : null;
  if (body === null) {
    throw new Error(
      "Unfiltered GET /dq/issues/counts from /today (must be per-status)",
    );
  }
  return { status: 200, body };
};

const safetyCounts = {
  total: 3,
  by_classification: { major: 1, non_major: 2 },
  unclassified: 0,
  superseded: 0,
};

const deadlines = {
  month: "2026-07",
  ss40: [
    {
      event_id: "ev-1",
      occurred_at: "2026-07-02T08:00:00Z",
      mode: "bus",
      event_category: "collision",
      due_date: "2026-08-01",
    },
  ],
  ss40_citation: "cite",
  ss40_note: "note",
  ss50: [
    {
      month: "2026-07",
      mode: "bus",
      due_date: "2026-08-31",
      non_major_event_count: 2,
      zero_event: false,
    },
    {
      month: "2026-07",
      mode: "ferry",
      due_date: "2026-08-31",
      non_major_event_count: 0,
      zero_event: true,
    },
  ],
  ss50_citation: "cite",
};

/** The server's compare response for the July-vs-March VRM pair. */
const compareRoute: RouteHandler = (call) => {
  const metric = new URL(call.url, "http://x").searchParams.get("metric");
  return {
    status: 200,
    body: {
      metric,
      unit: "miles",
      comparands: [
        { index: 0, period_start: "2026-03-01", period_end: "2026-03-31" },
        { index: 1, period_start: "2026-07-01", period_end: "2026-07-31" },
      ],
      scopes: ["agency"],
      rows: [
        {
          scope: "agency",
          cells: [
            { comparand_index: 0, value: vrmValue },
            {
              comparand_index: 1,
              value: julyVrm,
              delta_vs_baseline: "654.50",
              delta_vs_previous: "654.50",
            },
          ],
        },
      ],
      directions: { vrm: null },
      direction_note: "note",
      delta_note: "note",
      mixed_certification: false,
      mixed_certification_note: null,
    },
  };
};

const baseValues = [
  julyVrm,
  vrmValue,
  vrhValue,
  uptValue,
  certifiedValue,
  opsOtpAgencyValue,
  opsCvhAgencyValue,
];

describe("/today (the briefing home)", () => {
  it("is the landing redirect and leads the nav", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [] },
    });
    renderApp("/");
    expect(
      await screen.findByRole("heading", { name: "Today" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Today" })).toBeInTheDocument();
  });

  it("composes the certifying official's briefing: certification state + blockers + safety, every tally with its door", async () => {
    signInAs("certifying_official");
    mockApi({
      "GET /metrics/values": { status: 200, body: baseValues },
      "GET /metrics/compare": compareRoute,
      "GET /certifications": {
        status: 200,
        body: [signedCertificationRecord],
      },
      "GET /dq/issues/counts": dqCountsRoute,
      "GET /safety/events/counts": { status: 200, body: safetyCounts },
      "GET /safety/deadlines": { status: 200, body: deadlines },
    });
    renderApp("/today");

    // The lead card: this month's uncertified figures + blockers, counted
    // server-side (open 4 + owned 2 blocking), each line with its door.
    expect(
      await screen.findByText(
        "July 2026 figures: 1 computed and not yet certified.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/6 blocking data-quality issues open/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Review the blocking issues" }),
    ).toHaveAttribute("href", "/dq");
    expect(screen.getByText("1 certification on record.")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Go to the Certify page" }),
    ).toHaveAttribute("href", "/certify");

    // Safety: the month tallies from /safety/events/counts + deadlines.
    expect(
      screen.getByText("3 events recorded for July 2026 — 1 major."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/1 S&S-40 major-event report due/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/S&S-50 monthly summaries: 2 modes due by 2026-08-31/),
    ).toBeInTheDocument();

    // The steward's DQ card does NOT lead this briefing.
    expect(screen.queryByText("Data-quality queue")).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("composes the data steward's briefing from the counts endpoints — the queue is counted, never downloaded", async () => {
    signInAs("data_steward");
    const calls = mockApi({
      "GET /metrics/values": { status: 200, body: baseValues },
      "GET /metrics/compare": compareRoute,
      "GET /dq/issues/counts": dqCountsRoute,
      "GET /safety/events/counts": { status: 200, body: safetyCounts },
      "GET /safety/deadlines": { status: 200, body: deadlines },
    });
    renderApp("/today");

    expect(
      await screen.findByText("1,000 open and 200 owned issues in the queue."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/6 of the unresolved issues are blocking/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("10 issues closed under a recorded statistician attestation."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Go to the data-quality queue" }),
    ).toHaveAttribute("href", "/dq");

    // BINDING: the briefing consumed /dq/issues/counts and NEVER fetched
    // the issue list itself.
    expect(calls.some((c) => c.path === "/dq/issues/counts")).toBe(true);
    expect(calls.some((c) => c.path === "/dq/issues")).toBe(false);
    // And no certifications fetch — that slice is the official's.
    expect(calls.some((c) => c.path === "/certifications")).toBe(false);

    await expectNoAxeViolations();
  });

  it("composes the report preparer's briefing: report readiness + sampling progress (covered via mocks — no live demo user for this role)", async () => {
    signInAs("report_preparer");
    mockApi({
      "GET /metrics/values": { status: 200, body: baseValues },
      "GET /metrics/compare": compareRoute,
      "GET /sampling/plans": { status: 200, body: [samplingPlanCr] },
      [`GET /sampling/plans/${samplingPlanCr.plan_id}/progress`]: {
        status: 200,
        body: samplingProgressUnder,
      },
    });
    renderApp("/today");

    // Readiness is a workflow tally over WHICH measures have a July
    // figure (only VRM here) — never a sum of figures.
    expect(
      await screen.findByText(
        "1 of the 4 monthly report measures (VRM, VRH, UPT, VOMS) have a computed figure for July 2026.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open the monthly ridership report" }),
    ).toHaveAttribute("href", "/reports/monthly");

    // Sampling progress: the API's counts through the house RowProgress.
    expect(
      await screen.findByText("31 of 32 required units measured."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Go to PMT sampling" }),
    ).toHaveAttribute("href", "/sampling");

    await expectNoAxeViolations();
  });

  it("gives the viewer the figures with no workflow cards — and fetches nothing role-gated", async () => {
    signInAs("viewer");
    const calls = mockApi({
      "GET /metrics/values": { status: 200, body: baseValues },
      "GET /metrics/compare": compareRoute,
    });
    renderApp("/today");

    expect(await screen.findByText("Latest figures")).toBeInTheDocument();
    expect(screen.queryByText("Certification")).not.toBeInTheDocument();
    expect(screen.queryByText("Data-quality queue")).not.toBeInTheDocument();
    // The viewer's briefing touched ONLY the metrics endpoints.
    const paths = new Set(calls.map((c) => c.path));
    expect(paths.has("/dq/issues/counts")).toBe(false);
    expect(paths.has("/safety/deadlines")).toBe(false);
    expect(paths.has("/certifications")).toBe(false);
  });

  it("keeps the receipt door on every figure: the KPI figure discloses its full Receipt with the lineage walk inside", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: baseValues },
      "GET /metrics/compare": compareRoute,
    });
    renderApp("/today");

    // The figure verbatim IS the button (trailing zero preserved).
    const figureButton = await screen.findByRole("button", {
      name: /13000\.10.*Receipt for Vehicle Revenue Miles \(VRM\)/,
    });
    expect(figureButton).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(figureButton);
    expect(figureButton).toHaveAttribute("aria-expanded", "true");

    // The full house Receipt: story line + the walk to raw records.
    const receipt = screen.getByRole("region", {
      name: /Receipt.*Vehicle Revenue Miles/i,
    });
    expect(
      within(receipt).getByRole("link", {
        name: /Walk this number to its raw records/i,
      }),
    ).toHaveAttribute("href", "/metrics/mv-vrm-jul/lineage");

    await expectNoAxeViolations();
  });

  it("shows the SERVER's delta verbatim, sign-neutral, and states a first figure honestly", async () => {
    signInAs("viewer");
    const calls = mockApi({
      "GET /metrics/values": { status: 200, body: baseValues },
      "GET /metrics/compare": compareRoute,
    });
    renderApp("/today");

    // The server's signed string, rendered through the house DeltaFigure.
    expect(
      await screen.findByText(/654\.50 more than the previous period/),
    ).toBeInTheDocument();
    // The compare request carried BOTH periods (server-side arithmetic).
    const compareCall = calls.find((c) => c.path === "/metrics/compare");
    expect(compareCall?.url).toContain("2026-03-01..2026-03-31");
    expect(compareCall?.url).toContain("2026-07-01..2026-07-31");

    // VRH/UPT have no earlier period: the absence is stated, not blank.
    expect(
      screen.getAllByText("First figure of its kind — nothing earlier to compare against.").length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("badges every ops figure and keeps its receipt door", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: baseValues },
      "GET /metrics/compare": compareRoute,
    });
    renderApp("/today");

    expect(await screen.findByText("Operations pulse")).toBeInTheDocument();
    expect(
      screen.getAllByText("Operations metric — not an NTD reported figure")
        .length,
    ).toBeGreaterThanOrEqual(2);
    const otpButton = screen.getByRole("button", {
      name: /54\.10.*Receipt for On-time performance/,
    });
    await userEvent.click(otpButton);
    expect(
      screen.getByText(/The industry basis inside this number/),
    ).toBeInTheDocument();
  });

  it("says an empty board warmly, with the concrete first command — never invented urgency", async () => {
    signInAs("viewer");
    mockApi({ "GET /metrics/values": { status: 200, body: [] } });
    renderApp("/today");

    expect(
      await screen.findByText(/No figures have been computed yet — that is the honest state/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/python -m headway_calc\.runner/),
    ).toBeInTheDocument();
    // No alert, no warning voice: warmth is the binding rule.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("renders skeletons (announced in words) while the briefing loads, and axe passes in the loading state", async () => {
    signInAs("certifying_official");
    // Never-resolving handlers: hold the loading state open.
    mockApi({
      "GET /metrics/values": () => new Promise(() => {}),
      "GET /certifications": () => new Promise(() => {}),
      "GET /dq/issues/counts": () => new Promise(() => {}),
      "GET /safety/events/counts": () => new Promise(() => {}),
      "GET /safety/deadlines": () => new Promise(() => {}),
    });
    renderApp("/today");

    expect(
      await screen.findByRole("heading", { name: "Today" }),
    ).toBeInTheDocument();
    const statuses = screen.getAllByRole("status");
    expect(statuses.length).toBeGreaterThanOrEqual(1);
    expect(statuses[0]).toHaveTextContent("Loading…");
    await expectNoAxeViolations();
  });

  it("coexists with themed branding chrome (handoff 0017 #7): the chrome stamps the shell and the briefing renders untouched", async () => {
    signInAs("viewer");
    mockApi({
      "GET /branding": {
        status: 200,
        body: {
          display_name: "Transit Agency",
          primary: "#1a5fb4",
          accent: "#0b57d0",
          has_logo: false,
          chrome: {
            header_bg: "#0b3d2e",
            header_fg: "#f2fbf7",
            accent: "#7fe0b7",
          },
          chrome_note: "note",
        },
      },
      "GET /metrics/values": { status: 200, body: baseValues },
      "GET /metrics/compare": compareRoute,
    });
    renderApp("/today");

    expect(await screen.findByText("Latest figures")).toBeInTheDocument();
    // The shell applied the server-validated chrome (light mode)…
    await waitFor(() =>
      expect(document.documentElement.getAttribute("data-chrome")).toBe("on"),
    );
    expect(
      document.documentElement.style.getPropertyValue("--chrome-header-bg"),
    ).toBe("#0b3d2e");
    // …and the briefing's cards still carry their receipt doors.
    expect(
      screen.getByRole("button", {
        name: /13000\.10.*Receipt for Vehicle Revenue Miles/,
      }),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("renders a per-card load failure verbatim without taking down the rest of the briefing", async () => {
    signInAs("data_steward");
    mockApi({
      "GET /metrics/values": { status: 200, body: baseValues },
      "GET /metrics/compare": compareRoute,
      "GET /dq/issues/counts": {
        status: 500,
        body: { detail: "The counts query failed." },
      },
      "GET /safety/events/counts": { status: 200, body: safetyCounts },
      "GET /safety/deadlines": { status: 200, body: deadlines },
    });
    renderApp("/today");

    // The DQ card states the failure verbatim…
    expect(
      (await screen.findAllByText("The counts query failed.")).length,
    ).toBeGreaterThanOrEqual(1);
    // …while the figures still render.
    expect(await screen.findByText("Latest figures")).toBeInTheDocument();
  });
});
