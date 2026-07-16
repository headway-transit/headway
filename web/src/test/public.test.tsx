/**
 * /public — the human-readable rendering of GET /public/metrics/certified
 * (2026-07-11 click-through, finding 3). The page must work with NO session
 * at all (the endpoint is the one deliberately unauthenticated exception,
 * handoff 0006 design point 8), render every certified figure verbatim as a
 * receipt-lite card with its simulated flag when present, keep the permanent
 * disclaimer on screen (empty state included), and link the raw JSON.
 */

import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import type { PublicMetricValue, VerificationResult } from "../api/types";
import { certifiedValue, simulatedUptValue } from "./fixtures";

const DISCLAIMER =
  "This page is the agency's public courtesy copy of its certified figures. " +
  "It is not the official federal record: the agency's official submissions " +
  "are filed with the Federal Transit Administration. Any figure computed " +
  "from simulated test data is labeled below — the label is never removed.";

/** A certified, simulated figure — flags are published, never stripped. */
const certifiedSimulatedUpt: PublicMetricValue = {
  ...simulatedUptValue,
  certification_status: "certified",
  // Not served by the API today; the card renders it the moment it appears.
  certified_at: "2026-04-02T09:00:00Z",
};

function mockPublic(body: unknown) {
  return mockApi({
    "GET /public/metrics/certified": { status: 200, body },
  });
}

