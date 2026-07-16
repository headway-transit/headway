import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import type { RecordedCall } from "./helpers";
import type { MetricValue } from "../api/types";
import {
  simulatedUptValue,
  uptValue,
  vrhValue,
  vrmWithCoverage,
} from "./fixtures";
import { copy } from "../copy";
import { monthPeriod } from "../reports/period";

const DISCLAIMER =
  "Preview only. The official NTD Monthly Ridership submission format has " +
  "not yet been verified against FTA's reporting system documentation.";

const certifiedVrm: MetricValue = {
  ...vrmWithCoverage,
  certification_status: "certified",
};

/** Serve fixtures per metric regardless of period (the period FILTERING is
 * the API's job; the test asserts the derived query params instead). */
function mockReportApi(byMetric: Record<string, MetricValue[]>) {
  return mockApi({
    "GET /metrics/values": (call: RecordedCall) => {
      const metric = new URL(call.url, "http://test").searchParams.get(
        "metric",
      );
      return { status: 200, body: byMetric[metric ?? ""] ?? [] };
    },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("monthPeriod (period selection is UI logic)", () => {
  it("derives first/last calendar day, leap years included", () => {
    expect(monthPeriod(2026, 3)).toEqual({
      period_start: "2026-03-01",
      period_end: "2026-03-31",
    });
    expect(monthPeriod(2026, 6)).toEqual({
      period_start: "2026-06-01",
      period_end: "2026-06-30",
    });
    expect(monthPeriod(2024, 2)).toEqual({
      period_start: "2024-02-01",
      period_end: "2024-02-29",
    });
    expect(monthPeriod(2026, 2)).toEqual({
      period_start: "2026-02-01",
      period_end: "2026-02-28",
    });
  });
});

describe("/reports/monthly", () => {
  it("fetches VRM, VRH, and UPT for the picked month and renders them verbatim with mixed certification statuses", async () => {
    signInAs("viewer");
    const calls = mockReportApi({
      vrm: [certifiedVrm],
      vrh: [vrhValue],
      upt: [uptValue],
    });
    renderApp("/reports/monthly");

    const table = await screen.findByRole("table");

    // Exactly one GET per metric, each with a derived calendar-month period.
    const gets = calls.filter((c) => c.path === "/metrics/values");
    expect(gets).toHaveLength(3);
    const metrics = gets.map(
      (c) => new URL(c.url, "http://test").searchParams.get("metric"),
    );
    expect(metrics.sort()).toEqual(["upt", "vrh", "vrm"]);
    for (const call of gets) {
      const params = new URL(call.url, "http://test").searchParams;
      expect(params.get("period_start")).toMatch(/^\d{4}-\d{2}-01$/);
      expect(params.get("period_end")).toMatch(/^\d{4}-\d{2}-(28|29|30|31)$/);
    }

    // Figures verbatim (trailing zeros intact), plain-language units.
    expect(within(table).getByText("12345.60")).toBeInTheDocument();
    expect(within(table).getByText("987.25")).toBeInTheDocument();
    expect(within(table).getByText("41985.90")).toBeInTheDocument();
    expect(
      within(table).getByText("unlinked passenger trips"),
    ).toBeInTheDocument();

    // Mixed certification statuses shown as served.
    expect(within(table).getByText("certified")).toBeInTheDocument();
    expect(within(table).getAllByText("uncertified")).toHaveLength(2);

    // Coverage summary: the vrm coverage sentence; "Not reported" for the
    // detail-less vrh figure; the UPT counted-trips sentence.
    expect(
      within(table).getByText(
        "Covers 91.26% of vehicle-trips; 202 excluded and documented.",
      ),
    ).toBeInTheDocument();
    expect(within(table).getByText("Not reported")).toBeInTheDocument();
    expect(
      within(table).getByText(
        "Passenger counts were recorded on 9032 of 9123 operated trips.",
      ),
    ).toBeInTheDocument();

    // Every figure keeps its provenance path.
    const lineageLinks = within(table).getAllByRole("link", {
      name: /How this number was made/,
    });
    expect(lineageLinks).toHaveLength(3);
    expect(lineageLinks[0]).toHaveAttribute(
      "href",
      `/metrics/${certifiedVrm.metric_value_id}/lineage`,
    );

    // The preview disclaimer is permanently visible.
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument();

    // No simulated figure -> no badge, no report banner.
    expect(screen.queryByTitle(copy.simulated.tooltip)).not.toBeInTheDocument();
    expect(
      screen.queryByText(copy.simulated.reportBanner),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("month picker: keyboard-reachable labeled controls; changing the month refetches with the derived period", async () => {
    signInAs("viewer");
    const calls = mockReportApi({ vrm: [], vrh: [], upt: [] });
    const user = userEvent.setup();
    renderApp("/reports/monthly");

    await screen.findByRole("table");
    const monthSelect = screen.getByLabelText("Month");
    const yearSelect = screen.getByLabelText("Year");

    // Keyboard path: Tab reaches the month picker, then the year picker.
    let reachedMonth = false;
    for (let i = 0; i < 20 && !reachedMonth; i++) {
      await user.tab();
      reachedMonth = document.activeElement === monthSelect;
    }
    expect(reachedMonth).toBe(true);
    await user.tab();
    expect(yearSelect).toHaveFocus();

    // Pick March 2026; the three re-reads carry the derived period.
    await user.selectOptions(
      monthSelect,
      screen.getByRole("option", { name: "March" }),
    );
    await user.selectOptions(
      yearSelect,
      screen.getByRole("option", { name: "2026" }),
    );
    await waitFor(() => {
      const marchCalls = calls.filter((c) =>
        c.url.includes("period_start=2026-03-01"),
      );
      expect(marchCalls).toHaveLength(3);
    });
    for (const call of calls.filter((c) =>
      c.url.includes("period_start=2026-03-01"),
    )) {
      expect(new URL(call.url, "http://test").searchParams.get("period_end")).toBe(
        "2026-03-31",
      );
    }
  });

  it("shows a missing figure as a stated absence, never a silent skip", async () => {
    signInAs("viewer");
    mockReportApi({ vrm: [certifiedVrm], vrh: [], upt: [] });
    renderApp("/reports/monthly");

    const table = await screen.findByRole("table");
    expect(
      within(table).getByText(
        "No Vehicle Revenue Hours (VRH) figure has been computed for this month.",
      ),
    ).toBeInTheDocument();
    expect(
      within(table).getByText(
        "No Unlinked Passenger Trips (UPT) figure has been computed for this month.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the unmissable SIMULATED DATA badge and report banner when any included figure is simulated", async () => {
    signInAs("viewer");
    mockReportApi({
      vrm: [certifiedVrm],
      vrh: [vrhValue],
      upt: [simulatedUptValue],
    });
    renderApp("/reports/monthly");

    await screen.findByRole("table");
    // On the row AND on the report as a whole (badge appears in both).
    expect(screen.getAllByTitle(copy.simulated.tooltip)).toHaveLength(2);
    expect(
      screen.getByText(
        "This report includes at least one figure computed from simulated test data. It must never be submitted.",
      ),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });
});

describe("monthly ridership server export (replaced the client-side CSV, 2026-07-14)", () => {
  it("replaces the client CSV button with the CSV/XLSX server export, states the coverage difference, and saves the served bytes verbatim", async () => {
    signInAs("viewer");
    const csvBody =
      DISCLAIMER +
      "\r\nmetric,unit,period_start,period_end,scope,value,calc_name," +
      "calc_version,certification_status,category,simulated_data," +
      "metric_value_id\r\n";
    const calls = mockApi({
      "GET /metrics/values": (call: RecordedCall) => {
        const metric = new URL(call.url, "http://test").searchParams.get(
          "metric",
        );
        return {
          status: 200,
          body:
            { vrm: [certifiedVrm], vrh: [vrhValue], upt: [uptValue] }[
              metric ?? ""
            ] ?? [],
        };
      },
      "GET /metrics/values/export": {
        status: 200,
        rawBody: csvBody,
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition":
            'attachment; filename="headway-metric-values-served.csv"',
        },
      },
    });
    const captured: Blob[] = [];
    const savedAs: string[] = [];
    URL.createObjectURL = vi.fn((blob: Blob) => {
      captured.push(blob);
      return "blob:headway-test";
    }) as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as typeof URL.revokeObjectURL;
    // jsdom cannot navigate; stop the anchor click from attempting it.
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        savedAs.push(this.download);
      });
    const user = userEvent.setup();
    renderApp("/reports/monthly");

    await screen.findByRole("table");
    // The old client-side assembly is gone: no "preview only" CSV button.
    expect(
      screen.queryByRole("button", { name: "Download CSV (preview only)" }),
    ).not.toBeInTheDocument();
    // What changed is stated out loud, right at the control.
    expect(screen.getByText(copy.report.export.note)).toBeInTheDocument();

    // Scoped to THIS control's group: the workbook export control (handoff
    // 0020) also offers a CSV button on this page.
    const exportControl = screen.getByRole("group", {
      name: copy.report.export.label,
    });
    await user.click(
      within(exportControl).getByRole("button", { name: /Download CSV/ }),
    );
    await waitFor(() => expect(captured).toHaveLength(1));

    // The request is the server export, scoped to the picked month.
    const exportCall = calls.find(
      (c) => c.path === "/metrics/values/export",
    );
    expect(exportCall).toBeDefined();
    const params = new URL(exportCall!.url, "http://test").searchParams;
    expect(params.get("format")).toBe("csv");
    expect(params.get("period_start")).toMatch(/^\d{4}-\d{2}-01$/);
    expect(params.get("period_end")).toMatch(/^\d{4}-\d{2}-(28|29|30|31)$/);
    expect(exportCall!.headers.Authorization).toBe("Bearer test-token");

    // Saved byte for byte under the server's attachment filename, and
    // confirmed through the shell's toast region.
    expect(await captured[0].text()).toBe(csvBody);
    expect(savedAs).toEqual(["headway-metric-values-served.csv"]);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("log")).toHaveTextContent(
      "Download ready: headway-metric-values-served.csv",
    );

    await expectNoAxeViolations();
    clickSpy.mockRestore();
  });
});
