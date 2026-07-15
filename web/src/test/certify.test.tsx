/**
 * The certification cockpit (/certify — handoff 0007's deferred pillar;
 * signing ceremony per handoff 0019, design 5): one screen showing exactly
 * what a signature covers. The suite exercises every gate in the chain:
 * role-gated visibility, per-figure receipts with labeled consent
 * checkboxes, the blockers panel mirroring the API's 409 language, the
 * simulated/pre-verification acknowledgement, the SIGNATURE BLOCK (covered
 * list with receipt hashes and attestation reliance, the intent statement,
 * typed name + title), the POST body, the certificate handoff, the 409
 * path verbatim, the full keyboard path — and the STALE-RESPONSE GUARD
 * (the month-switch race): a slow older month's response must never paint
 * under a newer month's picker.
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
import type { MockedResponse } from "./helpers";
import type { MetricValue } from "../api/types";
import {
  attestedBlockingIssue,
  attestedUptValue,
  blockingIssue,
  certificateFixture,
  certificationIntentFixture,
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

/** Accessible name of the always-visible reason line AT the sign button. */
const REASON_NAME = "Why the sign-and-certify button is off";

const SIGN_BUTTON = "Sign and certify";

/**
 * The reason line rendered directly beside the sign button (2026-07-11
 * click-through, finding 1). It must exist whenever the button is off, be
 * wired to the button via aria-describedby, and state every active cause.
 */
function atButtonReason(): HTMLElement {
  const button = screen.getByRole("button", { name: SIGN_BUTTON });
  expect(button).toHaveAttribute("aria-disabled", "true");
  const reason = screen.getByRole("status", { name: REASON_NAME });
  expect(button).toHaveAttribute("aria-describedby", reason.id);
  return reason;
}

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
 * 1.0.0), so the clean signing path needs no acknowledgement gate.
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
    // The server's fixed signing statements: the ceremony signs against
    // THESE words (GET /certifications/intent), never its own.
    "GET /certifications/intent": {
      status: 200,
      body: certificationIntentFixture,
    },
    ...extra,
  });
}

/** Fills the signature block's typed name + title (the signing identity). */
async function typeSigner(user: UserEvent) {
  await user.type(screen.getByLabelText("Your full name"), "Alex Rivera");
  await user.type(
    screen.getByLabelText("Your title"),
    "NTD Certifying Official",
  );
}

/** Tabs until the given element has focus (fails loudly if never reached). */
async function tabTo(user: UserEvent, element: Element, max = 60) {
  for (let i = 0; i < max; i++) {
    if (document.activeElement === element) return;
    await user.tab();
  }
  expect(document.activeElement).toBe(element);
}

