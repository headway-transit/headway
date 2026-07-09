import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import { certifiedValue, vrhValue, vrmValue } from "./fixtures";

const BLOCKING_409_MESSAGE =
  "Certification refused: 1 blocking data-quality issue(s) are still " +
  "unresolved. Every blocking issue must be resolved before any figure can " +
  "be certified, because certifying over a known data gap would attest to " +
  "numbers we know may be wrong.";

function mockMetrics() {
  return mockApi({
    "GET /metrics/values": {
      status: 200,
      body: [certifiedValue, vrmValue, vrhValue],
    },
  });
}

describe("/metrics", () => {
  it("renders API values verbatim as strings, with lineage links and the pre-verification banner", async () => {
    signInAs("viewer");
    mockMetrics();
    renderApp("/metrics");

    const table = await screen.findByRole("table");
    // The figure is the exact string the API served — including the trailing
    // zero a number round-trip would destroy.
    expect(within(table).getByText("12345.60")).toBeInTheDocument();
    expect(within(table).getByText("987.25")).toBeInTheDocument();

    // Every figure links to its provenance.
    const lineageLinks = within(table).getAllByRole("link", {
      name: /How this number was made/,
    });
    expect(lineageLinks).toHaveLength(3);
    expect(lineageLinks[1]).toHaveAttribute(
      "href",
      "/metrics/mv-vrm-1/lineage",
    );

    // Plain-language pre-verification banner and per-row tag.
    expect(
      screen.getByText(/early calculation that has not yet been checked/),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Pre-verification").length).toBeGreaterThan(0);

    await expectNoAxeViolations();
  });

  it("does not render certification controls for roles other than certifying_official", async () => {
    signInAs("report_preparer");
    mockMetrics();
    renderApp("/metrics");

    await screen.findByRole("table");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Certify selected figures" }),
    ).not.toBeInTheDocument();
  });

  it("asks for a selection before opening the certify dialog", async () => {
    signInAs("certifying_official");
    mockMetrics();
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(
      screen.getByRole("button", { name: "Certify selected figures" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Select at least one figure to certify.",
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("certifies selected figures: labeled checkboxes, focus-trapped modal, POST body, success announcement", async () => {
    signInAs("certifying_official");
    const calls = mockApi({
      "GET /metrics/values": {
        status: 200,
        body: [certifiedValue, vrmValue, vrhValue],
      },
      "POST /certifications": {
        status: 201,
        body: {
          certification_id: "cert-42",
          metric_value_ids: ["mv-vrm-1", "mv-vrh-1"],
          certified_by: "test.user",
          certified_at: "2026-04-02T15:00:00Z",
          attestation: "I reviewed these figures and they are correct.",
          audit_event_id: 7,
        },
      },
    });
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    // Already-certified rows offer no checkbox; the two uncertified rows do,
    // each with a plain-language accessible name.
    const vrmBox = screen.getByRole("checkbox", {
      name: "Select Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31, for certification",
    });
    const vrhBox = screen.getByRole("checkbox", {
      name: "Select Vehicle Revenue Hours (VRH), 2026-03-01 to 2026-03-31, for certification",
    });
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    await user.click(vrmBox);
    await user.click(vrhBox);

    const openButton = screen.getByRole("button", {
      name: "Certify selected figures",
    });
    await user.click(openButton);

    const dialog = await screen.findByRole("dialog", {
      name: "Certify these figures",
    });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    // The dialog states exactly what is being attested: each figure verbatim.
    expect(dialog).toHaveTextContent(
      "Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31: 12345.60 miles — calculated by vrm_v0 0.1.0",
    );
    expect(dialog).toHaveTextContent(
      "Vehicle Revenue Hours (VRH), 2026-03-01 to 2026-03-31: 987.25 hours — calculated by vrh_v0 0.1.0",
    );

    // Focus moved into the dialog and Tab cycles inside it (focus trap).
    expect(dialog.contains(document.activeElement)).toBe(true);
    for (let i = 0; i < 8; i++) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }

    // Escape closes and focus returns to the opener…
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(openButton).toHaveFocus();

    // …reopen and complete the attestation.
    await user.keyboard("{Enter}");
    const reopened = await screen.findByRole("dialog");
    await expectNoAxeViolations(); // axe pass with the modal open
    await user.type(
      within(reopened).getByLabelText("Attestation statement"),
      "I reviewed these figures and they are correct.",
    );
    await user.click(within(reopened).getByRole("button", { name: "Certify" }));

    // Success is announced and the POST matched the OpenAPI request schema.
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(
      "Certification recorded for 2 figures. Certification ID cert-42.",
    );
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      metric_value_ids: ["mv-vrm-1", "mv-vrh-1"],
      attestation: "I reviewed these figures and they are correct.",
    });
    expect(post?.headers["Authorization"]).toBe("Bearer test-token");
    // The list is re-read from the API after certifying — never assumed.
    await waitFor(() =>
      expect(
        calls.filter((c) => c.path === "/metrics/values" && c.method === "GET"),
      ).toHaveLength(2),
    );
  });

  it("requires an attestation statement before certifying", async () => {
    signInAs("certifying_official");
    mockMetrics();
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(screen.getAllByRole("checkbox")[0]);
    await user.click(
      screen.getByRole("button", { name: "Certify selected figures" }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Certify" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "Please write an attestation statement before certifying.",
    );
  });

  it("shows a 409 blocking-DQ refusal verbatim with a link to the DQ queue", async () => {
    signInAs("certifying_official");
    mockApi({
      "GET /metrics/values": { status: 200, body: [vrmValue] },
      "POST /certifications": {
        status: 409,
        body: { detail: BLOCKING_409_MESSAGE },
      },
    });
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(screen.getByRole("checkbox"));
    await user.click(
      screen.getByRole("button", { name: "Certify selected figures" }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.type(
      within(dialog).getByLabelText("Attestation statement"),
      "These figures are correct.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Certify" }));

    // The refusal is shown verbatim — never softened — with a path to act.
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent(BLOCKING_409_MESSAGE);
    expect(
      within(alert).getByRole("link", {
        name: "Review the data-quality issues",
      }),
    ).toHaveAttribute("href", "/dq");
  });
});
