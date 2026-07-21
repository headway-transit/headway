/**
 * Teaching empty states (handoff 0021, design point 4): the main views'
 * empty states each carry one warm sentence + the concrete first action
 * (link or command), in the house voice — never blank, never urgent.
 * Role-aware where the action belongs to a role: the steward is told what
 * to do; everyone else is told how the room fills in.
 */

import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { mockApi, renderApp, signInAs } from "./helpers";
import { samplingOptions } from "./fixtures";

const EMPTY_DEADLINES = {
  month: "2026-07",
  ss40: [],
  ss40_citation: "cite",
  ss40_note: "note",
  ss50: [],
  ss50_citation: "cite",
};

describe("teaching empty states (handoff 0021 #4)", () => {
  it("/metrics before data: warm sentence + the concrete first command", async () => {
    signInAs("viewer");
    mockApi({ "GET /metrics/values": { status: 200, body: [] } });
    renderApp("/metrics");

    expect(
      await screen.findByText(/Nothing computed yet — that is the honest state/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/python -m headway_calc\.runner/),
    ).toBeInTheDocument();
    // Warm, not urgent: no alert voice on an empty room.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("/dashboard before data: warm sentence + the concrete first command", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [] },
      "GET /dq/issues": { status: 200, body: [] },
    });
    renderApp("/dashboard");

    expect(
      await screen.findByText(/an empty dashboard is a truthful one/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/python -m headway_calc\.runner/),
    ).toBeInTheDocument();
  });

  it("/safety with no events: the steward gets the first action, the reader gets the orientation", async () => {
    signInAs("data_steward");
    mockApi({
      "GET /safety/events": { status: 200, body: [] },
      "GET /safety/deadlines": { status: 200, body: EMPTY_DEADLINES },
    });
    const { unmount } = renderApp("/safety");

    expect(
      await screen.findByText(/an empty log is a good month/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/record it with the form above/),
    ).toBeInTheDocument();
    unmount();

    signInAs("viewer");
    mockApi({
      "GET /safety/events": { status: 200, body: [] },
      "GET /safety/deadlines": { status: 200, body: EMPTY_DEADLINES },
    });
    renderApp("/safety");
    expect(
      await screen.findByText(/A data steward records events/),
    ).toBeInTheDocument();
  });

  it("/sampling with no plans: the steward gets the first action, the reader gets the orientation", async () => {
    signInAs("data_steward");
    mockApi({
      "GET /sampling/options": { status: 200, body: samplingOptions },
      "GET /sampling/plans": { status: 200, body: [] },
    });
    const { unmount } = renderApp("/sampling");

    expect(
      await screen.findByText(/nothing needs sampling until passenger miles/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Create the first plan above/),
    ).toBeInTheDocument();
    unmount();

    signInAs("viewer");
    mockApi({
      "GET /sampling/options": { status: 200, body: samplingOptions },
      "GET /sampling/plans": { status: 200, body: [] },
    });
    renderApp("/sampling");
    expect(
      await screen.findByText(/A data steward creates the first plan/),
    ).toBeInTheDocument();
  });
});
