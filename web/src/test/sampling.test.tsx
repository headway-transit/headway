/**
 * /sampling (handoff 0012, design point 3) — MOCK-BASED verification, typed
 * against services/api routers/sampling.py's request/response models
 * exactly (the backend was built in parallel; the fixtures' regulatory
 * strings and figures are the real sampling_v0 / router text and output,
 * extracted programmatically when the fixtures were generated).
 *
 * Held lines:
 * - the wizard's vocabulary comes from GET /sampling/options (only the
 *   units Table 41.01 allows per mode are offered; non-creatable options
 *   cannot be picked), the calc's §41.01/§41.03 eligibility guidance is
 *   rendered VERBATIM, and the manual's §41.07(c) options are quoted;
 * - creating a plan ends in the required per-period AND annual sizes
 *   VERBATIM with the calc's table citation as a receipt;
 * - each period's worksheet carries the RECORDED seed and the verbatim
 *   §63.03 rule; observed figures render verbatim (trailing zeros kept);
 * - progress is the API's (counts, undersampled verdict, citations);
 *   under target the estimate button stays off with the reason AT the
 *   button (aria-disabled — clicks and Enter are refused, never sent);
 * - the estimate receipt shows the calc's figures VERBATIM (expansion
 *   factor × sample APTL, both sides quoted: §83.01/§83.05/§83.07), the
 *   fixed sampled-estimate provenance label, and the API's citations and
 *   caveats verbatim. THE PAGE NEVER COMPUTES.
 */

import { describe, expect, it } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import type { RouteHandler } from "./helpers";
import {
  samplingDrawCreatedQ1,
  samplingDrawsCr,
  samplingEstimate,
  samplingFinalMeasurement,
  samplingMeasurementsCr,
  samplingOptions,
  samplingPlanCr,
  samplingPlanMb,
  samplingPlanMbCreated,
  samplingProgressComplete,
  samplingProgressUnder,
} from "./fixtures";

const CR_LABEL =
  "2026 — Commuter rail (CR), one-way car trips — Averaging option (APTL, without route grouping), quarterly";
const MB_LABEL =
  "2026 — Bus (MB), one-way trips — Averaging option (APTL, without route grouping), monthly";

/** The one drawn-but-unmeasured unit in the under-target fixtures. */
const PENDING_UNIT = samplingProgressUnder.units_unmeasured[0];

function mockSampling(overrides: Record<string, RouteHandler> = {}) {
  return mockApi({
    "GET /sampling/options": { status: 200, body: samplingOptions },
    "GET /sampling/plans": { status: 200, body: [] },
    ...overrides,
  });
}

/** Routes for the active CR plan's per-card detail (progress/draws/
 *  measurements), one unit short of its required 32. */
function crPlanRoutes(): Record<string, RouteHandler> {
  return {
    "GET /sampling/plans": { status: 200, body: [samplingPlanCr] },
    [`GET /sampling/plans/${samplingPlanCr.plan_id}/progress`]: {
      status: 200,
      body: samplingProgressUnder,
    },
    [`GET /sampling/plans/${samplingPlanCr.plan_id}/draws`]: {
      status: 200,
      body: samplingDrawsCr,
    },
    [`GET /sampling/plans/${samplingPlanCr.plan_id}/measurements`]: {
      status: 200,
      body: samplingMeasurementsCr,
    },
  };
}

