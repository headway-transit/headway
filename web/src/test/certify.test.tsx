/**
 * The certification cockpit (/certify — handoff 0007's deferred pillar):
 * one screen showing exactly what a signature covers. Attestation is
 * informed consent, so the suite exercises every gate in the chain:
 * role-gated visibility, per-figure receipts with labeled consent
 * checkboxes, the blockers panel mirroring the API's 409 language, the
 * simulated/pre-verification acknowledgement, the dialog restating the
 * selection verbatim, the success and 409 paths verbatim, and the full
 * keyboard path through picker → checkboxes → acknowledge → dialog.
 */

import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UserEvent } from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import type { MetricValue } from "../api/types";
import {
  blockingIssue,
  certifiedValue,
  resolvedIssue,
  simulatedUptValue,
  vrhValue,
  vrmValue,
  warningIssue,
} from "./fixtures";

/** The API's blocking-DQ refusal, verbatim (services/api routers/certify.py). */
const BLOCKING_409_MESSAGE =
  "Certification refused: 1 blocking data-quality issue(s) are still " +
  "unresolved. Every blocking issue must be resolved before any figure can " +
  "be certified, because certifying over a known data gap would attest to " +
  "numbers we know may be wrong.";

/** The cockpit's pre-emptive blocked reason mirrors the API's 409 wording. */
const BLOCKED_REASON =
  "Certification is blocked: 1 blocking data-quality issue(s) are still " +
  "unresolved. Every blocking issue must be resolved before any figure can " +
  "be certified, because certifying over a known data gap would attest to " +
  "numbers we know may be wrong.";

const SIMULATED_WARNING =
  "You are about to attest to figures computed from simulated test data. " +
  "Simulated figures must never be submitted to the FTA. Certifying them " +
  "would put your name on numbers that do not come from real service.";

const PRE_VERIFICATION_WARNING =
  "You are about to attest to figures from an early calculation that has " +
  "not yet been checked against FTA rules. They are not certifiable " +
  "figures yet.";

/**
 * Real-data figures whose calc is past pre-verification (calc_version >=
 * 1.0.0), so the clean certify path needs no acknowledgement gate.
 */
const verifiedVrm: MetricValue = { ...vrmValue, calc_version: "1.0.0" };
const verifiedVrh: MetricValue = { ...vrhValue, calc_version: "1.0.0" };

function mockCockpit(
  values: MetricValue[],
  issues: unknown[] = [],
  extra: Parameters<typeof mockApi>[0] = {},
) {
  return mockApi({
    "GET /metrics/values": { status: 200, body: values },
    "GET /dq/issues": { status: 200, body: issues },
    ...extra,
  });
}

/** Tabs until the given element has focus (fails loudly if never reached). */
async function tabTo(user: UserEvent, element: Element, max = 40) {
  for (let i = 0; i < max; i++) {
    if (document.activeElement === element) return;
    await user.tab();
  }
  expect(document.activeElement).toBe(element);
}

