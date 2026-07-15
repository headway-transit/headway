/**
 * /compare (handoff 0017, design point 1) — the binding rules under test:
 * cells keep their receipt affordance; deltas render SIGN-NEUTRALLY unless
 * the response's registry direction defines better/worse; simulated badges
 * carry through; certified-vs-uncertified comparisons label both; every
 * figure and delta is the server's string verbatim.
 *
 * Fixtures are shaped exactly like services/api routers/metrics.py's
 * CompareResponse (reconciled against the regenerated openapi.json,
 * 2026-07-14).
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
import {
  compareCoverageResponse,
  compareVersionsResponse,
  compareVocabularyValues,
} from "./fixtures";

const PERIOD_KEY = "2026-06-01..2026-07-01";

async function pickVersionsComparison(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(
    await screen.findByLabelText("Which figure?"),
    "vrh",
  );
  await user.selectOptions(screen.getByLabelText("Which period?"), PERIOD_KEY);
  // Tick ORDER sets the baseline: 0.3.0 first.
  await user.click(screen.getByRole("checkbox", { name: /vrh_v0 0\.3\.0/ }));
  await user.click(screen.getByRole("checkbox", { name: /vrh_v0 0\.4\.0/ }));
}

describe("/compare", () => {
  it("keeps the compare button off (with the reason at the button) until 2–4 comparands are picked", async () => {
    signInAs("viewer");
    const calls = mockApi({
      "GET /metrics/values": { status: 200, body: compareVocabularyValues },
      "GET /metrics/compare": { status: 200, body: compareVersionsResponse },
    });
    const user = userEvent.setup();
    renderApp("/compare");

    await user.selectOptions(
      await screen.findByLabelText("Which figure?"),
      "vrh",
    );
    await user.selectOptions(
      screen.getByLabelText("Which period?"),
      PERIOD_KEY,
    );
    const button = screen.getByRole("button", { name: "Compare" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(
      screen.getByText(
        "Pick at least two and at most four comparands to compare.",
      ),
    ).toBeInTheDocument();

    // A refused click is refused perceivably — nothing is sent.
    await user.click(button);
    expect(
      calls.filter((c) => c.path === "/metrics/compare"),
    ).toHaveLength(0);

    // One comparand is still not a comparison.
    await user.click(screen.getByRole("checkbox", { name: /vrh_v0 0\.3\.0/ }));
    expect(button).toHaveAttribute("aria-disabled", "true");

    await user.click(screen.getByRole("checkbox", { name: /vrh_v0 0\.4\.0/ }));
    expect(button).not.toHaveAttribute("aria-disabled");

    await expectNoAxeViolations();
  });

  it("renders cards + matrix with verbatim figures, SIGN-NEUTRAL deltas, carried badges, and both statuses labeled", async () => {
    signInAs("viewer");
    const calls = mockApi({
      "GET /metrics/values": { status: 200, body: compareVocabularyValues },
      "GET /metrics/compare": { status: 200, body: compareVersionsResponse },
    });
    const user = userEvent.setup();
    renderApp("/compare");

    await pickVersionsComparison(user);
    // The first ticked comparand is marked as the baseline in the picker.
    const picker = screen.getByRole("region", { name: "What to compare" });
    expect(within(picker).getAllByText("Baseline").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Compare" }));

    // The request carries metric + ordered comparand tokens (first =
    // baseline), per the parallel-build contract.
    const compareCall = calls.find((c) => c.path === "/metrics/compare");
    expect(compareCall?.url).toContain("metric=vrh");
    const params = new URLSearchParams(compareCall!.url.split("?")[1]);
    // The token format GET /metrics/compare parses:
    // '<start>..<end>@<calc_name>:<calc_version>', first = baseline.
    expect(params.getAll("comparand")).toEqual([
      "2026-06-01..2026-07-01@vrh_v0:0.3.0",
      "2026-06-01..2026-07-01@vrh_v0:0.4.0",
    ]);

    // Card row: BOTH figures verbatim (trailing digits intact).
    const cards = await screen.findByRole("region", { name: "Side by side" });
    expect(within(cards).getAllByText("8203.40").length).toBeGreaterThan(0);
    expect(within(cards).getAllByText("9758.55").length).toBeGreaterThan(0);

    // The delta is the SERVER's magnitude, described SIGN-NEUTRALLY: a
    // direction word ("more"), never a judgement ("better"/"worse") for a
    // metric whose registry direction is neutral.
    expect(
      within(cards).getAllByText(/1555\.15 more than the baseline/).length,
    ).toBeGreaterThan(0);
    expect(within(cards).queryByText(/better/)).not.toBeInTheDocument();
    expect(within(cards).queryByText(/worse/)).not.toBeInTheDocument();

    // Certified vs uncertified: the SERVER's label-both note is shown
    // verbatim and BOTH figures carry their status.
    expect(
      screen.getByText(/mixes certified and uncertified figures/),
    ).toBeInTheDocument();
    expect(within(cards).getAllByText("certified").length).toBeGreaterThan(0);
    expect(within(cards).getAllByText("uncertified").length).toBeGreaterThan(0);

    // The matrix: scope rows, a stated (never blank) refused cell, and the
    // simulated badge carried through the comparison surface.
    const matrix = screen.getByRole("region", { name: "Detail matrix" });
    expect(within(matrix).getByText("Agency-wide")).toBeInTheDocument();
    expect(within(matrix).getByText("Mode: Bus")).toBeInTheDocument();
    expect(
      within(matrix).getByText(
        "The 0.4.0 run refused this mode: trip coverage 0.41 is below the coverage threshold 0.95.",
      ),
    ).toBeInTheDocument();
    expect(
      within(matrix).getAllByText("Simulated data").length,
    ).toBeGreaterThan(0);

    await expectNoAxeViolations();
  });

  it("keeps the receipt affordance on every cell: a cell's figure opens the full Receipt in a dialog", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: compareVocabularyValues },
      "GET /metrics/compare": { status: 200, body: compareVersionsResponse },
    });
    const user = userEvent.setup();
    renderApp("/compare");

    await pickVersionsComparison(user);
    await user.click(screen.getByRole("button", { name: "Compare" }));

    const matrix = await screen.findByRole("region", {
      name: "Detail matrix",
    });
    await user.click(
      within(matrix).getByRole("button", {
        name: /9758\.55.*Receipt for Vehicle Revenue Hours \(VRH\), Agency-wide/,
      }),
    );

    // The SAME Receipt as every other surface: story line, the verified
    // FTA rule, and the walk to raw records.
    const dialog = await screen.findByRole("dialog", { name: "Receipt" });
    expect(
      within(dialog).getByText(/9758\.55 hours — Vehicle Revenue Hours/),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("The FTA rule inside this number"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("link", {
        name: /Walk this number to its raw records/,
      }),
    ).toBeInTheDocument();

    // Axe holds with the dialog open, then focus returns on close.
    await expectNoAxeViolations();
    await user.click(
      within(dialog).getByRole("button", { name: "Close the receipt" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("colors a delta ONLY for a registry-directed metric, and then always with the word (worse, here)", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: compareVocabularyValues },
      "GET /metrics/compare": { status: 200, body: compareCoverageResponse },
    });
    const user = userEvent.setup();
    renderApp("/compare");

    // Periods mode: one calculation across two periods.
    await user.selectOptions(
      await screen.findByLabelText("Which figure?"),
      "vrh",
    );
    await user.selectOptions(
      screen.getByLabelText("Compare across"),
      "periods",
    );
    await user.selectOptions(
      screen.getByLabelText("Which calculation?"),
      "vrh_v0@0.4.0",
    );
    await user.click(
      screen.getByRole("checkbox", { name: /2026-05-01 to 2026-06-01/ }),
    );
    await user.click(
      screen.getByRole("checkbox", { name: /2026-06-01 to 2026-07-01/ }),
    );
    await user.click(screen.getByRole("button", { name: "Compare" }));

    // direction=higher_is_better + a negative server delta = "worse", in
    // words AND color class — never color alone.
    const cards = await screen.findByRole("region", { name: "Side by side" });
    const delta = within(cards)
      .getAllByText(/0\.0136 less than the baseline/)[0]
      .closest(".delta") as HTMLElement;
    expect(delta).toHaveTextContent("worse");
    expect(delta.className).toContain("worse");

    await expectNoAxeViolations();
  });

  it("surfaces a compare refusal verbatim", async () => {
    signInAs("viewer");
    const refusal =
      "Comparands must share a metric. vrh_v0 does not compute upt.";
    mockApi({
      "GET /metrics/values": { status: 200, body: compareVocabularyValues },
      "GET /metrics/compare": { status: 422, body: { detail: refusal } },
    });
    const user = userEvent.setup();
    renderApp("/compare");

    await pickVersionsComparison(user);
    await user.click(screen.getByRole("button", { name: "Compare" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(refusal);
  });
});
