/**
 * The single-sign-on configuration screen (handoff 0046).
 *
 * The card on /admin was honest about not existing for weeks. Now the screen
 * behind it is real, and these tests hold it to the properties that make the
 * difference between a working integration and a support call:
 *
 * - the client secret is show-once — never prefilled, never displayed back;
 * - server refusals appear verbatim at the control that caused them;
 * - `certifying_official` is absent from the mapping choices AND the screen
 *   says why, so the omission does not read as an oversight;
 * - "test this configuration" reports each step in words an administrator
 *   can act on, with the verdict in TEXT, never colour alone;
 * - the whole screen is keyboard-reachable and passes the axe gate.
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

const CONFIGURED = {
  configured: true,
  discovery_url:
    "https://idp.example.gov/realms/agency/.well-known/openid-configuration",
  client_id: "headway-api",
  client_secret_set: true,
  redirect_uri: "https://headway.example.gov/auth/callback",
  groups_claim: "groups",
  username_claim: "preferred_username",
  clock_skew_seconds: 120,
  ca_bundle_path: null,
  button_label: "Sign in with County SSO",
  is_enabled: true,
  updated_by: "certifier",
  updated_at: "2026-08-01T09:00:00Z",
  secret_storage_available: true,
  disabled_by_environment: false,
};

const UNCONFIGURED = {
  ...CONFIGURED,
  configured: false,
  discovery_url: null,
  client_id: null,
  client_secret_set: false,
  redirect_uri: null,
  button_label: "Sign in with single sign-on",
  is_enabled: false,
  updated_by: null,
  updated_at: null,
};

const MAPPINGS = [
  {
    mapping_id: "m-1",
    claim_value: "3f7a-transit-stewards",
    headway_role: "data_steward",
    role_label: "data steward",
    note: "Transit data team",
    created_by: "certifier",
    created_at: "2026-08-01T09:05:00Z",
  },
  {
    mapping_id: "m-2",
    claim_value: "9b21-external-audit",
    headway_role: "auditor",
    role_label: "auditor",
    note: null,
    created_by: "certifier",
    created_at: "2026-08-01T09:06:00Z",
  },
];

/** The API's plain-language refusal of an IdP-granted certifying official. */
const CERT_OFFICIAL_422 =
  "Headway will not let your identity provider grant the certifying " +
  "official role. Certifying is a legal attestation that figures sent to " +
  "the federal government are correct, so who may do it has to be decided " +
  "inside Headway and recorded in Headway's audit trail — not by a group " +
  "membership that is changed elsewhere, by people Headway cannot see. Map " +
  "this group to another role here, then make the specific people who " +
  "certify into certifying officials under Admin -> Users. They will still " +
  "sign in through your identity provider.";

async function openSso(
  routes: Parameters<typeof mockApi>[0] = {},
): Promise<ReturnType<typeof mockApi>> {
  const calls = mockApi(routes);
  renderApp("/admin");
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole("button", { name: "Set up single sign-on" }),
  );
  return calls;
}