describe("/certify (certification cockpit)", () => {
  it("is role-gated: other roles get no Certify nav entry, a plain not-allowed note, and no certify controls", async () => {
    signInAs("report_preparer");
    const calls = mockApi({}); // any fetch would fail the test loudly
    renderApp("/certify");

    expect(
      await screen.findByText(/Only a certifying official can certify/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Certify" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Certify selected figures" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(calls).toHaveLength(0);

    await expectNoAxeViolations();
  });

  it("renders each figure of the period as a full receipt with a labeled consent checkbox; warning-severity issues do not block", async () => {
    signInAs("certifying_official");
    const calls = mockCockpit(
      [certifiedValue, verifiedVrm, verifiedVrh],
      [resolvedIssue, warningIssue],
    );
    const user = userEvent.setup();
    renderApp("/certify");

    // The nav shows the cockpit to the certifying official.
    expect(await screen.findByRole("link", { name: "Certify" })).toHaveAttribute(
      "href",
      "/certify",
    );

    // One figures read for the picked calendar month + one DQ read.
    await screen.findByText("Figures in this period");
    const valueGets = calls.filter((c) => c.path === "/metrics/values");
    expect(valueGets).toHaveLength(1);
    const params = new URL(valueGets[0].url, "http://test").searchParams;
    expect(params.get("period_start")).toMatch(/^\d{4}-\d{2}-01$/);
    expect(params.get("period_end")).toMatch(/^\d{4}-\d{2}-(28|29|30|31)$/);
    expect(calls.filter((c) => c.path === "/dq/issues")).toHaveLength(1);

    // EVERY figure renders as a full Receipt (story, coverage, FTA rule,
    // flags, walk to raw records)…
    const receipts = screen.getAllByRole("region", { name: /^Receipt for / });
    expect(receipts).toHaveLength(3);
    expect(
      screen.getByText(
        "12345.60 miles — Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: /Walk this number to its raw records/ }),
    ).toHaveLength(3);

    // …with a visibly labeled checkbox per certifiable figure; an already
    // certified figure states so instead of offering a checkbox.
    const vrmBox = screen.getByRole("checkbox", {
      name: "Certify Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31",
    });
    screen.getByRole("checkbox", {
      name: "Certify Vehicle Revenue Hours (VRH), 2026-03-01 to 2026-03-31",
    });
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(screen.getByText("Already certified")).toBeInTheDocument();

    // A warning-severity issue is not a blocker: the panel says so, with
    // the path to the DQ queue, and the action is enabled.
    expect(
      screen.getByText(/No blocking data-quality issues are open/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Review the data-quality issues" }),
    ).toHaveAttribute("href", "/dq");
    const button = screen.getByRole("button", {
      name: "Certify selected figures",
    });
    expect(button).toBeEnabled();

    // Verified, real-data figures raise no acknowledgement warning.
    await user.click(vrmBox);
    expect(
      screen.queryByText("Read this before you sign"),
    ).not.toBeInTheDocument();

    // Empty selections are refused with a plain instruction.
    await user.click(vrmBox); // deselect
    await user.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Select at least one figure to certify. Use the checkbox above each receipt.",
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("disables the certify action while blocking issues are open, showing the API's 409 reason and the path to /dq", async () => {
    signInAs("certifying_official");
    mockCockpit([verifiedVrm], [blockingIssue, warningIssue]);
    const user = userEvent.setup();
    renderApp("/certify");

    // The reason mirrors the API's own refusal, count included.
    const blockers = await screen.findByText(BLOCKED_REASON);
    expect(blockers).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Review the data-quality issues" }),
    ).toHaveAttribute("href", "/dq");

    // The action stays disabled even with a figure selected.
    const button = screen.getByRole("button", {
      name: "Certify selected figures",
    });
    expect(button).toBeDisabled();
    await user.click(
      screen.getByRole("checkbox", {
        name: "Certify Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31",
      }),
    );
    expect(button).toBeDisabled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("requires a separate acknowledgement when any selected figure is simulated or pre-verification, and re-requires it when the selection changes", async () => {
    signInAs("certifying_official");
    mockCockpit([simulatedUptValue]); // simulated AND pre-verification (0.5.0)
    const user = userEvent.setup();
    renderApp("/certify");

    const figureBox = await screen.findByRole("checkbox", {
      name: "Certify Unlinked Passenger Trips (UPT), 2026-03-01 to 2026-03-31",
    });
    const button = screen.getByRole("button", {
      name: "Certify selected figures",
    });
    // No selection yet: no warning, button enabled (empty selections are
    // refused at click time instead).
    expect(
      screen.queryByText("Read this before you sign"),
    ).not.toBeInTheDocument();

    // Selecting the simulated, pre-verification figure raises the
    // unmissable aggregate warning and turns the button off.
    await user.click(figureBox);
    const warning = screen
      .getByText("Read this before you sign")
      .closest("div") as HTMLElement;
    expect(warning).toHaveTextContent(SIMULATED_WARNING);
    expect(warning).toHaveTextContent(PRE_VERIFICATION_WARNING);
    expect(button).toBeDisabled();
    expect(
      screen.getByText(
        "The certify button stays off until you confirm the warning above.",
      ),
    ).toBeInTheDocument();

    // The acknowledgement is its own explicit checkbox.
    const acknowledge = within(warning).getByRole("checkbox", {
      name: "I have read these warnings and I understand what certifying these figures would mean.",
    });
    await user.click(acknowledge);
    expect(button).toBeEnabled();

    // Consent never carries over: changing the selection clears it.
    await user.click(figureBox); // deselect
    await user.click(figureBox); // reselect
    expect(
      within(
        screen.getByText("Read this before you sign").closest("div") as HTMLElement,
      ).getByRole("checkbox", { name: /I have read these warnings/ }),
    ).not.toBeChecked();
    expect(button).toBeDisabled();

    await expectNoAxeViolations();
  });

  it("restates every selected figure verbatim in the dialog, requires the attestation, and shows the certification and audit ids verbatim on success", async () => {
    signInAs("certifying_official");
    const calls = mockCockpit([verifiedVrm, verifiedVrh], [], {
      "POST /certifications": {
        status: 201,
        body: {
          certification_id: "cert-42",
          metric_value_ids: ["mv-vrm-1", "mv-vrh-1"],
          certified_by: "test.user",
          certified_at: "2026-07-02T15:00:00Z",
          attestation: "I reviewed these figures and they are correct.",
          audit_event_id: 7,
        },
      },
    });
    const user = userEvent.setup();
    renderApp("/certify");

    await user.click(
      await screen.findByRole("checkbox", {
        name: "Certify Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31",
      }),
    );
    await user.click(
      screen.getByRole("checkbox", {
        name: "Certify Vehicle Revenue Hours (VRH), 2026-03-01 to 2026-03-31",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "Certify selected figures" }),
    );

    // The dialog states exactly what is being attested: metric, value
    // verbatim, period, and calculation + version, per figure.
    const dialog = await screen.findByRole("dialog", {
      name: "Certify these figures",
    });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveTextContent(
      "Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31: 12345.60 miles — calculated by vrm_v0 1.0.0",
    );
    expect(dialog).toHaveTextContent(
      "Vehicle Revenue Hours (VRH), 2026-03-01 to 2026-03-31: 987.25 hours — calculated by vrh_v0 1.0.0",
    );
    // Provenance stays one step away even inside the dialog.
    expect(
      within(dialog).getAllByRole("link", {
        name: "How this number was made",
      }),
    ).toHaveLength(2);
    await expectNoAxeViolations(); // axe pass with the dialog open

    // The attestation statement is required before anything is posted.
    await user.click(within(dialog).getByRole("button", { name: "Certify" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "Please write an attestation statement before certifying.",
    );
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    await user.type(
      within(dialog).getByLabelText("Attestation statement"),
      "I reviewed these figures and they are correct.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Certify" }));

    // Success restates the API's identifiers verbatim: certification id
    // AND the audit event reference.
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(
      "Certification recorded for 2 figures. Certification ID cert-42. Audit event 7. The API has audit-logged who certified and when.",
    );
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      metric_value_ids: ["mv-vrm-1", "mv-vrh-1"],
      attestation: "I reviewed these figures and they are correct.",
    });
    expect(post?.headers["Authorization"]).toBe("Bearer test-token");
    // Figures AND blockers are re-read from the API — never assumed.
    await waitFor(() => {
      expect(calls.filter((c) => c.path === "/metrics/values")).toHaveLength(2);
      expect(calls.filter((c) => c.path === "/dq/issues")).toHaveLength(2);
    });
  });

  it("shows a 409 blocking-DQ refusal verbatim in the dialog with a link to the DQ queue", async () => {
    signInAs("certifying_official");
    mockCockpit([verifiedVrm], [], {
      "POST /certifications": {
        status: 409,
        body: { detail: BLOCKING_409_MESSAGE },
      },
    });
    const user = userEvent.setup();
    renderApp("/certify");

    await user.click(
      await screen.findByRole("checkbox", {
        name: "Certify Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31",
      }),
    );
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

  it("is fully keyboard operable: picker → consent checkbox → acknowledge → certify button → focus-trapped dialog", async () => {
    signInAs("certifying_official");
    mockCockpit([simulatedUptValue]);
    const user = userEvent.setup();
    renderApp("/certify");

    const figureBox = await screen.findByRole("checkbox", {
      name: "Certify Unlinked Passenger Trips (UPT), 2026-03-01 to 2026-03-31",
    });

    // (a) the period picker is keyboard-reachable, month then year.
    const monthSelect = screen.getByLabelText("Month");
    await tabTo(user, monthSelect);
    await user.tab();
    expect(screen.getByLabelText("Year")).toHaveFocus();

    // (b) on to the figure's consent checkbox; Space selects it.
    await tabTo(user, figureBox);
    await user.keyboard(" ");
    expect(figureBox).toBeChecked();

    // (d) the acknowledge checkbox is next in the tab order (after the
    // receipt's provenance link and the blockers panel's /dq link); the
    // disabled certify button is skipped until it is checked.
    const acknowledge = screen.getByRole("checkbox", {
      name: /I have read these warnings/,
    });
    await tabTo(user, acknowledge);
    await user.keyboard(" ");
    expect(acknowledge).toBeChecked();

    // (e) Tab reaches the now-enabled certify button; Enter opens the
    // dialog and focus moves inside the trap.
    const button = screen.getByRole("button", {
      name: "Certify selected figures",
    });
    await tabTo(user, button);
    await user.keyboard("{Enter}");
    const dialog = await screen.findByRole("dialog", {
      name: "Certify these figures",
    });
    expect(dialog.contains(document.activeElement)).toBe(true);
    for (let i = 0; i < 8; i++) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }

    // Escape closes the dialog and returns focus to the opener.
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });
});
