/**
 * The server export controls (handoff 0017, design point 5): the compact
 * CSV + XLSX button pair on /metrics, the MR-20 section, the S&S-50
 * deadlines panel, and each sampling plan's worksheet block.
 *
 * Pinned per surface: the click hits the RIGHT export endpoint with the
 * right query (format, month/period, plan id) and the bearer token; the
 * saved file is the response body BYTE FOR BYTE under the server's
 * Content-Disposition filename; success is confirmed through the shell's
 * toast region (role="log"); an API refusal renders verbatim as an alert
 * and pushes no toast. Axe: zero violations with the control present.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import type { RouteHandler } from "./helpers";
import type { SafetyDeadlines } from "../api/types";
import {
  mr20Package,
  samplingDrawsCr,
  samplingMeasurementsCr,
  samplingOptions,
  samplingPlanCr,
  samplingProgressUnder,
  uptValue,
  vrhValue,
} from "./fixtures";

/** A CSV body distinctive enough that byte-identity is meaningful. */
const CSV_BODY =
  'banner line, with a comma\r\nmetric,value\r\nvrm,"12345.60"\r\n';

/** XLSX bytes are opaque here; any non-CSV byte string proves pass-through. */
const XLSX_BODY = "PKfake-xlsx-bytes";

function exportRoute(filename: string, body: string): RouteHandler {
  return {
    status: 200,
    rawBody: body,
    headers: {
      "Content-Type":
        filename.endsWith(".csv")
          ? "text/csv; charset=utf-8"
          : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "Content-Disposition": `attachment; filename="${filename}"`,
    },
  };
}

/** Capture blob saves: the object-URL + anchor-click dance, observed. */
function captureSaves() {
  const blobs: Blob[] = [];
  const filenames: string[] = [];
  URL.createObjectURL = vi.fn((blob: Blob) => {
    blobs.push(blob);
    return "blob:headway-test";
  }) as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as typeof URL.revokeObjectURL;
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function (this: HTMLAnchorElement) {
      filenames.push(this.download);
    });
  return { blobs, filenames, clickSpy };
}

const minimalDeadlines: SafetyDeadlines = {
  month: "2026-06",
  ss40: [],
  ss40_citation:
    "The S&S-40 Major Event Report is 'due no later than 30 days after " +
    "the date of the event.' (2026 S&S Policy Manual, Exhibit 2, p. 4)",
  ss40_note: "Headway v0 has no NTD submission tracking.",
  ss50: [
    {
      month: "2026-06",
      mode: "bus",
      due_date: "2026-07-31",
      non_major_event_count: 2,
      zero_event: false,
    },
    {
      month: "2026-06",
      mode: "ferry",
      due_date: "2026-07-31",
      non_major_event_count: 0,
      zero_event: true,
    },
  ],
  ss50_citation:
    "The S&S-50 Non-Major Monthly Summary is submitted 'for each mode " +
    "and TOS … every month, even if no event occurs'. (2026 S&S Policy " +
    "Manual, p. 4 + Exhibit 3, p. 5)",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("/metrics — server export control", () => {
  function mockMetrics(exportHandler: RouteHandler) {
    return mockApi({
      "GET /metrics/values": { status: 200, body: [uptValue, vrhValue] },
      "GET /metrics/values/export": exportHandler,
    });
  }

  it("downloads the CSV byte for byte, names it from Content-Disposition, and confirms via the toast region", async () => {
    signInAs("viewer");
    const calls = mockMetrics(
      exportRoute("headway-metric-values.csv", CSV_BODY),
    );
    const { blobs, filenames, clickSpy } = captureSaves();
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /Download CSV/ }));
    await waitFor(() => expect(blobs).toHaveLength(1));

    const call = calls.find((c) => c.path === "/metrics/values/export");
    expect(call).toBeDefined();
    const params = new URL(call!.url, "http://test").searchParams;
    expect(params.get("format")).toBe("csv");
    // The unfiltered table exports unfiltered: no period narrowing.
    expect(params.get("period_start")).toBeNull();
    expect(params.get("period_end")).toBeNull();
    expect(call!.headers.Authorization).toBe("Bearer test-token");

    // Byte-for-byte save under the server's filename.
    expect(await blobs[0].text()).toBe(CSV_BODY);
    expect(filenames).toEqual(["headway-metric-values.csv"]);
    expect(clickSpy).toHaveBeenCalledTimes(1);

    // The confirmation goes through the shell's toast region.
    expect(screen.getByRole("log")).toHaveTextContent(
      "Download ready: headway-metric-values.csv",
    );

    await expectNoAxeViolations();
  });

  it("downloads the XLSX bytes untouched with format=xlsx", async () => {
    signInAs("viewer");
    const calls = mockMetrics(
      exportRoute("headway-metric-values.xlsx", XLSX_BODY),
    );
    const { blobs, filenames } = captureSaves();
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(
      screen.getByRole("button", { name: /Download XLSX \(Excel\)/ }),
    );
    await waitFor(() => expect(blobs).toHaveLength(1));

    const call = calls.find((c) => c.path === "/metrics/values/export");
    expect(
      new URL(call!.url, "http://test").searchParams.get("format"),
    ).toBe("xlsx");
    expect(await blobs[0].text()).toBe(XLSX_BODY);
    expect(filenames).toEqual(["headway-metric-values.xlsx"]);
  });

  it("shows an API refusal verbatim as an alert and pushes no toast", async () => {
    signInAs("viewer");
    mockMetrics({
      status: 500,
      body: { detail: "The export could not be assembled." },
    });
    const { blobs } = captureSaves();
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /Download CSV/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The export could not be assembled.",
    );
    expect(blobs).toHaveLength(0);
    expect(screen.getByRole("log")).not.toHaveTextContent("Download ready");
    await expectNoAxeViolations();
  });
});