describe("/admin — single sign-on", () => {
  it("opens the settings from the hub card and shows the stored values", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
    });

    expect(
      await screen.findByRole("heading", { name: "Your identity provider" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Discovery address")).toHaveValue(
      CONFIGURED.discovery_url,
    );
    expect(screen.getByLabelText("Application (client) id")).toHaveValue(
      "headway-api",
    );
    expect(screen.getByLabelText("Group claim")).toHaveValue("groups");
    expect(
      screen.getByLabelText("Clock difference allowed (seconds)"),
    ).toHaveValue(120);
    await expectNoAxeViolations();
  });

  it("never prefills or displays the stored client secret", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
    });

    const secret = await screen.findByLabelText("Client secret");
    // Show-once: blank, with a placeholder that says a secret IS stored.
    expect(secret).toHaveValue("");
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveAttribute(
      "placeholder",
      "Stored — leave blank to keep it",
    );
    expect(document.body).toHaveTextContent(
      "Headway cannot show you the stored one, because it is encrypted and never displayed again.",
    );
  });

  it("leaving the secret blank keeps the stored one; it is not sent as empty", async () => {
    signInAs("certifying_official");
    const calls = await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
      "PUT /auth/oidc/config": {
        status: 200,
        body: { ...CONFIGURED, groups_claim: "roles", audit_event_id: 12 },
      },
    });
    const user = userEvent.setup();

    const groups = await screen.findByLabelText("Group claim");
    await user.clear(groups);
    await user.type(groups, "roles");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Settings saved.",
    );
    const put = calls.find((c) => c.method === "PUT")!;
    const body = put.body as Record<string, unknown>;
    expect(body.groups_claim).toBe("roles");
    // null = keep. An empty string would CLEAR it, which is a different act.
    expect(body.client_secret).toBeNull();
  });

  it("warns before the admin types a secret when the server has nowhere to keep it", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": {
        status: 200,
        body: { ...UNCONFIGURED, secret_storage_available: false },
      },
      "GET /auth/oidc/mappings": { status: 200, body: [] },
    });

    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((a) => a.textContent?.includes(
      "This server has nowhere safe to keep a secret yet",
    ))).toBe(true);
    expect(document.body).toHaveTextContent(
      "HEADWAY_SECRET_ENCRYPTION_KEY",
    );
  });

  it("shows the server's refusals verbatim at the control that caused them", async () => {
    signInAs("certifying_official");
    const HTTP_REFUSAL =
      "The discovery address must use https://, not http://. Headway " +
      "refuses to fetch identity-provider configuration over an " +
      "unencrypted connection, because anyone on the network could replace " +
      "it and take over every sign-in. (http:// is allowed only for " +
      "localhost, so a developer can test against a provider on the same " +
      "machine.)";
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: UNCONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: [] },
      "PUT /auth/oidc/config": {
        status: 422,
        body: { detail: HTTP_REFUSAL },
      },
    });
    const user = userEvent.setup();

    await user.type(
      await screen.findByLabelText("Discovery address"),
      "http://idp.example.gov/.well-known/openid-configuration",
    );
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((a) => a.textContent === HTTP_REFUSAL)).toBe(true);
  });

  it("explains the TLS-inspecting-proxy field without ever offering to skip checking", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
    });

    expect(
      await screen.findByLabelText("Certificate authority file (optional)"),
    ).toBeInTheDocument();
    expect(document.body).toHaveTextContent(
      "Headway will not skip certificate checking: that would let anyone on the network impersonate your provider.",
    );
    // There is no control anywhere on this screen that turns verification off.
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(1);
    expect(checkboxes[0]).toHaveAccessibleName("Turn single sign-on on");
  });

  // -----------------------------------------------------------------------
  // The mapping table — the wave's central security decision, on screen
  // -----------------------------------------------------------------------

  it("lists the configured group mappings", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
    });

    const row = (await screen.findByText("3f7a-transit-stewards")).closest(
      "tr",
    )!;
    expect(within(row).getByText("Data steward")).toBeInTheDocument();
    expect(within(row).getByText("Transit data team")).toBeInTheDocument();
    expect(
      screen.getByText("9b21-external-audit").closest("tr")!,
    ).toHaveTextContent("Auditor");
  });

  it("says plainly that an unmapped person is refused and no account is created", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: [] },
    });

    expect(await screen.findByText(/No groups are mapped yet/)).toHaveTextContent(
      "every single sign-on attempt is refused and no accounts are created",
    );
    expect(document.body).toHaveTextContent(
      "they are refused and no account is created for them — Headway never guesses",
    );
  });

  it("offers certifying_official nowhere in the role list, and says why", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
    });

    const select = await screen.findByLabelText(
      "Headway role for this group",
    );
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual([
      "Viewer",
      "Auditor",
      "Data steward",
      "Report preparer",
    ]);
    expect(options).not.toContain("Certifying official");
    // An omission with no explanation reads as an oversight and invites
    // someone to look for a way round it.
    expect(document.body).toHaveTextContent(
      "Certifying official is deliberately missing from this list.",
    );
    expect(document.body).toHaveTextContent(
      "They still sign in through your identity provider.",
    );
  });

  it("adds a mapping and confirms exactly what it now grants", async () => {
    signInAs("certifying_official");
    let added = false;
    const calls = mockApi({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": () => ({
        status: 200,
        body: added
          ? [
              ...MAPPINGS,
              {
                mapping_id: "m-3",
                claim_value: "aa11-planning",
                headway_role: "viewer",
                role_label: "viewer",
                note: "Planning team",
                created_by: "test.user",
                created_at: "2026-08-02T10:00:00Z",
              },
            ]
          : MAPPINGS,
      }),
      "POST /auth/oidc/mappings": () => {
        added = true;
        return {
          status: 201,
          body: {
            mapping_id: "m-3",
            claim_value: "aa11-planning",
            headway_role: "viewer",
            role_label: "viewer",
            note: "Planning team",
            created_by: "test.user",
            created_at: "2026-08-02T10:00:00Z",
            audit_event_id: 44,
          },
        };
      },
    });
    renderApp("/admin");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Set up single sign-on" }),
    );

    await user.type(
      await screen.findByLabelText("Group value"),
      "aa11-planning",
    );
    await user.type(screen.getByLabelText("Note (optional)"), "Planning team");
    await user.click(screen.getByRole("button", { name: "Add group" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Anyone in 'aa11-planning' will sign in as a Viewer from now on.",
    );
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({
      claim_value: "aa11-planning",
      headway_role: "viewer",
      note: "Planning team",
    });
    // Always re-read from the server after a change — never client-adjust.
    expect(await screen.findByText("aa11-planning")).toBeInTheDocument();
  });

  it("surfaces the server's certifying-official refusal verbatim if one is ever attempted", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
      "POST /auth/oidc/mappings": {
        status: 422,
        body: { detail: CERT_OFFICIAL_422 },
      },
    });
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Group value"), "domain-admins");
    await user.click(screen.getByRole("button", { name: "Add group" }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((a) => a.textContent === CERT_OFFICIAL_422)).toBe(true);
  });

  it("removing a mapping says accounts it already created are unchanged", async () => {
    signInAs("certifying_official");
    let removed = false;
    mockApi({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": () => ({
        status: 200,
        body: removed ? [MAPPINGS[1]] : MAPPINGS,
      }),
      "DELETE /auth/oidc/mappings/m-1": () => {
        removed = true;
        return {
          status: 200,
          body: {
            claim_value: "3f7a-transit-stewards",
            headway_role: "data_steward",
            audit_event_id: 51,
          },
        };
      },
    });
    renderApp("/admin");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Set up single sign-on" }),
    );

    await user.click(
      await screen.findByRole("button", {
        name: "Remove the mapping for 3f7a-transit-stewards",
      }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "no longer grants any access. Accounts it already created are unchanged",
    );
    await waitFor(() =>
      expect(screen.queryByText("3f7a-transit-stewards")).toBeNull(),
    );
  });

  // -----------------------------------------------------------------------
  // "Test this configuration"
  // -----------------------------------------------------------------------

  it("reports every test step with a TEXT verdict, never colour alone", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
      "POST /auth/oidc/config/test": {
        status: 200,
        body: {
          ok: true,
          audit_event_id: 61,
          steps: [
            {
              step: "reach your identity provider",
              ok: true,
              message:
                "Headway reached your identity provider and read its configuration.",
            },
            {
              step: "read the signing keys",
              ok: true,
              message:
                "Your provider publishes 2 signing keys. Headway re-reads them automatically when your provider rotates them, so a rotation will not interrupt sign-in.",
            },
            {
              step: "check the client id and secret",
              ok: true,
              message:
                "Your identity provider accepted Headway's client id and client secret.",
            },
          ],
        },
      },
    });
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", { name: "Test this configuration" }),
    );

    const row = (await screen.findByText("read the signing keys")).closest(
      "tr",
    )!;
    expect(within(row).getByText("Working")).toBeInTheDocument();
    expect(row).toHaveTextContent("rotates them");
    const statuses = await screen.findAllByRole("status");
    expect(statuses.some((n) => n.textContent?.includes(
      "Everything Headway can check by itself is working.",
    ))).toBe(true);
    await expectNoAxeViolations();
  });

  it("a failing step says what to do, in words, and the overall verdict is honest", async () => {
    signInAs("certifying_official");
    const SECRET_REJECTED =
      "Your identity provider rejected Headway's client id or client " +
      "secret. Check the client id above, and enter the client secret " +
      "again — if the secret was rotated at the provider, Headway still " +
      "holds the old one. (Headway sent a deliberately invalid sign-in " +
      "code to test this; no one was signed in.)";
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
      "POST /auth/oidc/config/test": {
        status: 200,
        body: {
          ok: false,
          audit_event_id: 62,
          steps: [
            {
              step: "reach your identity provider",
              ok: true,
              message: "Headway reached your identity provider.",
            },
            {
              step: "check the client id and secret",
              ok: false,
              message: SECRET_REJECTED,
            },
          ],
        },
      },
    });
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", { name: "Test this configuration" }),
    );

    const row = (await screen.findByText("check the client id and secret")).closest(
      "tr",
    )!;
    expect(within(row).getByText("Needs attention")).toBeInTheDocument();
    expect(row).toHaveTextContent(SECRET_REJECTED);
    expect(document.body).toHaveTextContent(
      "Something is not right yet. Each step below says what to do about it.",
    );
  });

  it("says the test signed nobody in", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
    });
    expect(
      await screen.findByText(/Nobody was signed in\./),
    ).toBeInTheDocument();
  });

  // -----------------------------------------------------------------------
  // Honesty and gating
  // -----------------------------------------------------------------------

  it("says plainly what turning single sign-on on changes on the sign-in page", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
    });
    // Where the button appears, AND that Headway passwords keep working:
    // an administrator deciding whether to switch this on needs both.
    expect(
      await screen.findByText(
        /the sign-in page shows this button under the Headway username and password fields/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/a Headway password is still the way back in/),
    ).toBeInTheDocument();
  });

  it("shows the live status when SSO is on, and when the server has switched it off", async () => {
    signInAs("certifying_official");
    mockApi({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
    });
    const { unmount } = renderApp("/admin");
    expect(
      await screen.findByText("On", { selector: ".admin-card-status" }),
    ).toBeInTheDocument();
    unmount();

    mockApi({
      "GET /auth/oidc/config": {
        status: 200,
        body: { ...CONFIGURED, disabled_by_environment: true },
      },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
    });
    renderApp("/admin");
    expect(
      await screen.findByText("Turned off on the server", {
        selector: ".admin-card-status",
      }),
    ).toBeInTheDocument();
  });

  it("a load failure is shown, not swallowed", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": {
        status: 503,
        body: { detail: "The database is unavailable." },
      },
      "GET /auth/oidc/mappings": { status: 200, body: [] },
    });
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((a) => a.textContent?.includes(
      "Could not load the single sign-on settings.",
    ))).toBe(true);
  });

  it.each(["viewer", "data_steward", "report_preparer", "auditor"] as const)(
    "is not offered to %s, who cannot administer Headway",
    async (role) => {
      signInAs(role);
      mockApi({});
      renderApp("/admin");
      expect(
        await screen.findByText(
          /Only a certifying official can use the admin area/,
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Set up single sign-on" }),
      ).toBeNull();
    },
  );

  it("the whole screen is reachable by keyboard alone", async () => {
    signInAs("certifying_official");
    await openSso({
      "GET /auth/oidc/config": { status: 200, body: CONFIGURED },
      "GET /auth/oidc/mappings": { status: 200, body: MAPPINGS },
    });
    const user = userEvent.setup();
    await screen.findByLabelText("Discovery address");

    // Every control the screen offers must be tabbable; walking forward from
    // the top must reach the last one without a mouse.
    const focusable = Array.from(
      document.querySelectorAll<HTMLElement>(
        "input, select, button, a[href], textarea",
      ),
    ).filter((el) => el.tabIndex >= 0);
    expect(focusable.length).toBeGreaterThan(10);

    document.body.focus();
    const reached = new Set<Element>();
    for (let i = 0; i < focusable.length + 5; i += 1) {
      await user.tab();
      if (document.activeElement) reached.add(document.activeElement);
    }
    expect(reached.has(screen.getByLabelText("Discovery address"))).toBe(true);
    expect(reached.has(screen.getByLabelText("Client secret"))).toBe(true);
    expect(
      reached.has(screen.getByRole("button", { name: "Save settings" })),
    ).toBe(true);
  });
});
