/**
 * /admin/block-labels — the screen that replaces a shell command (task #34).
 *
 * The behaviours worth pinning are the ones that protect a person who cannot
 * check the result any other way:
 *
 * - saving is never the first thing you can click;
 * - choosing a different file throws away the verdict on the old one;
 * - a partial result is presented as normal, with the leftovers visible;
 * - and the Excel warning is on the page BEFORE the file picker, because by
 *   the time someone has uploaded a mangled file the damage is invisible.
 */

import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";

function result(over: Record<string, unknown> = {}) {
  return { status: 200, body: body(over) };
}

function body(over: Record<string, unknown> = {}) {
  return {
    rows_read: 33202,
    matched: 31998,
    ambiguous: 704,
    unmatched: 480,
    unparseable: 20,
    labels_derived: 66,
    conflicts: 2,
    ambiguous_examples: [],
    unmatched_examples: [],
    unparseable_examples: [],
    conflict_notes: [],
    service_days: [],
    examples_capped_at: 20,
    note: "Nothing has been saved. This is what the file would do.",
    ...over,
  };
}

function csv(name = "tripblock.csv") {
  return new File(["67 - 1E - 06:12,67-1\n"], name, { type: "text/csv" });
}

async function chooseFile(user: ReturnType<typeof userEvent.setup>) {
  const input = screen.getByLabelText(/trip-to-block export/i);
  await user.upload(input as HTMLInputElement, csv());
}

