/**
 * The review surface (/review — handoff 0047), and the routing around it.
 *
 * What these pin, in the order they matter:
 *
 *  - a read-only role LANDS here, and every other role still lands in the
 *    control room. The redirect is the whole point of the wave: giving a
 *    reviewer a queue of things to do is how they learn to distrust a tool;
 *  - the worklist states, per certification, the period, the signer, the
 *    signing time, how many figures it covers, and the SERVER's verification
 *    verdict — verbatim, including the failing one;
 *  - "could not be checked" is never drawn as a pass, and never as a failure
 *    either: they are different findings;
 *  - the reader is told, plainly and once, that their own reading is
 *    recorded, and what this account cannot open;
 *  - a withheld raw record shows the server's refusal VERBATIM and keeps the
 *    control in the tab order — a blank would be recorded as missing data;
 *  - the room links the calculation runs, which the nav used to hide from
 *    every reader although the API grants them;
 *  - axe reports zero violations on the whole surface.
 */

import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import {
  certificateFixture,
  legacyCertificationRecord,
  lineageTree,
  signedCertificationRecord,
  unsignedCertificateFixture,
} from "./fixtures";
import { copy } from "../copy";

/** The two records the index serves, oldest first, as the API orders them. */
const RECORDS = [legacyCertificationRecord, signedCertificationRecord];

function mockReview(extra: Record<string, unknown> = {}) {
  return mockApi({
    "GET /certifications": { status: 200, body: RECORDS },
    "GET /certifications/cert-7": {
      status: 200,
      body: unsignedCertificateFixture,
    },
    "GET /certifications/cert-42": { status: 200, body: certificateFixture },
    ...(extra as Record<string, never>),
  });
}

/** The row whose first cell links to `id`. */
function rowFor(id: string): HTMLElement {
  return screen
    .getByRole("link", { name: `Certification ${id}` })
    .closest("tr") as HTMLElement;
}

describe("/review — where a reviewer lands", () => {
  it("sends an auditor to /review, not to the control room", async () => {
    signInAs("auditor", "external.reviewer");
    mockReview();
    renderApp("/");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Review" }),
    ).toBeInTheDocument();
    // Not the control room, and not a queue.
    expect(
      screen.queryByRole("heading", { level: 1, name: "Today" }),
    ).not.toBeInTheDocument();
    // Their own room is in the nav.
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Review" })).toHaveAttribute(
      "href",
      "/review",
    );
    // And the role is named in words, not as a raw enum string.
    expect(
      screen.getByText("Signed in as external.reviewer (auditor)"),
    ).toBeInTheDocument();
  });

  it("leaves every other role on /today, with no Review link", async () => {
    signInAs("data_steward");
    mockApi({ "GET /metrics/values": { status: 200, body: [] } });
    renderApp("/");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Today" }),
    ).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: "Review" })).toBeNull();
  });

  it("links the calculation runs for a reader — the API grants them, so the nav stops hiding them", async () => {
    signInAs("auditor");
    mockReview();
    renderApp("/review");
    await screen.findByRole("heading", { level: 1, name: "Review" });

    const user = userEvent.setup();
    const nav = screen.getByRole("navigation", { name: "Main" });
    await user.click(within(nav).getByRole("button", { name: /^Tools/ }));
    expect(
      within(nav).getByRole("link", { name: "Compute figures" }),
    ).toHaveAttribute("href", "/calc-runs");
  });
});

