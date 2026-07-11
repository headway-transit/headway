/**
 * The MR-20 package section of /reports/monthly (docket #2): the tab fetches
 * GET /reports/mr20 for the picked month, the NOT-REPORTABLE banner and
 * citation render verbatim, the per-mode table shows every value verbatim
 * with its flags (rail pending-D2 included) and every null with its stated
 * reason, the caveats sit behind a disclosure, and the JSON download is the
 * fetched response BYTE FOR BYTE.
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
import type { RecordedCall } from "./helpers";
import { mr20Package } from "./fixtures";

function mockMr20Api() {
  return mockApi({
    // The ridership preview's three metric reads (not under test here).
    "GET /metrics/values": { status: 200, body: [] },
    "GET /reports/mr20": { status: 200, body: mr20Package },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openMr20(calls: RecordedCall[]) {
  const user = userEvent.setup();
  renderApp("/reports/monthly");
  await screen.findByRole("group", { name: "Report section" });
  await user.click(screen.getByRole("button", { name: "MR-20 package" }));
  await waitFor(() =>
    expect(calls.some((c) => c.path === "/reports/mr20")).toBe(true),
  );
  await screen.findByText(mr20Package.banner);
  return user;
}

describe("/reports/monthly — MR-20 package", () => {
  it("is fetched only when its tab is opened, for the picked month (YYYY-MM)", async () => {
    signInAs("viewer");
    const calls = mockMr20Api();
    const user = userEvent.setup();
    renderApp("/reports/monthly");

    await screen.findByRole("group", { name: "Report section" });
    // Not fetched while the preview tab is active.
    expect(calls.some((c) => c.path === "/reports/mr20")).toBe(false);

    const mr20Tab = screen.getByRole("button", { name: "MR-20 package" });
    expect(mr20Tab).toHaveAttribute("aria-pressed", "false");
    await user.click(mr20Tab);
    expect(mr20Tab).toHaveAttribute("aria-pressed", "true");

    await waitFor(() =>
      expect(calls.some((c) => c.path === "/reports/mr20")).toBe(true),
    );
    const first = calls.find((c) => c.path === "/reports/mr20");
    expect(
      new URL(first!.url, "http://test").searchParams.get("month"),
    ).toMatch(/^\d{4}-(0[1-9]|1[0-2])$/);

    // Changing the picked month refetches the package for that month.
    await user.selectOptions(
      screen.getByLabelText("Month"),
      screen.getByRole("option", { name: "March" }),
    );
    await user.selectOptions(
      screen.getByLabelText("Year"),
      screen.getByRole("option", { name: "2026" }),
    );
    await waitFor(() => {
      const months = calls
        .filter((c) => c.path === "/reports/mr20")
        .map((c) => new URL(c.url, "http://test").searchParams.get("month"));
      expect(months).toContain("2026-03");
    });
  });

  it("renders the NOT-REPORTABLE banner prominently, the citation, and the per-mode table with verbatim values, cert badges, the rail pending-D2 flag, and plain-language null reasons", async () => {
    signInAs("viewer");
    const calls = mockMr20Api();
    await openMr20(calls);

    // The package's own banner, verbatim, in the alert pattern.
    const banner = screen.getByText(mr20Package.banner);
    expect(banner.className).toContain("alert");
    // The citation line, verbatim.
    expect(screen.getByText(mr20Package.citation)).toBeInTheDocument();

    const table = screen.getByRole("table", {
      name: /MR-20 package for /,
    });
    // Rows: fleet first, then each mode with its plain-language label.
    expect(
      within(table).getByRole("rowheader", { name: "Fleet (all modes)" }),
    ).toBeInTheDocument();
    expect(
      within(table).getByRole("rowheader", { name: "Bus (MB)" }),
    ).toBeInTheDocument();
    expect(
      within(table).getByRole("rowheader", { name: "Heavy rail (HR)" }),
    ).toBeInTheDocument();

    // Values VERBATIM — trailing zeros intact, never reparsed. VOMS included.
    for (const figure of [
      "41985.90",
      "12345.60",
      "987.25",
      "38",
      "40100.50",
      "900.00",
      "1200.00",
      "87.25",
    ]) {
      expect(within(table).getByText(figure)).toBeInTheDocument();
    }

    // Certification status rides with each figure.
    expect(within(table).getAllByText("certified").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("uncertified").length).toBeGreaterThan(0);

    // The rail pending-D2 flag is surfaced on every flagged cell (the null
    // UPT cell and the three valued rail cells).
    expect(within(table).getAllByText("Pending D-2")).toHaveLength(4);

    // A null cell states its reason in the package's own words — never a
    // silent blank.
    expect(
      within(table).getByText(
        "Rail passenger counts are on hold until the D-2 form definition is verified.",
      ),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("keeps the caveats behind a keyboard-operable disclosure", async () => {
    signInAs("viewer");
    const calls = mockMr20Api();
    await openMr20(calls);

    const toggle = screen.getByRole("button", {
      name: "Caveats (2) — read these before using the package",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByText(mr20Package.caveats[0]),
    ).not.toBeInTheDocument();

    toggle.focus();
    await userEvent.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(mr20Package.caveats[0])).toBeInTheDocument();
    expect(screen.getByText(mr20Package.caveats[1])).toBeInTheDocument();

    await userEvent.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await expectNoAxeViolations();
  });

  it("downloads the package BYTE-IDENTICAL to the fetched response (never re-serialized)", async () => {
    signInAs("viewer");
    const calls = mockMr20Api();
    const captured: Blob[] = [];
    const createObjectURL = vi.fn((blob: Blob) => {
      captured.push(blob);
      return "blob:headway-test";
    });
    URL.createObjectURL = createObjectURL as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as typeof URL.revokeObjectURL;
    // jsdom cannot navigate; stop the anchor click from attempting it.
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const user = await openMr20(calls);

    await user.click(
      screen.getByRole("button", { name: "Download package (JSON)" }),
    );

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(captured[0].type).toContain("application/json");
    // THE load-bearing assertion: the saved bytes are exactly the bytes the
    // API served (the fetch mock serves JSON.stringify(mr20Package)), not a
    // client-side re-serialization.
    const text = await captured[0].text();
    expect(text).toBe(JSON.stringify(mr20Package));
    clickSpy.mockRestore();
  });

  it("shows an MR-20 load failure verbatim without touching the ridership preview", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [] },
      "GET /reports/mr20": {
        status: 503,
        body: { detail: "The MR-20 package service is unavailable." },
      },
    });
    const user = userEvent.setup();
    renderApp("/reports/monthly");
    await screen.findByRole("group", { name: "Report section" });
    await user.click(screen.getByRole("button", { name: "MR-20 package" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The MR-20 package service is unavailable.",
    );
    // The preview tab still works.
    await user.click(
      screen.getByRole("button", { name: "Monthly ridership preview" }),
    );
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });
});