describe("MR-20 section — server export control", () => {
  it("hits /reports/mr20/export with the picked month and saves the served bytes", async () => {
    signInAs("viewer");
    const calls = mockApi({
      "GET /metrics/values": { status: 200, body: [] },
      "GET /reports/mr20": { status: 200, body: mr20Package },
      "GET /reports/mr20/export": exportRoute(
        "headway-mr20-preview.csv",
        CSV_BODY,
      ),
    });
    const { blobs, filenames } = captureSaves();
    const user = userEvent.setup();
    renderApp("/reports/monthly");

    await screen.findByRole("group", { name: "Report section" });
    await user.click(screen.getByRole("button", { name: "MR-20 package" }));
    await screen.findByText(mr20Package.banner);

    // Scoped to the MR-20 control's group: the monthly agency workbook
    // control (handoff 0020) also offers a CSV button on this page.
    const mr20Control = screen.getByRole("group", {
      name: "Download the MR-20 package as a spreadsheet",
    });
    await user.click(
      within(mr20Control).getByRole("button", { name: /Download CSV/ }),
    );
    await waitFor(() => expect(blobs).toHaveLength(1));

    const call = calls.find((c) => c.path === "/reports/mr20/export");
    expect(call).toBeDefined();
    const params = new URL(call!.url, "http://test").searchParams;
    expect(params.get("format")).toBe("csv");
    // The picked month, as YYYY-MM (the view defaults to last month).
    expect(params.get("month")).toMatch(/^\d{4}-\d{2}$/);
    expect(await blobs[0].text()).toBe(CSV_BODY);
    expect(filenames).toEqual(["headway-mr20-preview.csv"]);
    expect(screen.getByRole("log")).toHaveTextContent(
      "Download ready: headway-mr20-preview.csv",
    );
    await expectNoAxeViolations();
  });
});

describe("/reports/monthly — monthly agency workbook export control (handoff 0020, CONTRACT-AHEAD)", () => {
  // Built and MOCK-TESTED against the handoff-0020 contract
  // (GET /reports/agency-workbook?month=&format=) while the backend lands
  // the endpoint in a parallel wave. Reconcile against the regenerated
  // openapi.json when it appears; until then the live server's refusal
  // renders verbatim at the control (the error test below is that path).
  function mockReport(workbookHandler: RouteHandler) {
    return mockApi({
      "GET /metrics/values": { status: 200, body: [] },
      "GET /reports/agency-workbook": workbookHandler,
    });
  }

  it("downloads the month's workbook (XLSX) with the picked month, saves the served bytes, and confirms via the toast region", async () => {
    signInAs("viewer");
    const calls = mockReport(
      exportRoute("headway-agency-workbook-2026-06.xlsx", XLSX_BODY),
    );
    const { blobs, filenames } = captureSaves();
    const user = userEvent.setup();
    renderApp("/reports/monthly");

    // The control sits with the month picker and states what the file is
    // — provenance ids per cell, absences stated, never invented.
    const control = await screen.findByRole("group", {
      name: "Download the monthly agency workbook",
    });
    expect(control).toHaveTextContent(
      "A figure Headway has not computed is stated as absent — never invented, never zero-filled.",
    );

    await user.click(
      within(control).getByRole("button", {
        name: /Download XLSX \(Excel\)/,
      }),
    );
    await waitFor(() => expect(blobs).toHaveLength(1));

    const call = calls.find((c) => c.path === "/reports/agency-workbook");
    expect(call).toBeDefined();
    const params = new URL(call!.url, "http://test").searchParams;
    expect(params.get("format")).toBe("xlsx");
    // The picked month, as YYYY-MM (the view defaults to last month).
    expect(params.get("month")).toMatch(/^\d{4}-\d{2}$/);
    expect(call!.headers.Authorization).toBe("Bearer test-token");
    expect(await blobs[0].text()).toBe(XLSX_BODY);
    expect(filenames).toEqual(["headway-agency-workbook-2026-06.xlsx"]);
    expect(screen.getByRole("log")).toHaveTextContent(
      "Download ready: headway-agency-workbook-2026-06.xlsx",
    );
    await expectNoAxeViolations();
  });

  it("downloads the CSV variant via the same grid (format=csv)", async () => {
    signInAs("viewer");
    const calls = mockReport(
      exportRoute("headway-agency-workbook-2026-06.csv", CSV_BODY),
    );
    const { blobs, filenames } = captureSaves();
    const user = userEvent.setup();
    renderApp("/reports/monthly");

    const control = await screen.findByRole("group", {
      name: "Download the monthly agency workbook",
    });
    await user.click(
      within(control).getByRole("button", { name: /Download CSV/ }),
    );
    await waitFor(() => expect(blobs).toHaveLength(1));

    const call = calls.find((c) => c.path === "/reports/agency-workbook");
    expect(
      new URL(call!.url, "http://test").searchParams.get("format"),
    ).toBe("csv");
    expect(await blobs[0].text()).toBe(CSV_BODY);
    expect(filenames).toEqual(["headway-agency-workbook-2026-06.csv"]);
  });

  it("shows the server's refusal verbatim — the honest state while the endpoint has not landed", async () => {
    signInAs("viewer");
    mockReport({ status: 404, body: { detail: "Not Found" } });
    const { blobs } = captureSaves();
    const user = userEvent.setup();
    renderApp("/reports/monthly");

    const control = await screen.findByRole("group", {
      name: "Download the monthly agency workbook",
    });
    await user.click(
      within(control).getByRole("button", { name: /Download CSV/ }),
    );

    expect(await within(control).findByRole("alert")).toHaveTextContent(
      "Not Found",
    );
    expect(blobs).toHaveLength(0);
    expect(screen.getByRole("log")).not.toHaveTextContent("Download ready");
    await expectNoAxeViolations();
  });
});