describe("/review — the worklist", () => {
  it("states period, signer, signing time, figure count and the SERVER's verdict for each certification", async () => {
    signInAs("auditor");
    const calls = mockReview();
    renderApp("/review");
    await screen.findByRole("heading", { level: 1, name: "Review" });

    // The signed record: everything verbatim from the API.
    const signed = rowFor("cert-42");
    await waitFor(() =>
      expect(signed).toHaveTextContent("2026-03-01 to 2026-03-31"),
    );
    expect(signed).toHaveTextContent("Alex Rivera, NTD Certifying Official");
    expect(signed).toHaveTextContent("2026-07-02T15:00:00Z");
    expect(within(signed).getByText("2")).toBeInTheDocument();
    expect(within(signed).getByText("Signature verified")).toBeInTheDocument();
    // The verdict's own words, not a paraphrase of them.
    expect(signed).toHaveTextContent(
      certificateFixture.verification.message,
    );

    // The pre-signature record: the absence stated, never a blank.
    const legacy = rowFor("cert-7");
    await waitFor(() =>
      expect(
        within(legacy).getByText("No digital signature"),
      ).toBeInTheDocument(),
    );
    expect(legacy).toHaveTextContent("The account certifier");
    expect(legacy).toHaveTextContent(
      unsignedCertificateFixture.verification.message,
    );
    expect(legacy).toHaveTextContent(/predates the signed document/);

    // The count column is a bare number, so it stacks on the ones place.
    const countCell = within(signed).getByText("2");
    expect(countCell).toHaveClass("figure", "numeric");

    // Every verdict came from the server, one read per certification.
    expect(
      calls.filter((c) => c.path.startsWith("/certifications/")).length,
    ).toBe(2);
    await expectNoAxeViolations();
  });

  it("opens the existing certificate rather than restating it", async () => {
    signInAs("auditor");
    mockReview();
    renderApp("/review");
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("link", { name: "Certification cert-42" }),
    );
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Certification certificate",
      }),
    ).toBeInTheDocument();
    // The signature block is that page's job, and it is there.
    expect(
      screen.getByRole("heading", { name: "Signature" }),
    ).toBeInTheDocument();
  });

  it("renders a FAILED verdict loudly and verbatim — never softened", async () => {
    const failed = {
      ...certificateFixture,
      verification: {
        ...certificateFixture.verification,
        verified: false,
        verdict: "failed",
        message:
          "VERIFICATION FAILED: the stored certification record does not match its signature (the signed bytes or the signature were altered).",
      },
    };
    signInAs("auditor");
    mockReview({
      "GET /certifications/cert-42": { status: 200, body: failed },
    });
    renderApp("/review");
    await screen.findByRole("heading", { level: 1, name: "Review" });

    const row = rowFor("cert-42");
    await waitFor(() =>
      expect(
        within(row).getByText("SIGNATURE CHECK FAILED"),
      ).toBeInTheDocument(),
    );
    expect(row).toHaveTextContent(failed.verification.message);
    await expectNoAxeViolations();
  });

  it("says a check could not be MADE — which is neither a pass nor a failure", async () => {
    signInAs("auditor");
    mockReview({
      "GET /certifications/cert-42": {
        status: 503,
        body: {
          detail:
            "The signing key is not available on this installation right now, so this certificate cannot be checked.",
        },
      },
    });
    renderApp("/review");
    await screen.findByRole("heading", { level: 1, name: "Review" });

    const row = rowFor("cert-42");
    await waitFor(() =>
      expect(within(row).getByText("Could not be checked")).toBeInTheDocument(),
    );
    // The server's words, and NOT the failure label.
    expect(row).toHaveTextContent(/signing key is not available/);
    expect(within(row).queryByText("SIGNATURE CHECK FAILED")).toBeNull();
    expect(within(row).queryByText("Signature verified")).toBeNull();
  });

  it("states the empty record warmly and the load failure verbatim", async () => {
    signInAs("auditor");
    mockApi({ "GET /certifications": { status: 200, body: [] } });
    renderApp("/review");
    expect(
      await screen.findByText(/No certifications are on record yet/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("surfaces a failed list read as an alert, in the server's words", async () => {
    signInAs("auditor");
    mockApi({
      "GET /certifications": {
        status: 500,
        body: { detail: "The certifications table could not be read." },
      },
    });
    renderApp("/review");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The certifications table could not be read.",
    );
  });
});

describe("/review — what the room says out loud", () => {
  it("tells the reader they are on the record, plainly and once", async () => {
    signInAs("auditor");
    mockReview();
    renderApp("/review");

    const heading = await screen.findByRole("heading", {
      name: copy.review.recordHeading,
    });
    const panel = heading.closest("section") as HTMLElement;
    expect(panel).toHaveTextContent(/who read it, which filters they used/);
    expect(panel).toHaveTextContent(/never the entries themselves/);
    expect(panel).toHaveTextContent(copy.review.recordNoWrites);
    // Said once — not repeated as a banner on every render pass.
    expect(
      screen.getAllByText(copy.review.recordBody),
    ).toHaveLength(1);
    // Not a warning: no alert role anywhere on a clean load.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("names the ONE write this account can cause, beside the rule it excepts", async () => {
    // The "no writes" line stopped being absolute when handoff 0047 opened a
    // single route to this role. A rule stated without its carve-out is the
    // same defect this whole surface was built to remove — the product saying
    // one thing and the server doing another — so the exception is asserted
    // to live in the same panel as the rule, not in a tooltip somewhere else.
    signInAs("auditor");
    mockReview();
    renderApp("/review");

    const heading = await screen.findByRole("heading", {
      name: copy.review.recordHeading,
    });
    const panel = heading.closest("section") as HTMLElement;
    expect(panel).toHaveTextContent(copy.review.recordNoWrites);
    expect(panel).toHaveTextContent(copy.review.recordVerify);
    // It must say what the exception COSTS the reviewer: the finding is
    // raised under their name, which is the part a reader would otherwise
    // discover only after pressing the button.
    expect(panel).toHaveTextContent(/data-quality finding/);
    expect(panel).toHaveTextContent(/under your name/);
  });

  it("states what this account cannot open, instead of leaving it to a 403", async () => {
    signInAs("auditor");
    mockReview();
    renderApp("/review");

    const heading = await screen.findByRole("heading", {
      name: copy.review.scopeHeading,
    });
    const panel = heading.closest("section") as HTMLElement;
    for (const item of copy.review.scopeItems) {
      expect(within(panel).getByText(item)).toBeInTheDocument();
    }
    // And the withholding rule, before the reader meets it in the wild.
    expect(panel).toHaveTextContent(/never drawn as an empty one/);
  });

  /**
   * The one that matters most. Rider-location withholding (the API's own
   * rule — raw_payloads.RESTRICTED_MINIMUM_ROLE, not migration 0028, which
   * is the parallel SQL-layer grant for the analyst role)
   * is NOT waived for an auditor, on purpose — and an auditor who sees a
   * blank where contents should be records MISSING DATA, a false finding
   * against an agency that did nothing wrong. So the refusal is drawn, in
   * the server's exact words, at the leaf of the walk this role makes.
   */
  it("draws a withheld raw record as WITHHELD, in the server's own words, for an auditor", async () => {
    const REFUSAL =
      "Your account cannot open the contents of this raw record. This is a " +
      "demand-response (paratransit) source record. Its rows carry pickup " +
      "and dropoff coordinates, which are rider home and destination " +
      "addresses. You can still see this record's label and prove its bytes " +
      "are unaltered — only the contents are withheld.";
    signInAs("auditor");
    mockApi({
      "GET /metrics/values/mv-vrm-1/lineage": {
        status: 200,
        body: lineageTree,
      },
      "GET /raw/records/sha256%3Aaaaa1111": {
        status: 200,
        body: {
          record_id: "sha256:aaaa1111",
          source: "dr_simulated",
          simulated: false,
          connector: "headway-dr",
          connector_version: "0.1.0",
          content_type: "text/csv",
          payload_encoding: "object_ref",
          fetched_at: "2026-07-30T23:26:07Z",
          landed_at: "2026-07-30T23:26:07Z",
          parse_status: "ok",
          parse_error: null,
          stored_bytes: {
            location: "object_store",
            object_key: "raw/dr/trips.csv",
            size_bytes: 5130,
            status: "available",
            note: "Held in the object store.",
          },
          content_address: {
            algorithm: "sha-256",
            digest: "sha256:aaaa1111",
            note: "This record's id is the SHA-256 hash of the bytes as received.",
          },
          sensitivity: {
            classification: "rider_location",
            label: "Rider locations — restricted",
            minimum_role: "data_steward",
            reason: "Its rows carry pickup and dropoff coordinates.",
            preview_allowed: false,
            refusal: REFUSAL,
          },
          decoder: { kind: "delimited_text", note: "A comma-separated file." },
          immutability_note: "Raw records are never edited.",
        },
      },
    });
    renderApp("/metrics/mv-vrm-1/lineage");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Text view" }));
    await user.click(
      (
        await screen.findAllByRole("button", {
          name: "Open the raw source record sha256:aaaa1111",
        })
      )[0],
    );

    // Named, and explained in the server's exact sentence — never a blank
    // and never this UI's paraphrase of the rule.
    expect(await screen.findByText("Contents withheld")).toBeInTheDocument();
    expect(screen.getByText(REFUSAL)).toBeInTheDocument();
    // The chain of custody is intact: the integrity check is still offered,
    // and the refused control is still reachable by keyboard.
    expect(
      screen.getByRole("button", { name: "Verify integrity" }),
    ).toBeEnabled();
    const inspect = screen.getByRole("button", { name: "Look inside" });
    expect(inspect).toHaveAttribute("aria-disabled", "true");
    expect(inspect).toHaveAccessibleDescription(new RegExp("only the contents are withheld"));
    await expectNoAxeViolations();
  });

  it("carries no queue, no tally waiting to be cleared, and no button that acts", async () => {
    signInAs("auditor");
    mockReview();
    renderApp("/review");
    await screen.findByRole("heading", { level: 1, name: "Review" });

    // The page's own content offers nothing to press: every control on the
    // screen belongs to the shell (theme, tour, sign out, nav groups).
    const main = document.querySelector("main") as HTMLElement;
    expect(within(main).queryAllByRole("button")).toEqual([]);
    expect(within(main).queryAllByRole("textbox")).toEqual([]);
  });
});