describe("/certify (certification cockpit)", () => {
  it("is role-gated: other roles get no Certify nav entry, a plain not-allowed note, and no signing controls", async () => {
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
      screen.queryByRole("button", { name: SIGN_BUTTON }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    // No certify-related fetch happened; the only call is the app shell's
    // unauthenticated GET /branding (handoff 0008 pillar C).
    expect(calls.filter((c) => c.path !== "/branding")).toHaveLength(0);

    await expectNoAxeViolations();
  });

  // Explicit timeout: receipts + typing + axe sit at the 5 s default's
  // edge under full-suite load on this box (the house 15 s precedent).
  it("renders each figure of the period as a full receipt with a labeled consent checkbox; warning-severity issues do not block", { timeout: 15_000 }, async () => {
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
    // the path to the DQ queue.
    expect(
      screen.getByText(/No blocking data-quality issues are open/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Review the data-quality issues" }),
    ).toHaveAttribute("href", "/dq");
    const button = screen.getByRole("button", { name: SIGN_BUTTON });

    // Nothing is selected and no name is typed, so the button is off — and
    // it says WHY, right beside itself, for EVERY active cause (finding 1).
    const reason = atButtonReason();
    expect(reason).toHaveTextContent(
      "Select at least one figure to certify. Use the checkbox above each receipt.",
    );
    expect(reason).toHaveTextContent(
      "Type your full name. The signature must carry it.",
    );
    expect(reason).toHaveTextContent(
      "Type your title. The signature must carry it.",
    );
    // The empty covered list is stated, never blank.
    expect(
      screen.getByText(
        "No figures are selected yet. Tick a figure above to bring it under your signature.",
      ),
    ).toBeInTheDocument();

    // Selecting a figure brings it under the signature: the covered list
    // restates it verbatim, with the honest receipt-hash line (this API
    // serves no hash) and the intent statement in view.
    await user.click(vrmBox);
    expect(
      screen.queryByText("Read this before you sign"),
    ).not.toBeInTheDocument();
    const covers = screen
      .getByText("What your signature covers")
      .closest("section") as HTMLElement;
    expect(covers).toHaveTextContent(
      "Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31: 12345.60 miles — calculated by vrm_v0 1.0.0",
    );
    expect(covers).toHaveTextContent(
      "Receipt hash: computed and recorded by the server when it signs.",
    );
    // The intent statement is the SERVER's own text, rendered verbatim.
    expect(covers).toHaveTextContent(
      certificationIntentFixture.intent_statement,
    );

    // Verified, real-data figures raise no acknowledgement warning; with a
    // selection, no blockers, and the typed identity the button turns on.
    await typeSigner(user);
    expect(button).not.toHaveAttribute("aria-disabled");
    expect(
      screen.queryByRole("status", { name: REASON_NAME }),
    ).not.toBeInTheDocument();

    // Empty selections: the reason returns, and a click on the still-
    // perceivable (aria-disabled, never display:none) button is refused —
    // no POST, no silent swallow.
    await user.click(vrmBox); // deselect
    expect(atButtonReason()).toHaveTextContent(
      "Select at least one figure to certify. Use the checkbox above each receipt.",
    );
    await user.click(button);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    await expectNoAxeViolations();
  });

  it("disables the sign action while blocking issues are open, showing the API's 409 reason and the path to /dq — at the panel AND at the button", async () => {
    signInAs("certifying_official");
    const calls = mockCockpit([verifiedVrm], [blockingIssue, warningIssue]);
    const user = userEvent.setup();
    renderApp("/certify");

    // The blockers panel mirrors the API's own refusal, count included.
    const blockers = await screen.findByText(BLOCKED_REASON);
    expect(blockers).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Review the data-quality issues" }),
    ).toHaveAttribute("href", "/dq");

    // Finding 1: the refusal is ALSO stated right beside the button — the
    // panel above can be far off-screen on a long page.
    const reason = atButtonReason();
    expect(reason).toHaveTextContent(
      "Certification is blocked: 1 blocking data-quality issue(s) must be resolved first.",
    );
    expect(
      within(reason).getByRole("link", { name: "View the blocking issues" }),
    ).toHaveAttribute("href", "/dq");

    // The action stays off even with a figure selected and an identity
    // typed, and a click on the still-focusable (aria-disabled) button is
    // refused, never swallowed silently: no POST, reason still on screen.
    const button = screen.getByRole("button", { name: SIGN_BUTTON });
    await user.click(
      screen.getByRole("checkbox", {
        name: "Certify Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31",
      }),
    );
    await typeSigner(user);
    expect(button).toHaveAttribute("aria-disabled", "true");
    await user.click(button);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    expect(
      screen.getByRole("status", { name: REASON_NAME }),
    ).toHaveTextContent(/Certification is blocked/);

    await expectNoAxeViolations();
  });

  it("treats an ATTESTED blocking issue as closed — exactly as the API's 409 rule does (found by the 2026-07-15 live click-through)", async () => {
    signInAs("certifying_official");
    // 'attested' (migration 0029) is a CLOSED state: the p. 146
    // statistician closure. The cockpit must not block on it — before this
    // pin, the client-side filter (status !== 'resolved') refused what the
    // server allows, and screen and server told different stories.
    mockCockpit([verifiedVrm], [attestedBlockingIssue, resolvedIssue]);
    const user = userEvent.setup();
    renderApp("/certify");

    expect(
      await screen.findByText(/No blocking data-quality issues are open/),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("checkbox", {
        name: "Certify Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31",
      }),
    );
    await typeSigner(user);
    expect(
      screen.getByRole("button", { name: SIGN_BUTTON }),
    ).not.toHaveAttribute("aria-disabled");
  });

  it("requires a separate acknowledgement when any selected figure is simulated or pre-verification, and re-requires it when the selection changes", async () => {
    signInAs("certifying_official");
    mockCockpit([simulatedUptValue]); // simulated AND pre-verification (0.5.0)
    const user = userEvent.setup();
    renderApp("/certify");

    const figureBox = await screen.findByRole("checkbox", {
      name: "Certify Unlinked Passenger Trips (UPT), 2026-03-01 to 2026-03-31",
    });
    const button = screen.getByRole("button", { name: SIGN_BUTTON });
    // No selection yet: no warning (the button is off with the
    // nothing-selected reason beside it instead).
    expect(
      screen.queryByText("Read this before you sign"),
    ).not.toBeInTheDocument();

    // Selecting the simulated, pre-verification figure raises the
    // unmissable aggregate warning and keeps the button off.
    await user.click(figureBox);
    await typeSigner(user);
    const warning = screen
      .getByText("Read this before you sign")
      .closest("div") as HTMLElement;
    expect(warning).toHaveTextContent(SIMULATED_WARNING);
    expect(warning).toHaveTextContent(PRE_VERIFICATION_WARNING);
    // Finding 1: the unacknowledged gate states itself AT the button too.
    expect(atButtonReason()).toHaveTextContent(
      "The certify button stays off until you confirm the warning above.",
    );

    // The acknowledgement is its own explicit checkbox. (The signed
    // document carries each figure's simulated flags inside its detail —
    // the gate is the ceremony's, the record is the server's.)
    const acknowledge = within(warning).getByRole("checkbox", {
      name: "I have read these warnings and I understand what certifying these figures would mean.",
    });
    await user.click(acknowledge);
    expect(button).not.toHaveAttribute("aria-disabled");
    expect(
      screen.queryByRole("status", { name: REASON_NAME }),
    ).not.toBeInTheDocument();

    // Consent never carries over: changing the selection clears it.
    await user.click(figureBox); // deselect
    await user.click(figureBox); // reselect
    expect(
      within(
        screen.getByText("Read this before you sign").closest("div") as HTMLElement,
      ).getByRole("checkbox", { name: /I have read these warnings/ }),
    ).not.toBeChecked();
    expect(atButtonReason()).toHaveTextContent(
      "The certify button stays off until you confirm the warning above.",
    );

    await expectNoAxeViolations();
  });

  it("lists an attested figure's receipt hash and statistician-attestation reliance under the signature", async () => {
    signInAs("certifying_official");
    mockCockpit([attestedUptValue]);
    const user = userEvent.setup();
    renderApp("/certify");

    await user.click(
      await screen.findByRole("checkbox", {
        name: "Certify Unlinked Passenger Trips (UPT), 2026-03-01 to 2026-03-31",
      }),
    );

    const covers = screen
      .getByText("What your signature covers")
      .closest("section") as HTMLElement;
    // Receipt hashes exist only inside the signed document — the covered
    // list states that instead of ever faking one.
    expect(covers).toHaveTextContent(
      "Receipt hash: computed and recorded by the server when it signs.",
    );
    // The signature visibly covers the figure's attestation reliance.
    expect(covers).toHaveTextContent(
      "This figure relies on statistician attestation #att-3.",
    );
    expect(
      within(covers).getByRole("link", {
        name: "Read attestation #att-3 on the Attestations page",
      }),
    ).toHaveAttribute("href", "/attestations");

    await expectNoAxeViolations();
  });

  it("refuses to arm when the server's signing statement cannot be loaded — there is nothing to sign against", async () => {
    signInAs("certifying_official");
    mockApi({
      "GET /metrics/values": { status: 200, body: [verifiedVrm] },
      "GET /dq/issues": { status: 200, body: [] },
      "GET /certifications/intent": {
        status: 404,
        body: { detail: "Not Found" },
      },
    });
    const user = userEvent.setup();
    renderApp("/certify");

    await user.click(
      await screen.findByRole("checkbox", {
        name: "Certify Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31",
      }),
    );
    await typeSigner(user);

    // The absence is an alert (the server's error verbatim beneath the
    // plain-language statement) AND a stated reason at the button.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Headway could not load the signing statement from the server, so there is nothing to sign against.",
    );
    expect(alert).toHaveTextContent("Not Found");
    expect(atButtonReason()).toHaveTextContent(
      "Headway could not load the signing statement from the server",
    );

    await expectNoAxeViolations();
  });

  it("signs with the typed name and title against the intent statement, POSTs exactly what was shown, and lands on the certificate", async () => {
    signInAs("certifying_official");
    const calls = mockCockpit([verifiedVrm, verifiedVrh], [], {
      "POST /certifications": {
        status: 201,
        body: {
          certification_id: "cert-42",
          metric_value_ids: ["mv-vrm-1", "mv-vrh-1"],
          certified_by: "test.user",
          certified_at: "2026-07-02T15:00:00Z",
          attestation: certificationIntentFixture.intent_statement,
          signer_full_name: "Alex Rivera",
          signer_title: "NTD Certifying Official",
          canonical_document: certificateFixture.canonical_document,
          signature: certificateFixture.signature,
          key_fingerprint: certificateFixture.key_fingerprint,
          algorithm: "ed25519",
          audit_event_id: 7,
        },
      },
      "GET /certifications/cert-42": {
        status: 200,
        body: certificateFixture,
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

    // The signature block restates exactly what is being signed: metric,
    // value verbatim, period, calculation + version, per figure — with
    // provenance one step away.
    const covers = screen
      .getByText("What your signature covers")
      .closest("section") as HTMLElement;
    expect(covers).toHaveTextContent(
      "Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31: 12345.60 miles — calculated by vrm_v0 1.0.0",
    );
    expect(covers).toHaveTextContent(
      "Vehicle Revenue Hours (VRH), 2026-03-01 to 2026-03-31: 987.25 hours — calculated by vrh_v0 1.0.0",
    );
    expect(
      within(covers).getAllByRole("link", { name: "How this number was made" }),
    ).toHaveLength(2);

    await typeSigner(user);
    await user.click(screen.getByRole("button", { name: SIGN_BUTTON }));

    // The POST carries the typed identity, the SERVER's intent statement
    // VERBATIM (the record holds exactly the words the signer saw), and
    // the ids — the reconciled contract's exact field names.
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      metric_value_ids: ["mv-vrm-1", "mv-vrh-1"],
      attestation: certificationIntentFixture.intent_statement,
      signer_full_name: "Alex Rivera",
      signer_title: "NTD Certifying Official",
    });
    expect(post?.headers["Authorization"]).toBe("Bearer test-token");

    // Submit → certificate view (SPA nav): the stored record is read from
    // the API and the signature block renders front and center.
    expect(
      await screen.findByRole("heading", { name: "Certification certificate" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Signed by Alex Rivera, NTD Certifying Official"),
    ).toBeInTheDocument();
    expect(
      calls.filter((c) => c.path === "/certifications/cert-42"),
    ).toHaveLength(1);
  });

  it("shows a 409 blocking-DQ refusal verbatim beside the signature block with a link to the DQ queue", async () => {
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
    await typeSigner(user);
    await user.click(screen.getByRole("button", { name: SIGN_BUTTON }));

    // The refusal is shown verbatim — never softened — with a path to act,
    // and the user stays on the cockpit (nothing navigates on a refusal).
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(BLOCKING_409_MESSAGE);
    expect(
      within(alert).getByRole("link", {
        name: "Review the data-quality issues",
      }),
    ).toHaveAttribute("href", "/dq");
    expect(
      screen.getByRole("heading", { name: "Certify figures" }),
    ).toBeInTheDocument();
  });

  it("discards a stale month's late response: switching months mid-flight never paints the old month's figures (the 0017-era race, regression-pinned)", async () => {
    signInAs("certifying_official");
    // The FIRST figures request hangs until we resolve it BY HAND — after
    // the second month's (instant) response has landed. Without the guard,
    // the stale response would overwrite the newer month's figures.
    let resolveFirst: (response: MockedResponse) => void = () => {};
    const firstResponse = new Promise<MockedResponse>((resolve) => {
      resolveFirst = resolve;
    });
    let figureCalls = 0;
    mockApi({
      "GET /metrics/values": () => {
        figureCalls += 1;
        if (figureCalls === 1) return firstResponse;
        return { status: 200, body: [verifiedVrh] };
      },
      "GET /dq/issues": { status: 200, body: [] },
      "GET /certifications/intent": {
        status: 200,
        body: certificationIntentFixture,
      },
    });
    const user = userEvent.setup();
    renderApp("/certify");

    // The initial load is in flight (deliberately hung); switch the month.
    await screen.findByLabelText("Month");
    await user.selectOptions(screen.getByLabelText("Month"), "1");

    // The NEW month's response lands and paints.
    await screen.findByRole("region", {
      name: /^Receipt for Vehicle Revenue Hours/,
    });
    expect(figureCalls).toBe(2);

    // NOW the stale first response arrives — and must be discarded.
    resolveFirst({ status: 200, body: [verifiedVrm] });
    // Give the discarded promise every chance to (wrongly) paint.
    await waitFor(() => {
      expect(
        screen.getByRole("region", {
          name: /^Receipt for Vehicle Revenue Hours/,
        }),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("region", {
        name: /^Receipt for Vehicle Revenue Miles/,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/12345\.60 miles/),
    ).not.toBeInTheDocument();
  });

  it("is fully keyboard operable: picker → consent checkbox → acknowledge → name → title → sign button", async () => {
    signInAs("certifying_official");
    mockCockpit([simulatedUptValue], [], {
      "POST /certifications": {
        status: 201,
        body: {
          certification_id: "cert-9",
          metric_value_ids: ["mv-upt-sim-1"],
          certified_by: "test.user",
          certified_at: "2026-07-02T15:00:00Z",
          attestation: certificationIntentFixture.intent_statement,
          signer_full_name: "Alex Rivera",
          signer_title: "NTD Certifying Official",
          canonical_document: certificateFixture.canonical_document,
          signature: certificateFixture.signature,
          key_fingerprint: certificateFixture.key_fingerprint,
          algorithm: "ed25519",
          audit_event_id: 8,
        },
      },
      "GET /certifications/cert-9": {
        status: 200,
        body: { ...certificateFixture, certification_id: "cert-9" },
      },
    });
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

    // (d) the acknowledge checkbox is reachable in the tab order. The sign
    // button stays IN the tab order even while off (aria-disabled, never
    // the native attribute) so its reason is perceivable.
    const acknowledge = screen.getByRole("checkbox", {
      name: /I have read these warnings/,
    });
    await tabTo(user, acknowledge);
    await user.keyboard(" ");
    expect(acknowledge).toBeChecked();

    // (e) the typed identity, reached by keyboard.
    const nameInput = screen.getByLabelText("Your full name");
    await tabTo(user, nameInput);
    await user.keyboard("Alex Rivera");
    const titleInput = screen.getByLabelText("Your title");
    await tabTo(user, titleInput);
    await user.keyboard("NTD Certifying Official");

    // Tab reaches the now-enabled sign button; Enter signs and the
    // certificate renders.
    const button = screen.getByRole("button", { name: SIGN_BUTTON });
    await tabTo(user, button);
    expect(button).not.toHaveAttribute("aria-disabled");
    await user.keyboard("{Enter}");
    expect(
      await screen.findByRole("heading", { name: "Certification certificate" }),
    ).toBeInTheDocument();
  });
});