describe("/safety deadlines panel — S&S-50 server export control", () => {
  it("exports the deadlines month via /reports/ss50/export and states what the file covers", async () => {
    signInAs("viewer");
    const calls = mockApi({
      "GET /safety/events": { status: 200, body: [] },
      "GET /safety/deadlines": { status: 200, body: minimalDeadlines },
      "GET /reports/ss50/export": exportRoute(
        "headway-ss50-2026-06-preview.xlsx",
        XLSX_BODY,
      ),
    });
    const { blobs, filenames } = captureSaves();
    const user = userEvent.setup();
    renderApp("/safety");

    const panel = await screen.findByRole("region", {
      name: "Reporting deadlines",
    });
    // The control names the panel's month and states its coverage
    // (explicit zero-event rows included) right at the buttons.
    expect(
      screen.getByRole("group", {
        name: "Download the S&S-50 summary for June 2026",
      }),
    ).toBeInTheDocument();
    expect(panel).toHaveTextContent("explicit zero-event rows included");

    await user.click(
      screen.getByRole("button", { name: /Download XLSX \(Excel\)/ }),
    );
    await waitFor(() => expect(blobs).toHaveLength(1));

    const call = calls.find((c) => c.path === "/reports/ss50/export");
    expect(call).toBeDefined();
    const params = new URL(call!.url, "http://test").searchParams;
    // The month the API served for the panel — never a client guess.
    expect(params.get("month")).toBe("2026-06");
    expect(params.get("format")).toBe("xlsx");
    expect(await blobs[0].text()).toBe(XLSX_BODY);
    expect(filenames).toEqual(["headway-ss50-2026-06-preview.xlsx"]);
    expect(screen.getByRole("log")).toHaveTextContent(
      "Download ready: headway-ss50-2026-06-preview.xlsx",
    );
    await expectNoAxeViolations();
  });
});

describe("/sampling worksheet — server export control", () => {
  it("exports the plan's worksheet via /sampling/plans/{id}/worksheet", async () => {
    signInAs("data_steward");
    const calls = mockApi({
      "GET /sampling/options": { status: 200, body: samplingOptions },
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
      [`GET /sampling/plans/${samplingPlanCr.plan_id}/worksheet`]:
        exportRoute(
          `headway-sampling-worksheet-${samplingPlanCr.plan_id}.csv`,
          CSV_BODY,
        ),
    });
    const { blobs, filenames } = captureSaves();
    const user = userEvent.setup();
    renderApp("/sampling");

    // The control sits with the print button, once per plan.
    await screen.findByRole("button", { name: "Print the worksheets" });
    await user.click(screen.getByRole("button", { name: /Download CSV/ }));
    await waitFor(() => expect(blobs).toHaveLength(1));

    const call = calls.find((c) =>
      c.path.endsWith(
        `/sampling/plans/${samplingPlanCr.plan_id}/worksheet`,
      ),
    );
    expect(call).toBeDefined();
    expect(
      new URL(call!.url, "http://test").searchParams.get("format"),
    ).toBe("csv");
    expect(await blobs[0].text()).toBe(CSV_BODY);
    expect(filenames).toEqual([
      `headway-sampling-worksheet-${samplingPlanCr.plan_id}.csv`,
    ]);
    expect(screen.getByRole("log")).toHaveTextContent("Download ready");
    await expectNoAxeViolations();
  }, 15000);
});
