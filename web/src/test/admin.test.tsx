/**
 * The admin area (handoff 0025): hub honesty (SSO + Updates cards state,
 * never pretend), user management (create / reset / role / deactivate with
 * the server's lockout fail-safe verbatim at the control), the read-only
 * data-sources room (NO fake add-source form), and the settings room
 * (values verbatim, audited edits, refusals verbatim).
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

const USERS = [
  {
    username: "certifier",
    role: "certifying_official",
    is_active: true,
    created_at: "2026-07-09T15:30:51Z",
  },
  {
    username: "dsteward",
    role: "data_steward",
    is_active: true,
    created_at: "2026-07-09T15:30:51Z",
  },
  {
    username: "parked",
    role: "viewer",
    is_active: false,
    created_at: "2026-07-10T09:00:00Z",
  },
];

// The API's lockout fail-safe refusal, word for word (routers/users.py).
const LOCKOUT_409 =
  "'certifier' is the last active certifying official on this Headway " +
  "instance. Deactivating this account would leave no one able to certify " +
  "reports or manage users and branding, so Headway refuses it. Make " +
  "another account a certifying official first, then try again.";

const SOURCES_STATUS = {
  as_of: "2026-07-28T17:00:00Z",
  window_hours: 24,
  sources: [
    {
      source: "gtfs_rt",
      connector: "headway-gtfs-rt",
      latest_connector_version: "0.1.0",
      records_total: 35105,
      malformed_total: 0,
      first_seen_at: "2026-07-09T14:15:17Z",
      latest_landed_at: "2026-07-22T03:01:50Z",
      latest_fetched_at: "2026-07-22T03:01:49Z",
      latest_age_seconds: 568690,
      records_in_window: 0,
      malformed_in_window: 0,
      simulated: false,
    },
    {
      source: "tides_simulated",
      connector: "headway-tides",
      latest_connector_version: "0.1.0",
      records_total: 3,
      malformed_total: 1,
      first_seen_at: "2026-07-10T17:00:00Z",
      latest_landed_at: "2026-07-10T17:51:23Z",
      latest_fetched_at: "2026-07-10T17:51:22Z",
      latest_age_seconds: 1552117,
      records_in_window: 0,
      malformed_in_window: 0,
      simulated: true,
    },
  ],
  canonical: {
    newest_vehicle_position_at: "2026-07-22T02:58:36Z",
    age_seconds: 568884,
    note:
      "The newest normalized vehicle position, against the database clock " +
      "— the same freshness the live map states.",
  },
  connecting_note:
    "Connecting a new data source is not an in-app action yet. Feeds are " +
    "configured in the deployment's .env file (GTFS and GTFS-Realtime " +
    "URLs), APC/TIDES files land in the watched drop folder or arrive " +
    "over the machine-key ingest API, and vendor exports go through the " +
    "vendor adapters — the step-by-step guide is " +
    "docs/connecting-your-data.md in your Headway installation. In-app " +
    "source configuration is a recorded roadmap item.",
  note: null,
};

const SETTINGS = [
  {
    setting_key: "coverage_threshold",
    setting_value: "0.95",
    value_type: "decimal",
    description:
      "Coverage certifiability line. 0.95 is an ENGINEERING PLACEHOLDER, " +
      "not an FTA number (REGULATORY_TRACKER.md).",
    updated_by: "migration-0014",
    updated_at: "2026-07-09T15:00:00Z",
  },
  {
    setting_key: "gap_threshold_seconds",
    setting_value: "300",
    value_type: "integer",
    description: "Telemetry-gap threshold (engineering default).",
    updated_by: "migration-0014",
    updated_at: "2026-07-09T15:00:00Z",
  },
  {
    setting_key: "brand_color_primary",
    setting_value: "#1a5fb4",
    value_type: "text",
    description: "Primary brand color.",
    updated_by: "migration-0015",
    updated_at: "2026-07-09T15:00:00Z",
  },
  {
    setting_key: "agency_display_name",
    setting_value: "Transit Agency",
    value_type: "text",
    description: "The agency's display name.",
    updated_by: "migration-0015",
    updated_at: "2026-07-09T15:00:00Z",
  },
];

describe("/admin — the hub", () => {
  it("shows the doors and the two honest cards to the certifying official", async () => {
    signInAs("certifying_official");
    mockApi({});
    renderApp("/admin");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Admin" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage users" })).toHaveAttribute(
      "href",
      "/admin/users",
    );
    expect(
      screen.getByRole("link", { name: "View data sources" }),
    ).toHaveAttribute("href", "/admin/sources");
    // Branding keeps its existing route, linked from the hub.
    expect(screen.getByRole("link", { name: "Edit branding" })).toHaveAttribute(
      "href",
      "/settings/branding",
    );
    expect(screen.getByRole("link", { name: "Edit settings" })).toHaveAttribute(
      "href",
      "/admin/settings",
    );
    await expectNoAxeViolations();
  });

  it("SSO card is honest: designed-not-available, cites ADR-0011, and has NO toggle or setup control", async () => {
    signInAs("certifying_official");
    mockApi({});
    renderApp("/admin");

    const ssoHeading = await screen.findByRole("heading", {
      name: "Single sign-on",
    });
    const card = ssoHeading.closest("section")!;
    expect(card).toHaveTextContent(
      "Single sign-on with Entra ID, Google, or Okta is designed for Headway but not available yet.",
    );
    expect(card).toHaveTextContent("ADR-0011");
    expect(card).toHaveTextContent(
      "every account is a local Headway account",
    );
    // Nothing pretends: no button, no checkbox, no switch, no input.
    expect(within(card).queryAllByRole("button")).toEqual([]);
    expect(within(card).queryAllByRole("checkbox")).toEqual([]);
    expect(within(card).queryAllByRole("switch")).toEqual([]);
    expect(within(card).queryAllByRole("textbox")).toEqual([]);
  });

  it("Updates card is honest: server-side updating, both commands verbatim, no button that acts", async () => {
    signInAs("certifying_official");
    mockApi({});
    renderApp("/admin");

    const heading = await screen.findByRole("heading", { name: "Updates" });
    const card = heading.closest("section")!;
    expect(card).toHaveTextContent(
      "Updating Headway happens on the server, by an administrator — not from this page.",
    );
    // The two commands, verbatim.
    expect(card).toHaveTextContent(
      "./install/install.sh --update-from-source",
    );
    expect(card).toHaveTextContent("./install/install.sh --check-updates");
    // The why, stated: a web session must never replace its own software.
    expect(card).toHaveTextContent(
      "a web session must never be able to replace the software it runs in",
    );
    expect(within(card).queryAllByRole("button")).toEqual([]);
  });

  it("is presented to other roles as not-allowed, in plain language", async () => {
    signInAs("data_steward");
    mockApi({});
    renderApp("/admin");
    expect(
      await screen.findByText(/Only a certifying official can use the admin/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Manage users" })).toBeNull();
  });

  it("nav shows Admin to the certifying official only (UX; the API enforces)", async () => {
    signInAs("certifying_official");
    mockApi({});
    renderApp("/admin");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Admin" })).toBeInTheDocument();
  });

  it("nav hides Admin from a data steward", async () => {
    signInAs("data_steward");
    mockApi({});
    renderApp("/admin");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: "Admin" })).toBeNull();
  });
});

describe("/admin/users", () => {
  it("lists accounts (role, status, created) with no password material anywhere", async () => {
    signInAs("certifying_official", "certifier");
    mockApi({ "GET /users": { status: 200, body: USERS } });
    renderApp("/admin/users");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("certifier (you)")).toBeInTheDocument();
    expect(within(table).getByText("dsteward")).toBeInTheDocument();
    expect(within(table).getByText("Deactivated")).toBeInTheDocument();
    expect(within(table).getAllByText("Active")).toHaveLength(2);
    expect(document.body.textContent).not.toMatch(/\$2b\$|password_hash/);
    await expectNoAxeViolations();
  });

  it("creates a user and shows the confirmation; the server's refusals render verbatim", async () => {
    const user = userEvent.setup();
    signInAs("certifying_official", "certifier");
    let created = false;
    const calls = mockApi({
      "GET /users": () => ({
        status: 200,
        body: created
          ? [
              ...USERS,
              {
                username: "nadia.ops",
                role: "data_steward",
                is_active: true,
                created_at: "2026-07-28T17:30:00Z",
              },
            ]
          : USERS,
      }),
      "POST /users": (call) => {
        const body = call.body as { username: string };
        if (body.username === "has space") {
          return {
            status: 422,
            body: {
              detail:
                "Usernames can use only letters, numbers, dots, hyphens or underscores, with no spaces — the same rule the installer applies. Please choose a different username.",
            },
          };
        }
        created = true;
        return {
          status: 201,
          body: {
            username: "nadia.ops",
            role: "data_steward",
            is_active: true,
            created_at: "2026-07-28T17:30:00Z",
            audit_event_id: 99,
          },
        };
      },
    });
    renderApp("/admin/users");

    // Refused username first: the installer-rule 422, verbatim.
    await user.type(await screen.findByLabelText("Username"), "has space");
    await user.type(
      screen.getByLabelText("Temporary password"),
      "a-fine-password",
    );
    await user.click(screen.getByRole("button", { name: "Create user" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Usernames can use only letters, numbers, dots, hyphens or underscores",
    );

    // Then a good one.
    const username = screen.getByLabelText("Username");
    await user.clear(username);
    await user.type(username, "nadia.ops");
    await user.selectOptions(screen.getByLabelText("Role"), "data_steward");
    await user.click(screen.getByRole("button", { name: "Create user" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Account 'nadia.ops' created as data steward.",
    );
    // The list was RE-READ from the server, not client-appended.
    expect(
      await within(screen.getByRole("table")).findByText("nadia.ops"),
    ).toBeInTheDocument();
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts.at(-1)?.body).toEqual({
      username: "nadia.ops",
      role: "data_steward",
      password: "a-fine-password",
    });
  });

  it("states the lockout fail-safe at the last admin's control (aria-disabled + reason) and surfaces the server 409 verbatim on click", async () => {
    const user = userEvent.setup();
    signInAs("certifying_official", "certifier");
    const calls = mockApi({
      "GET /users": { status: 200, body: USERS },
      "POST /users/certifier/deactivate": {
        status: 409,
        body: { detail: LOCKOUT_409 },
      },
    });
    renderApp("/admin/users");

    const deactivate = await screen.findByRole("button", {
      name: "Deactivate certifier",
    });
    // aria-disabled (never native disabled): the reason is visible and
    // programmatically attached.
    expect(deactivate).toHaveAttribute("aria-disabled", "true");
    expect(deactivate).toHaveAccessibleDescription(
      /last active certifying official/,
    );
    expect(
      screen.getByText(
        /Headway refuses to deactivate or demote the last one/,
      ),
    ).toBeInTheDocument();

    // The click is NOT swallowed — the server answers and its refusal
    // renders verbatim at the control.
    await user.click(deactivate);
    expect(await screen.findByRole("alert")).toHaveTextContent(LOCKOUT_409);
    expect(
      calls.some((c) => c.path === "/users/certifier/deactivate"),
    ).toBe(true);
    await expectNoAxeViolations();
  });

  it("deactivates a non-admin (with the server's session note verbatim) and reactivates", async () => {
    const user = userEvent.setup();
    signInAs("certifying_official", "certifier");
    let active = true;
    mockApi({
      "GET /users": () => ({
        status: 200,
        body: USERS.map((u) =>
          u.username === "dsteward" ? { ...u, is_active: active } : u,
        ),
      }),
      "POST /users/dsteward/deactivate": () => {
        active = false;
        return {
          status: 200,
          body: {
            username: "dsteward",
            is_active: false,
            note: "New sign-ins for 'dsteward' are refused from now on. If this person is signed in right now, that session ends on its own within 30 minutes (when their current session token expires).",
            audit_event_id: 100,
          },
        };
      },
      "POST /users/dsteward/reactivate": () => {
        active = true;
        return {
          status: 200,
          body: {
            username: "dsteward",
            is_active: true,
            note: null,
            audit_event_id: 101,
          },
        };
      },
    });
    renderApp("/admin/users");

    await user.click(
      await screen.findByRole("button", { name: "Deactivate dsteward" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "'dsteward' has been deactivated. New sign-ins for 'dsteward' are refused from now on.",
    );
    // Re-read state: the button flips to Reactivate.
    await user.click(
      await screen.findByRole("button", { name: "Reactivate dsteward" }),
    );
    expect(
      await screen.findByRole("button", { name: "Deactivate dsteward" }),
    ).toBeInTheDocument();
  });

  it("resets a password through its own labeled form", async () => {
    const user = userEvent.setup();
    signInAs("certifying_official", "certifier");
    const calls = mockApi({
      "GET /users": { status: 200, body: USERS },
      "POST /users/dsteward/reset-password": {
        status: 200,
        body: { username: "dsteward", audit_event_id: 102 },
      },
    });
    renderApp("/admin/users");

    await user.click(
      await screen.findByRole("button", {
        name: "Reset password for dsteward",
      }),
    );
    await user.type(
      screen.getByLabelText("New password for dsteward"),
      "a-new-password",
    );
    await user.click(
      screen.getByRole("button", { name: "Save new password" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Password for 'dsteward' has been reset.",
    );
    const post = calls.find(
      (c) => c.path === "/users/dsteward/reset-password",
    );
    expect(post?.body).toEqual({ password: "a-new-password" });
  });

  it("changes a role and renders the server's session-lifetime note verbatim", async () => {
    const user = userEvent.setup();
    signInAs("certifying_official", "certifier");
    mockApi({
      "GET /users": { status: 200, body: USERS },
      "POST /users/dsteward/role": {
        status: 200,
        body: {
          username: "dsteward",
          role: "report_preparer",
          note: "'dsteward' is a report preparer from their next sign-in. If this person is signed in right now, their current session keeps the data steward role for up to 30 minutes (until their session token expires).",
          audit_event_id: 103,
        },
      },
    });
    renderApp("/admin/users");

    await user.selectOptions(
      await screen.findByLabelText("Role for dsteward"),
      "report_preparer",
    );
    const changeButtons = screen.getAllByRole("button", {
      name: "Change role",
    });
    await user.click(changeButtons[1]); // dsteward's row
    expect(await screen.findByRole("status")).toHaveTextContent(
      "'dsteward' is now a report preparer. 'dsteward' is a report preparer from their next sign-in.",
    );
  });
});

describe("/admin/sources", () => {
  it("renders what each source delivered — counts, latest data, refused rows, SIMULATED badge — and NO add-source form", async () => {
    signInAs("certifying_official", "certifier");
    mockApi({ "GET /sources/status": { status: 200, body: SOURCES_STATUS } });
    renderApp("/admin/sources");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("gtfs_rt")).toBeInTheDocument();
    expect(within(table).getByText("35,105")).toBeInTheDocument();
    // The simulated source is badged — text, not color alone.
    const simulatedRow = within(table)
      .getByText("tides_simulated")
      .closest("tr")!;
    expect(
      within(simulatedRow).getByText("Simulated data"),
    ).toBeInTheDocument();

    // The honest connecting story, VERBATIM, plus the teaching panel.
    expect(
      screen.getByText(SOURCES_STATUS.connecting_note),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "How connecting works today" }),
    ).toBeInTheDocument();
    // Named in the server note AND the teaching bullet.
    expect(
      screen.getAllByText(/docs\/connecting-your-data\.md/).length,
    ).toBeGreaterThan(1);

    // BINDING: no fake add-source affordance of any kind.
    expect(screen.queryByRole("button", { name: /add/i })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(document.body.textContent).not.toMatch(/Add (a )?source/i);

    // Canonical liveness, verbatim note.
    expect(
      screen.getByText(SOURCES_STATUS.canonical.note),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("opens for a data steward too — the same rule as the API", async () => {
    signInAs("data_steward");
    mockApi({ "GET /sources/status": { status: 200, body: SOURCES_STATUS } });
    renderApp("/admin/sources");
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });

  it("a viewer gets the plain not-allowed note and no request is made", async () => {
    signInAs("viewer");
    const calls = mockApi({});
    renderApp("/admin/sources");
    expect(
      await screen.findByText(/Only a certifying official can use the admin/),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/sources/status")).toBe(false);
  });
});

describe("/admin/settings", () => {
  it("lists calc knobs with values EXACTLY as served, basis descriptions, and excludes branding keys", async () => {
    signInAs("certifying_official", "certifier");
    mockApi({ "GET /settings": { status: 200, body: SETTINGS } });
    renderApp("/admin/settings");

    // Values verbatim in the edit fields.
    expect(
      await screen.findByLabelText("Value for coverage_threshold"),
    ).toHaveValue("0.95");
    expect(
      screen.getByLabelText("Value for gap_threshold_seconds"),
    ).toHaveValue("300");
    // The basis citation (the served description) renders verbatim.
    expect(
      screen.getByText(/ENGINEERING PLACEHOLDER, not an FTA number/),
    ).toBeInTheDocument();
    // Branding keys have their own room — not duplicated here.
    expect(
      screen.queryByLabelText("Value for brand_color_primary"),
    ).toBeNull();
    expect(
      screen.queryByLabelText("Value for agency_display_name"),
    ).toBeNull();
    expect(
      screen.getByText(/Branding \(agency name, colors, logo\) has its own room/),
    ).toBeInTheDocument();
    // The sandbox door (model first, apply here).
    expect(
      screen.getByRole("link", { name: "Open the Settings sandbox" }),
    ).toHaveAttribute("href", "/sandbox");
    await expectNoAxeViolations();
  });

  it("saves a knob (PUT /settings/{key}) and quotes the stored value exactly; refusals verbatim", async () => {
    const user = userEvent.setup();
    signInAs("certifying_official", "certifier");
    let value = "300";
    const calls = mockApi({
      "GET /settings": () => ({
        status: 200,
        body: SETTINGS.map((s) =>
          s.setting_key === "gap_threshold_seconds"
            ? { ...s, setting_value: value }
            : s,
        ),
      }),
      "PUT /settings/gap_threshold_seconds": (call) => {
        const proposed = (call.body as { value: string }).value;
        if (proposed === "abc") {
          return {
            status: 422,
            body: {
              detail:
                "'abc' is not a whole number, so it cannot be the value of the 'gap_threshold_seconds' setting. Please send a whole number of seconds, for example '300'.",
            },
          };
        }
        value = proposed;
        return {
          status: 200,
          body: {
            ...SETTINGS[1],
            setting_value: proposed,
            updated_by: "certifier",
            updated_at: "2026-07-28T18:00:00Z",
            audit_event_id: 104,
          },
        };
      },
    });
    renderApp("/admin/settings");

    const input = await screen.findByLabelText(
      "Value for gap_threshold_seconds",
    );
    // A bad value: the server's type refusal, verbatim.
    await user.clear(input);
    await user.type(input, "abc");
    await user.click(
      screen.getByRole("button", { name: "Save gap_threshold_seconds" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "'abc' is not a whole number",
    );

    // A good value: saved, quoted exactly, audited server-side.
    await user.clear(input);
    await user.type(input, "240");
    await user.click(
      screen.getByRole("button", { name: "Save gap_threshold_seconds" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "'gap_threshold_seconds' is now 240.",
    );
    const puts = calls.filter(
      (c) => c.path === "/settings/gap_threshold_seconds",
    );
    expect(puts.map((c) => c.body)).toEqual([
      { value: "abc" },
      { value: "240" },
    ]);
    await waitFor(() => expect(input).toHaveValue("240"));
  });

  it("is presented to non-certifiers as not-allowed", async () => {
    signInAs("report_preparer");
    mockApi({});
    renderApp("/admin/settings");
    expect(
      await screen.findByText(/Only a certifying official can use the admin/),
    ).toBeInTheDocument();
  });
});