describe("/sampling", () => {
  it("shows the honest-scope banner, the calc's retention note verbatim, the eligibility guidance verbatim, and the §41.07(c) options quoted — with non-creatable options unpickable", async () => {
    signInAs("data_steward");
    mockSampling();
    renderApp("/sampling");

    expect(
      await screen.findByRole("heading", { name: "PMT sampling" }),
    ).toBeInTheDocument();

    // Honest scope: deferred tiers + the statistician workflow stated.
    expect(
      screen.getByText(/Alpha preview — not certified for submission/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /their estimation \(Sampling Manual Section 70\) is deferred/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /qualified statistician \(§57\) is your agency's own workflow/,
      ),
    ).toBeInTheDocument();

    // The ≥3-year retention rule (design point 2): the CALC's own note,
    // served by GET /sampling/options and shown verbatim.
    expect(
      screen.getByText(samplingOptions.retention_note),
    ).toBeInTheDocument();

    // Eligibility: the calc's guidance strings VERBATIM — §41.01 and
    // §41.03 quoted inside them.
    const wizard = await screen.findByRole("region", {
      name: "Plan a sample",
    });
    for (const guidance of samplingOptions.eligibility_guidance) {
      expect(within(wizard).getByText(guidance)).toBeInTheDocument();
    }
    expect(wizard).toHaveTextContent(
      "no longer have the original raw sample data.",
    );
    expect(wizard).toHaveTextContent(
      "You should not use it again if your next report year is your mandatory sampling year.",
    );

    // The efficiency options: plain-language explanations (APTL SAYS it
    // requires a 100% UPT count), the §41.07(c) rule quoted with its
    // citation, and the non-creatable grouped option unpickable.
    expect(wizard).toHaveTextContent(
      "This option REQUIRES a 100% count of unlinked passenger trips",
    );
    expect(wizard).toHaveTextContent(
      "cannot yet run the Base-option estimate (Sampling Manual Section 70 is deferred",
    );
    expect(wizard).toHaveTextContent(
      "(2) APTL Option – you must report a 100% count of UPT, estimate the average passenger trip length (APTL) through random sampling",
    );
    expect(wizard).toHaveTextContent(
      "§41.07(c) — FTA NTD Sampling Manual, March 31, 2009, p. 4",
    );
    expect(
      screen.getByLabelText("Averaging option (APTL, without route grouping)"),
    ).toBeChecked();
    expect(screen.getByLabelText("Base option")).not.toBeDisabled();
    expect(
      screen.getByLabelText("Averaging option with route grouping"),
    ).toBeDisabled();

    await expectNoAxeViolations();
  });

  it("keeps reading open to viewers while planning, drawing, measuring, and estimating stay role-gated", async () => {
    signInAs("viewer");
    mockSampling(crPlanRoutes());
    renderApp("/sampling");

    await screen.findByRole("heading", { name: "PMT sampling" });

    // Viewers read the plan, its receipt, and every worksheet…
    expect(
      screen.getByText(
        /Only a data steward or above can create sampling plans/,
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("region", {
        name: `Plan receipt for ${CR_LABEL}`,
      }),
    ).toHaveTextContent("Required sample size: 32 units for the year.");
    expect(
      await screen.findByRole("region", {
        name: "Ride-checker worksheet — 2026-Q1",
      }),
    ).toBeInTheDocument();

    // …but get no write controls (UX only — the API enforces the roles).
    expect(
      screen.queryByRole("button", { name: "Create this plan" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Draw this period's sample" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Record this measurement" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Run the estimate" }),
    ).not.toBeInTheDocument();
    // The estimate gate is stated, not hidden.
    expect(
      screen.getByText(/Only a report preparer or above can run the estimate/),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("offers only the units the API's Table 41.01 vocabulary allows for the picked mode", async () => {
    signInAs("data_steward");
    mockSampling();
    const user = userEvent.setup();
    renderApp("/sampling");

    await screen.findByRole("heading", { name: "Plan a sample" });
    const mode = screen.getByLabelText("Which mode are you sampling?");
    const unit = screen.getByLabelText(
      "What is one sampled unit of service?",
    ) as HTMLSelectElement;

    // Bus: one-way trips or round trips (Table 41.01), nothing else.
    await user.selectOptions(mode, "MB");
    expect(
      within(unit).getByRole("option", { name: "One-way trips" }),
    ).toBeInTheDocument();
    expect(
      within(unit).getByRole("option", { name: "Round trips" }),
    ).toBeInTheDocument();
    expect(
      within(unit).queryByRole("option", { name: "Vehicle-days" }),
    ).not.toBeInTheDocument();

    // Commuter rail has exactly one unit — it is selected for you.
    await user.selectOptions(mode, "CR");
    expect(unit.value).toBe("one_way_car_trips");

    // Back to bus: the CR-only unit is CLEARED, never silently submitted.
    await user.selectOptions(mode, "MB");
    expect(unit.value).toBe("");

    await expectNoAxeViolations();
  });

  it("refuses an invalid wizard client-side, in plain language, without calling the API", async () => {
    signInAs("data_steward");
    const calls = mockSampling();
    const user = userEvent.setup();
    renderApp("/sampling");

    await screen.findByRole("heading", { name: "Plan a sample" });
    await user.click(screen.getByRole("button", { name: "Create this plan" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The plan was not created.");
    expect(alert).toHaveTextContent("Pick which mode you are sampling.");
    expect(alert).toHaveTextContent("Pick who operates this service.");
    expect(alert).toHaveTextContent(
      "Pick what one sampled unit of service is.",
    );
    expect(alert).toHaveTextContent("Pick how often you will sample.");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("creates a plan with the contract body and ends in the size receipt: BOTH sizes verbatim, the calc's table citation, its guidance, and the quoted p. 149 floor", async () => {
    signInAs("data_steward");
    let plansBody = [] as (typeof samplingPlanMb)[];
    const calls = mockSampling({
      "GET /sampling/plans": () => ({ status: 200, body: plansBody }),
      "POST /sampling/plans": () => {
        plansBody = [samplingPlanMb];
        return { status: 201, body: samplingPlanMbCreated };
      },
      [`GET /sampling/plans/${samplingPlanMb.plan_id}/progress`]: {
        status: 200,
        body: {
          ...samplingProgressUnder,
          plan: samplingPlanMb,
          draws: [],
          units_selected: 0,
          units_measured: 0,
          units_unmeasured: [],
        },
      },
      [`GET /sampling/plans/${samplingPlanMb.plan_id}/draws`]: {
        status: 200,
        body: [],
      },
      [`GET /sampling/plans/${samplingPlanMb.plan_id}/measurements`]: {
        status: 200,
        body: [],
      },
    });
    const user = userEvent.setup();
    renderApp("/sampling");

    await screen.findByRole("heading", { name: "Plan a sample" });
    // The report year defaults to the current year; type an explicit one.
    const year = screen.getByLabelText(
      "Which NTD report year is this plan for?",
    );
    await user.clear(year);
    await user.type(year, "2026");
    await user.selectOptions(
      screen.getByLabelText("Which mode are you sampling?"),
      "MB",
    );
    await user.selectOptions(
      screen.getByLabelText("Who operates this service?"),
      "DO",
    );
    await user.selectOptions(
      screen.getByLabelText("What is one sampled unit of service?"),
      "one_way_trips",
    );
    await user.selectOptions(
      screen.getByLabelText("How often will you sample?"),
      "monthly",
    );
    await user.click(screen.getByRole("button", { name: "Create this plan" }));

    // The toast confirmation (handoff 0017 #4) carries the size the CALC
    // served, verbatim.
    expect(await screen.findByRole("log")).toHaveTextContent(
      "Required sample size, from the manual's table: 324 units for the year.",
    );

    // The POST body matches the router's PlanCreate exactly.
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/sampling/plans");
    expect(post?.body).toEqual({
      report_year: 2026,
      mode: "MB",
      type_of_service: "DO",
      unit: "one_way_trips",
      efficiency_option: "aptl",
      frequency: "monthly",
    });

    // The receipt: BOTH sizes verbatim (per-period AND annual are the
    // manual's own rows), the calc's citation verbatim, the selector
    // version named, the calc's guidance verbatim, and the p. 149
    // estimation floor quoted with its citation.
    const wizard = screen.getByRole("region", { name: "Plan a sample" });
    const receipt = within(wizard).getByRole("region", {
      name: `New plan receipt for ${MB_LABEL}`,
    });
    expect(receipt).toHaveTextContent(
      "Required sample size: 324 units for the year.",
    );
    expect(receipt).toHaveTextContent("27 units per monthly period");
    expect(receipt).toHaveTextContent(samplingPlanMb.table_citation);
    expect(receipt).toHaveTextContent("Sizes looked up by sampling_v0 0.1.0");
    for (const guidance of samplingPlanMbCreated.guidance) {
      expect(within(receipt).getByText(guidance)).toBeInTheDocument();
    }
    expect(receipt).toHaveTextContent(
      "Minimum confidence of 95 percent; and Minimum precision level of ±10 percent,",
    );
    expect(receipt).toHaveTextContent(
      "Estimation floor — 2026 NTD Full Reporting Policy Manual, p. 149",
    );

    // The API is the record: the plans list was re-read after the POST.
    const gets = calls.filter(
      (c) => c.method === "GET" && c.path === "/sampling/plans",
    );
    expect(gets.length).toBe(2);

    await expectNoAxeViolations();
  });

  it("draws one period's sample (blank lines dropped; blank seed omitted so the API generates and records one) and shows the worksheet with the seed and the verbatim §63.03 rule", async () => {
    signInAs("data_steward");
    let detail = {
      progress: {
        ...samplingProgressUnder,
        draws: [] as typeof samplingProgressUnder.draws,
        units_selected: 0,
        units_measured: 0,
        units_unmeasured: [] as string[],
      },
      draws: [] as typeof samplingDrawsCr,
      measurements: [] as typeof samplingMeasurementsCr,
    };
    const calls = mockSampling({
      "GET /sampling/plans": { status: 200, body: [samplingPlanCr] },
      [`GET /sampling/plans/${samplingPlanCr.plan_id}/progress`]: () => ({
        status: 200,
        body: detail.progress,
      }),
      [`GET /sampling/plans/${samplingPlanCr.plan_id}/draws`]: () => ({
        status: 200,
        body: detail.draws,
      }),
      [`GET /sampling/plans/${samplingPlanCr.plan_id}/measurements`]: () => ({
        status: 200,
        body: detail.measurements,
      }),
      [`POST /sampling/plans/${samplingPlanCr.plan_id}/draws`]: () => {
        detail = {
          progress: {
            ...samplingProgressUnder,
            draws: [samplingProgressUnder.draws[0]],
            units_selected: 8,
            units_measured: 0,
            units_unmeasured: [...samplingDrawsCr[0].selected_units],
          },
          draws: [samplingDrawsCr[0]],
          measurements: [],
        };
        return { status: 201, body: samplingDrawCreatedQ1 };
      },
    });
    const user = userEvent.setup();
    renderApp("/sampling");

    await screen.findByRole("region", { name: "Draw a period's sample" });
    await user.type(
      screen.getByLabelText("Which period is this draw for?"),
      "2026-Q1",
    );
    // Bulk paste (the realistic gesture for a period's unit list) with a
    // blank line that must be dropped, and NO seed — the API generates one.
    fireEvent.change(
      screen.getByLabelText(
        "Service units expected this period (one per line)",
      ),
      {
        target: {
          value:
            "2026-Q1/car-trip-01\n2026-Q1/car-trip-02\n   \n2026-Q1/car-trip-03\n",
        },
      },
    );
    await user.click(
      screen.getByRole("button", { name: "Draw this period's sample" }),
    );

    expect(await screen.findByRole("log")).toHaveTextContent(
      "The sample for 2026-Q1 is drawn: 8 units were selected at random, without replacement.",
    );

    // The POST body: trimmed, blank-line-free unit list; NO seed key (the
    // API generates and records one); no oversample key at 0.
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(`/sampling/plans/${samplingPlanCr.plan_id}/draws`);
    expect(post?.body).toEqual({
      period_label: "2026-Q1",
      service_units: [
        "2026-Q1/car-trip-01",
        "2026-Q1/car-trip-02",
        "2026-Q1/car-trip-03",
      ],
    });

    // The worksheet: the RECORDED seed on the sheet, the frame size, the
    // §63.03 rule WORD FOR WORD with its citation, the drawn units in draw
    // order, and the drawer named with its version.
    const worksheet = await screen.findByRole("region", {
      name: "Ride-checker worksheet — 2026-Q1",
    });
    expect(worksheet).toHaveTextContent(
      `Random seed recorded for reproducibility: ${samplingDrawsCr[0].seed}`,
    );
    expect(worksheet).toHaveTextContent(
      "Drawn from the period's full list of 20 service units.",
    );
    expect(worksheet).toHaveTextContent(
      "(2) sampling under the method is without replacement. Without replacement means that the method will not select the same service unit more than once.",
    );
    expect(worksheet).toHaveTextContent(
      "§63.03 — FTA NTD Sampling Manual, March 31, 2009, p. 19",
    );
    // Draw order held: the first row is the drawer's first selection.
    const rows = within(worksheet).getAllByRole("row");
    expect(rows[1]).toHaveTextContent(samplingDrawsCr[0].selected_units[0]);
    expect(rows[1]).toHaveTextContent("Not yet measured");
    expect(worksheet).toHaveTextContent("Drawn by dsteward");
    expect(worksheet).toHaveTextContent("using sampling_v0 0.1.0");

    // The drawer's documented procedure (DrawCreated.method), verbatim.
    expect(screen.getByText(samplingDrawCreatedQ1.method)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Print the worksheets" }),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("states progress from the API (counts, per-draw lines, the undersampling citation verbatim) and keeps the estimate button off with the reason at the button — clicks and Enter are refused, never sent", async () => {
    signInAs("report_preparer");
    const calls = mockSampling(crPlanRoutes());
    const user = userEvent.setup();
    renderApp("/sampling");

    await screen.findByRole("heading", { name: "Sample progress" });

    // Progress as TEXT (the API's counts) plus an accessible meter and the
    // per-draw lines.
    expect(
      screen.getAllByText("31 of 32 required units measured.").length,
    ).toBeGreaterThan(0);
    // Two meters now: the in-row plan progress bar (handoff 0017 #3) and
    // the progress panel's meter — both value+label text, never bar-alone.
    expect(screen.getAllByRole("meter").length).toBeGreaterThan(1);
    expect(
      screen.getByText("2026-Q4: 7 of 8 drawn units measured"),
    ).toBeInTheDocument();

    // The API's own no-undersampling citation, verbatim (p. 149 quotes
    // inside it).
    expect(
      screen.getByText(samplingProgressUnder.undersampling_citation),
    ).toBeInTheDocument();

    // Measured units render VERBATIM on the worksheet (trailing zeros).
    const worksheet = screen.getByRole("region", {
      name: "Ride-checker worksheet — 2026-Q1",
    });
    expect(within(worksheet).getAllByText("112.40").length).toBeGreaterThan(0);

    // Reason-at-button: aria-disabled (focusable, perceivable), with the
    // under-target reason stated exactly where the user is looking.
    const button = screen.getByRole("button", { name: "Run the estimate" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(
      screen.getByText(/only 31 of 32 required units are measured/),
    ).toBeInTheDocument();

    // A pointer click AND a keyboard Enter both land and are refused —
    // no POST leaves the browser.
    await user.click(button);
    button.focus();
    await user.keyboard("{Enter}");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    // Typing the expansion factor does not unlock an under-target sample.
    await user.type(
      screen.getByLabelText("Annual 100% boarding count (UPT)"),
      "12750000",
    );
    expect(button).toHaveAttribute("aria-disabled", "true");

    await expectNoAxeViolations();
  });

  // Long test (form typing + full estimate receipt): headroom under load.
  it("records the last measurement (observed PMT stays a decimal string), reaches target, and runs the §83 estimate into a receipt with both sides quoted and the sampled-estimate provenance kept distinct", { timeout: 15000 }, async () => {
    signInAs("report_preparer");
    let detail = {
      progress: samplingProgressUnder,
      measurements: samplingMeasurementsCr,
    };
    const calls = mockSampling({
      ...crPlanRoutes(),
      [`GET /sampling/plans/${samplingPlanCr.plan_id}/progress`]: () => ({
        status: 200,
        body: detail.progress,
      }),
      [`GET /sampling/plans/${samplingPlanCr.plan_id}/measurements`]: () => ({
        status: 200,
        body: detail.measurements,
      }),
      [`POST /sampling/plans/${samplingPlanCr.plan_id}/measurements`]: () => {
        detail = {
          progress: samplingProgressComplete,
          measurements: [...samplingMeasurementsCr, samplingFinalMeasurement],
        };
        return {
          status: 201,
          body: {
            measurement: samplingFinalMeasurement,
            source_caveat:
              "Sample observations are MANUALLY ENTERED ride-check data.",
            retention_note: samplingOptions.retention_note,
            audit_event_id: 74,
          },
        };
      },
      [`POST /sampling/plans/${samplingPlanCr.plan_id}/estimate`]: {
        status: 200,
        body: samplingEstimate,
      },
    });
    const user = userEvent.setup();
    renderApp("/sampling");

    await screen.findByRole("heading", { name: "Record a measurement" });
    await user.selectOptions(
      screen.getByLabelText("Which selected unit was measured?"),
      PENDING_UNIT,
    );
    await user.type(screen.getByLabelText("Boardings observed (UPT)"), "30");
    await user.type(
      screen.getByLabelText("Passenger miles observed (PMT)"),
      "141.00",
    );
    await user.selectOptions(
      screen.getByLabelText("What type of service day was it? (optional)"),
      "Weekday",
    );
    await user.click(
      screen.getByRole("button", { name: "Record this measurement" }),
    );

    expect(await screen.findByRole("log")).toHaveTextContent(
      `Measurement recorded for ${PENDING_UNIT}.`,
    );
    // The measurement body: observed UPT a whole count, observed PMT a
    // decimal STRING with its trailing zeros intact, the day type sent.
    const measurementPost = calls.find(
      (c) =>
        c.method === "POST" &&
        c.path === `/sampling/plans/${samplingPlanCr.plan_id}/measurements`,
    );
    expect(measurementPost?.body).toEqual({
      unit_id: PENDING_UNIT,
      observed_upt: 30,
      observed_pmt: "141.00",
      service_day_type: "Weekday",
    });

    // Target met: the sample is stated complete, and the only remaining
    // reason at the estimate button is the missing expansion factor.
    expect(
      await screen.findByText(/Every drawn unit has a recorded observation/),
    ).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Run the estimate" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(
      screen.getByText(
        /The estimate is off until you enter the annual 100% boarding count/,
      ),
    ).toBeInTheDocument();

    // Supplying the 100% UPT count arms the button.
    await user.type(
      screen.getByLabelText("Annual 100% boarding count (UPT)"),
      "12750000",
    );
    expect(button).not.toHaveAttribute("aria-disabled");
    await user.click(button);

    expect(await screen.findByRole("log")).toHaveTextContent(
      "The estimate is computed.",
    );
    const estimatePost = calls.find(
      (c) =>
        c.method === "POST" &&
        c.path === `/sampling/plans/${samplingPlanCr.plan_id}/estimate`,
    );
    // The expansion factor stays a decimal STRING end to end (the router's
    // EstimateRequest body exactly).
    expect(estimatePost?.body).toEqual({ annual_upt_100pct: "12750000" });

    // The estimate receipt: every figure the CALC's output verbatim, both
    // sides of "expansion factor × sample APTL" quoted (§83.01 / §83.05 /
    // §83.07), the fixed provenance label, and the API's citations and
    // caveats verbatim.
    const receipt = screen.getByRole("region", {
      name: `Estimate receipt for ${CR_LABEL}`,
    });
    expect(within(receipt).getByText("Sampled estimate")).toBeInTheDocument();
    expect(receipt).toHaveTextContent(
      "57375000 passenger miles (annual, sampled estimate).",
    );
    expect(receipt).toHaveTextContent(
      "This is a sampled estimate with estimation provenance. It is not a computed passenger-miles figure",
    );
    // The calc's fixed provenance label, verbatim.
    expect(receipt).toHaveTextContent(samplingEstimate.estimate.method);
    // Both components, verbatim figures.
    expect(receipt).toHaveTextContent(
      "100% boarding count (the expansion factor, §83.01)",
    );
    expect(within(receipt).getByText("12750000")).toBeInTheDocument();
    expect(receipt).toHaveTextContent(
      "Sample average passenger trip length (sample APTL, §83.05)",
    );
    expect(within(receipt).getByText("4.50")).toBeInTheDocument();
    expect(within(receipt).getByText("805")).toBeInTheDocument();
    expect(within(receipt).getByText("3625.40")).toBeInTheDocument();
    expect(receipt).toHaveTextContent("32 of 32");
    // The §83 rules, word for word, with their citations.
    expect(receipt).toHaveTextContent(
      "(a) You must use your 100% count of UPT as the expansion factor.",
    );
    expect(receipt).toHaveTextContent(
      "§83.01(a)/(b) — FTA NTD Sampling Manual, March 31, 2009, p. 42",
    );
    expect(receipt).toHaveTextContent(
      "(b) You must not determine the sample APTL as the average of the APTL across individual service units in the sample.",
    );
    expect(receipt).toHaveTextContent(
      "§83.05 — FTA NTD Sampling Manual, March 31, 2009, p. 42",
    );
    expect(receipt).toHaveTextContent(
      "you should multiply your sample APTL for the entire annual sample with your corresponding annual expansion factor",
    );
    // The API's citations and caveats, verbatim.
    for (const citation of samplingEstimate.citations) {
      expect(within(receipt).getByText(citation)).toBeInTheDocument();
    }
    for (const caveat of samplingEstimate.caveats) {
      expect(within(receipt).getByText(caveat)).toBeInTheDocument();
    }

    await expectNoAxeViolations();
  });

  it("tells a data steward the estimate is report_preparer+ — stated, not hidden", async () => {
    signInAs("data_steward");
    mockSampling(crPlanRoutes());
    renderApp("/sampling");

    await screen.findByRole("heading", { name: "Sample progress" });
    expect(
      screen.queryByRole("button", { name: "Run the estimate" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Only a report preparer or above can run the estimate/),
    ).toBeInTheDocument();
    // Measurement entry is still theirs.
    expect(
      screen.getByRole("button", { name: "Record this measurement" }),
    ).toBeInTheDocument();
  });

  it("shows an API refusal verbatim and leaves the estimate form standing", async () => {
    signInAs("report_preparer");
    const refusal =
      "This plan requires 32 measured units for the year but only 31 have " +
      "observations on file. Headway refuses to estimate from an " +
      "undersampled plan.";
    mockSampling({
      ...crPlanRoutes(),
      [`GET /sampling/plans/${samplingPlanCr.plan_id}/progress`]: {
        status: 200,
        body: samplingProgressComplete,
      },
      [`GET /sampling/plans/${samplingPlanCr.plan_id}/measurements`]: {
        status: 200,
        body: [...samplingMeasurementsCr, samplingFinalMeasurement],
      },
      [`POST /sampling/plans/${samplingPlanCr.plan_id}/estimate`]: {
        status: 422,
        body: { detail: refusal },
      },
    });
    const user = userEvent.setup();
    renderApp("/sampling");

    await screen.findByRole("heading", { name: "Run the estimate" });
    await user.type(
      screen.getByLabelText("Annual 100% boarding count (UPT)"),
      "12750000",
    );
    await user.click(screen.getByRole("button", { name: "Run the estimate" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(refusal);
    // No receipt appears for a refused estimate.
    expect(
      screen.queryByRole("region", { name: /^Estimate receipt/ }),
    ).not.toBeInTheDocument();
  });

  it("shows an in-row progress bar per plan (text + meter, never bar-alone) with the estimate-ready state visually distinct", async () => {
    // Under target: the bar rides the API's counts; no ready tag.
    signInAs("viewer");
    mockSampling(crPlanRoutes());
    renderApp("/sampling");

    const rowMeter = await screen.findByRole("meter", {
      name: /Sampling progress for 2026/,
    });
    // Value + label TEXT first (the API's counts verbatim in the sentence).
    expect(rowMeter.closest(".row-progress")).toHaveTextContent(
      "31 of 32 required units measured.",
    );
    expect(screen.queryByText("Ready to estimate")).not.toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("marks a plan whose sample reached its required size as Ready to estimate", async () => {
    signInAs("viewer");
    mockSampling({
      ...crPlanRoutes(),
      [`GET /sampling/plans/${samplingPlanCr.plan_id}/progress`]: {
        status: 200,
        body: samplingProgressComplete,
      },
      [`GET /sampling/plans/${samplingPlanCr.plan_id}/measurements`]: {
        status: 200,
        body: [...samplingMeasurementsCr, samplingFinalMeasurement],
      },
    });
    renderApp("/sampling");

    const rowMeter = await screen.findByRole("meter", {
      name: /Sampling progress for 2026/,
    });
    const row = rowMeter.closest(".row-progress") as HTMLElement;
    expect(row).toHaveTextContent("32 of 32 required units measured.");
    // The distinct ready state: tag + class — the label carries the
    // meaning, never color alone.
    expect(within(row).getByText("Ready to estimate")).toBeInTheDocument();
    expect(row.className).toContain("ready");
    await expectNoAxeViolations();
  });
});