describe("/public (certified open data)", () => {
  it("renders the certification block's key fingerprint when served — and the honest legacy line for a pre-signature certification (handoff 0019, design 7)", async () => {
    const signedRow: PublicMetricValue = {
      ...certifiedValue,
      certification: {
        certification_id: "cert-42",
        certified_at: "2026-07-15T23:00:05Z",
        key_fingerprint: "ed25519:f0995b71ecc91f99d6c0794eee26297907fe2ae7",
      },
    };
    const legacyRow: PublicMetricValue = {
      ...certifiedSimulatedUpt,
      certification: {
        certification_id: "cert-7",
        certified_at: "2026-04-02T09:00:00Z",
        key_fingerprint: null,
      },
    };
    mockPublic([signedRow, legacyRow]);
    renderApp("/public");

    // The signed row: the fingerprint verbatim — never any certifier
    // identity (the public feed carries none by design).
    const vrmCard = (
      await screen.findByRole("heading", { name: "Vehicle Revenue Miles (VRM)" })
    ).closest("article") as HTMLElement;
    expect(vrmCard).toHaveTextContent("Signature key fingerprint");
    expect(vrmCard).toHaveTextContent(
      "ed25519:f0995b71ecc91f99d6c0794eee26297907fe2ae7",
    );
    expect(vrmCard).toHaveTextContent("Certified on");
    expect(vrmCard).toHaveTextContent("2026-07-15T23:00:05Z");

    // The legacy row states the absence instead of a blank cell.
    const uptCard = screen
      .getByRole("heading", { name: "Unlinked Passenger Trips (UPT)" })
      .closest("article") as HTMLElement;
    expect(uptCard).toHaveTextContent(
      "Certified before digital signatures existed in Headway — no signature fingerprint.",
    );

    // The verify affordance rides ONLY the signed row: a legacy record has
    // nothing to verify, so it gets no button (the honest line stands).
    expect(
      within(vrmCard).getByRole("button", { name: /^Verify this signature/ }),
    ).toBeInTheDocument();
    expect(
      within(uptCard).queryByRole("button", {
        name: /^Verify this signature/,
      }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("verifies a signed row through the PUBLIC endpoint — no token sent — and renders the server's verified verdict verbatim", async () => {
    // NO signInAs: the check must work for an anonymous visitor.
    const signedRow: PublicMetricValue = {
      ...certifiedValue,
      certification: {
        certification_id: "cert-42",
        certified_at: "2026-07-15T23:00:05Z",
        key_fingerprint: "ed25519:f0995b71ecc91f99d6c0794eee26297907fe2ae7",
      },
    };
    const verdict: VerificationResult = {
      certification_id: "cert-42",
      signed: true,
      verified: true,
      verdict: "verified",
      algorithm: "ed25519",
      key_fingerprint: "ed25519:f0995b71ecc91f99d6c0794eee26297907fe2ae7",
      certified_at: "2026-07-15T23:00:05Z",
      message:
        "Verified: the stored certificate is byte-identical to what was signed and the signature is valid under this installation's key.",
    };
    const calls = mockApi({
      "GET /public/metrics/certified": { status: 200, body: [signedRow] },
      "GET /public/certifications/cert-42/verify": {
        status: 200,
        body: verdict,
      },
    });
    const user = userEvent.setup();
    renderApp("/public");

    const card = (
      await screen.findByRole("heading", {
        name: "Vehicle Revenue Miles (VRM)",
      })
    ).closest("article") as HTMLElement;
    // The always-visible note says anyone can run the check.
    expect(card).toHaveTextContent(
      "Anyone can run this check, without an account",
    );
    await user.click(
      within(card).getByRole("button", { name: /^Verify this signature/ }),
    );

    // The server's verdict, verbatim, in the success voice.
    const status = await within(card).findByRole("status");
    expect(status).toHaveTextContent("Signature verified.");
    expect(status).toHaveTextContent(verdict.message);

    // The verify call hit the PUBLIC endpoint and carried no token.
    const verifyCall = calls.find((c) =>
      c.path.endsWith("/certifications/cert-42/verify"),
    );
    expect(verifyCall?.path).toBe("/public/certifications/cert-42/verify");
    expect(verifyCall?.headers.Authorization).toBeUndefined();

    await expectNoAxeViolations();
  });

  it("renders a FAILED verdict loudly and verbatim — tamper evidence is never softened", async () => {
    const signedRow: PublicMetricValue = {
      ...certifiedValue,
      certification: {
        certification_id: "cert-99",
        certified_at: "2026-07-15T23:00:05Z",
        key_fingerprint: "ed25519:f0995b71ecc91f99d6c0794eee26297907fe2ae7",
      },
    };
    const failedMessage =
      "VERIFICATION FAILED: the stored record does not match its " +
      "signature. The record has been tampered with since signing, or " +
      "the stored signature is corrupt.";
    mockApi({
      "GET /public/metrics/certified": { status: 200, body: [signedRow] },
      "GET /public/certifications/cert-99/verify": {
        status: 200,
        body: {
          certification_id: "cert-99",
          signed: true,
          verified: false,
          verdict: "failed",
          algorithm: "ed25519",
          key_fingerprint:
            "ed25519:f0995b71ecc91f99d6c0794eee26297907fe2ae7",
          certified_at: "2026-07-15T23:00:05Z",
          message: failedMessage,
        } satisfies VerificationResult,
      },
    });
    const user = userEvent.setup();
    renderApp("/public");

    const card = (
      await screen.findByRole("heading", {
        name: "Vehicle Revenue Miles (VRM)",
      })
    ).closest("article") as HTMLElement;
    await user.click(
      within(card).getByRole("button", { name: /^Verify this signature/ }),
    );

    const alert = await within(card).findByRole("alert");
    expect(alert).toHaveTextContent("SIGNATURE VERIFICATION FAILED.");
    expect(alert).toHaveTextContent(failedMessage);

    await expectNoAxeViolations();
  });

  it("treats a failure to reach the verify endpoint as a loud failure to verify (e.g. the public rate limit), verbatim", async () => {
    const signedRow: PublicMetricValue = {
      ...certifiedValue,
      certification: {
        certification_id: "cert-42",
        certified_at: "2026-07-15T23:00:05Z",
        key_fingerprint: "ed25519:f0995b71ecc91f99d6c0794eee26297907fe2ae7",
      },
    };
    mockApi({
      "GET /public/metrics/certified": { status: 200, body: [signedRow] },
      "GET /public/certifications/cert-42/verify": {
        status: 429,
        body: {
          detail:
            "Too many requests from this address. Wait a moment and try again.",
        },
      },
    });
    const user = userEvent.setup();
    renderApp("/public");

    const card = (
      await screen.findByRole("heading", {
        name: "Vehicle Revenue Miles (VRM)",
      })
    ).closest("article") as HTMLElement;
    await user.click(
      within(card).getByRole("button", { name: /^Verify this signature/ }),
    );

    const alert = await within(card).findByRole("alert");
    expect(alert).toHaveTextContent("SIGNATURE VERIFICATION FAILED.");
    expect(alert).toHaveTextContent(
      "Too many requests from this address. Wait a moment and try again.",
    );
  });

  it("renders the certified figures as receipt-lite cards WITHOUT any sign-in, values verbatim, no token sent", async () => {
    // NO signInAs: the whole point is that this page needs no account.
    const calls = mockPublic([certifiedValue, certifiedSimulatedUpt]);
    renderApp("/public");

    expect(
      await screen.findByRole("heading", {
        name: "Public data: certified figures",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/figures this agency's certifying official has attested to/),
    ).toBeInTheDocument();

    // The request carried no bearer token: the endpoint is public by
    // design. (The app shell also fetches GET /branding — the other
    // deliberately unauthenticated path — and nothing else.)
    const dataCalls = calls.filter((c) => c.path !== "/branding");
    expect(dataCalls).toHaveLength(1);
    expect(dataCalls[0].path).toBe("/public/metrics/certified");
    for (const call of calls) {
      expect(call.headers["Authorization"]).toBeUndefined();
    }

    // Each figure is a card: plain metric name, the value VERBATIM
    // (trailing zero preserved — never reparsed), period, coverage line.
    const vrmCard = screen
      .getByRole("heading", { name: "Vehicle Revenue Miles (VRM)" })
      .closest("article") as HTMLElement;
    expect(vrmCard).toHaveTextContent("11111.10 miles");
    expect(vrmCard).toHaveTextContent("2026-02-01 to 2026-02-28");
    expect(vrmCard).toHaveTextContent("Certified");
    // No detail on this figure: its coverage absence is stated, not blank.
    expect(vrmCard).toHaveTextContent(
      "The calculation reported no coverage information for this figure.",
    );
    expect(vrmCard).toHaveTextContent("Calculated by vrm_v0 (version 0.1.0).");
    // No certification block on this row (an API predating handoff 0019):
    // no fingerprint line is invented.
    expect(vrmCard).not.toHaveTextContent("Signature key fingerprint");

    // The simulated figure keeps its badge — transparency shows the flags —
    // plus its coverage line and (when served) its certification date.
    const uptCard = screen
      .getByRole("heading", { name: "Unlinked Passenger Trips (UPT)" })
      .closest("article") as HTMLElement;
    expect(uptCard).toHaveTextContent("41985.90 unlinked passenger trips");
    expect(within(uptCard).getByText("Simulated data")).toBeInTheDocument();
    expect(uptCard).toHaveTextContent(
      "Passenger counts were recorded on 9032 of 9123 operated trips.",
    );
    expect(uptCard).toHaveTextContent("Certified on");
    expect(uptCard).toHaveTextContent("2026-04-02T09:00:00Z");

    // The permanent disclaimer and the raw machine-readable JSON link.
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "Machine-readable version of this data (JSON)",
      }),
    ).toHaveAttribute("href", "/public/metrics/certified");

    // Signed out, the shell still offers the way in — and the public link.
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(
      within(nav).getByRole("link", { name: "Public data" }),
    ).toHaveAttribute("href", "/public");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/login",
    );
    // Authenticated pages are not offered to a signed-out visitor (UX only;
    // the API enforces authentication regardless).
    expect(
      within(nav).queryByRole("link", { name: "Metrics" }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("shows the plain-language empty state with the disclaimer still on screen", async () => {
    mockPublic([]);
    renderApp("/public");

    expect(
      await screen.findByText(
        "No figures have been certified yet. Figures appear here as soon as the agency's certifying official attests to them.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "Machine-readable version of this data (JSON)",
      }),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("shows an API refusal verbatim (fail loudly, even in public)", async () => {
    mockApi({
      "GET /public/metrics/certified": {
        status: 429,
        body: {
          detail:
            "Too many requests from this address. Wait a moment and try again.",
        },
      },
    });
    renderApp("/public");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many requests from this address. Wait a moment and try again.",
    );
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument();
  });

  it("stays reachable signed in: the nav links Public data alongside the authenticated pages, and still sends no token to the public endpoint", async () => {
    signInAs("viewer");
    const calls = mockPublic([certifiedValue]);
    renderApp("/public");

    expect(
      await screen.findByRole("heading", {
        name: "Public data: certified figures",
      }),
    ).toBeInTheDocument();
    // Even with a session, the public endpoint gets no bearer token.
    expect(calls[0].headers["Authorization"]).toBeUndefined();

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(
      within(nav).getByRole("link", { name: "Public data" }),
    ).toHaveAttribute("href", "/public");
    expect(
      within(nav).getByRole("link", { name: "Metrics" }),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });
});