describe("block-name upload", () => {
  it("will not offer to save until a file has been checked", async () => {
    signInAs("certifying_official");
    mockApi({
      "POST /admin/block-labels/preview": () => result(),
    });
    const user = userEvent.setup();
    renderApp("/admin/block-labels");

    await screen.findByRole("heading", { name: /block names/i, level: 1 });
    // THE POINT: no save button exists before a preview.
    expect(
      screen.queryByRole("button", { name: /save these block names/i }),
    ).toBeNull();

    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: /check this file/i }));

    await screen.findByRole("button", { name: /save these block names/i });
  });

  it("checking a file writes nothing — only the preview call is made", async () => {
    signInAs("certifying_official");
    const calls = mockApi({
      "POST /admin/block-labels/preview": () => result(),
      "POST /admin/block-labels/load": () => result({ labels_derived: 66 }),
    });
    const user = userEvent.setup();
    renderApp("/admin/block-labels");

    await screen.findByRole("heading", { name: /block names/i, level: 1 });
    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: /check this file/i }));
    await screen.findByRole("button", { name: /save these block names/i });

    expect(calls.some((c) => c.path.endsWith("/load"))).toBe(false);
  });

  it("shows every count, including the leftovers", async () => {
    signInAs("certifying_official");
    mockApi({ "POST /admin/block-labels/preview": () => result() });
    const user = userEvent.setup();
    renderApp("/admin/block-labels");

    await screen.findByRole("heading", { name: /block names/i, level: 1 });
    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: /check this file/i }));

    await screen.findByText("33,202");
    // Leftovers are shown, not summarised away.
    expect(screen.getByText("704")).toBeTruthy();
    expect(screen.getByText("480")).toBeTruthy();
    expect(screen.getByText("66")).toBeTruthy();
    // And the page says a partial mapping is expected, so 66-from-33,202
    // does not read as a failure.
    expect(screen.getByText(/partial mapping is normal and safe/i)).toBeTruthy();
  });

  it("choosing a different file discards the previous verdict", async () => {
    signInAs("certifying_official");
    mockApi({ "POST /admin/block-labels/preview": () => result() });
    const user = userEvent.setup();
    renderApp("/admin/block-labels");

    await screen.findByRole("heading", { name: /block names/i, level: 1 });
    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: /check this file/i }));
    await screen.findByRole("button", { name: /save these block names/i });

    // A stale verdict beside a new file is how someone approves the wrong
    // thing. It has to disappear the moment the file changes.
    const input = screen.getByLabelText(/trip-to-block export/i);
    await user.upload(input as HTMLInputElement, csv("different.csv"));

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /save these block names/i }),
      ).toBeNull(),
    );
    expect(screen.queryByText("33,202")).toBeNull();
  });

  it("a file with nothing derivable offers no save button at all", async () => {
    signInAs("certifying_official");
    mockApi({
      "POST /admin/block-labels/preview": () =>
        result({ labels_derived: 0, matched: 0, unmatched: 33202 }),
    });
    const user = userEvent.setup();
    renderApp("/admin/block-labels");

    await screen.findByRole("heading", { name: /block names/i, level: 1 });
    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: /check this file/i }));

    await screen.findByText(/nothing to save/i);
    expect(
      screen.queryByRole("button", { name: /save these block names/i }),
    ).toBeNull();
  });

  it("names the blocks two rows disagreed about, and says they were left out", async () => {
    signInAs("certifying_official");
    mockApi({
      "POST /admin/block-labels/preview": () =>
        result({
          conflicts: 1,
          conflict_notes: [
            "Block 4821 was given 2 different names (67-1, 67-9) — left " +
              "out rather than guessed at.",
          ],
        }),
    });
    const user = userEvent.setup();
    renderApp("/admin/block-labels");

    await screen.findByRole("heading", { name: /block names/i, level: 1 });
    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: /check this file/i }));

    await screen.findByText(/left out rather than guessed at/i);
  });

  it("lists the unusable rows with their reasons and says the list is capped", async () => {
    signInAs("certifying_official");
    mockApi({
      "POST /admin/block-labels/preview": () =>
        result({
          unmatched_examples: [
            {
              line: 91,
              trip_name: "999 - 9Z - 23:59",
              block_name: "999-1",
              reason: "No scheduled trip on route 999 departs at 23:59.",
            },
          ],
        }),
    });
    const user = userEvent.setup();
    renderApp("/admin/block-labels");

    await screen.findByRole("heading", { name: /block names/i, level: 1 });
    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: /check this file/i }));

    await screen.findByText("999 - 9Z - 23:59");
    expect(screen.getByText(/No scheduled trip on route 999/)).toBeTruthy();
    // The counts are complete; the examples are not. Saying so stops a
    // reader treating one listed row as the only problem row.
    expect(screen.getByText(/counts above are complete/i)).toBeTruthy();
  });

  it("says which service days were used to separate blocks, and which were not", async () => {
    // A reader who sees only the improved counts would assume every service
    // day was separated. Both outcomes have to be on the page.
    signInAs("certifying_official");
    mockApi({
      "POST /admin/block-labels/preview": () =>
        result({
          service_days: [
            {
              service_day: "Weekday",
              used: true,
              trips_named: 5610,
              explanation:
                "Used to tell blocks apart — service '18' covers 97% of the 5,610 trips this label names, and the next best service covers only 12%.",
            },
            {
              service_day: "Training",
              used: false,
              trips_named: 5848,
              explanation:
                "Not used — no single service explains this label, so the label is left unpaired rather than guessed at.",
            },
          ],
        }),
    });
    const user = userEvent.setup();
    renderApp("/admin/block-labels");

    await screen.findByRole("heading", { name: /block names/i, level: 1 });
    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: /check this file/i }));

    await screen.findByText("Weekday");
    expect(screen.getByText("Training")).toBeTruthy();
    // Text, never colour alone.
    expect(screen.getByText(/Used to tell blocks apart/)).toBeTruthy();
    expect(screen.getByText(/left unpaired rather than guessed at/)).toBeTruthy();
  });

  it("warns about Excel before the file picker, not after the upload", async () => {
    signInAs("certifying_official");
    mockApi({});
    renderApp("/admin/block-labels");

    const warning = await screen.findByText(/silently turns block names/i);
    const picker = screen.getByLabelText(/trip-to-block export/i);
    // Node.compareDocumentPosition: DOCUMENT_POSITION_FOLLOWING === 4.
    expect(warning.compareDocumentPosition(picker) & 4).toBeTruthy();
  });

  it("saving sends the file again and reports what was written", async () => {
    signInAs("certifying_official");
    const calls = mockApi({
      "POST /admin/block-labels/preview": () => result(),
      "POST /admin/block-labels/load": () =>
        result({
          note: "Saved. 66 blocks will now be named the way your run board names them.",
        }),
    });
    const user = userEvent.setup();
    renderApp("/admin/block-labels");

    await screen.findByRole("heading", { name: /block names/i, level: 1 });
    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: /check this file/i }));
    await user.click(
      await screen.findByRole("button", { name: /save these block names/i }),
    );

    await screen.findByText(/Saved\. 66 blocks will now be named/i);
    // The file is uploaded twice on purpose — the server re-derives from the
    // exact bytes it writes rather than trusting a cached preview.
    expect(calls.filter((c) => c.path.includes("block-labels")).length).toBe(2);
    // And once saved, there is no second save to click.
    expect(
      screen.queryByRole("button", { name: /save these block names/i }),
    ).toBeNull();
  });

  it("shows the server's refusal word for word", async () => {
    signInAs("certifying_official");
    const refusal =
      "Line 4 has only one column. This file needs at least two: the trip " +
      "name, then the block name.";
    mockApi({
      "POST /admin/block-labels/preview": () => ({
        status: 422,
        body: { detail: refusal },
      }),
    });
    const user = userEvent.setup();
    renderApp("/admin/block-labels");

    await screen.findByRole("heading", { name: /block names/i, level: 1 });
    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: /check this file/i }));

    await screen.findByText(new RegExp(refusal.slice(0, 40)));
  });

  it("tells a non-certifier why, and shows no upload control", async () => {
    signInAs("data_steward");
    mockApi({});
    renderApp("/admin/block-labels");

    await screen.findByText(/Only a certifying official can load block names/i);
    expect(screen.queryByLabelText(/trip-to-block export/i)).toBeNull();
  });

  it("has no accessibility violations with a result on screen", async () => {
    signInAs("certifying_official");
    mockApi({
      "POST /admin/block-labels/preview": () =>
        result({
          conflict_notes: ["Block 4821 was given 2 different names."],
          unmatched_examples: [
            {
              line: 91,
              trip_name: "999 - 9Z - 23:59",
              block_name: "999-1",
              reason: "No scheduled trip on route 999 departs at 23:59.",
            },
          ],
        }),
    });
    const user = userEvent.setup();
    const { container } = renderApp("/admin/block-labels");

    await screen.findByRole("heading", { name: /block names/i, level: 1 });
    await chooseFile(user);
    await user.click(screen.getByRole("button", { name: /check this file/i }));
    await screen.findByText("33,202");

    await expectNoAxeViolations(container);
  });
});
