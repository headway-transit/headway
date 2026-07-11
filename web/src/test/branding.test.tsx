/**
 * Agency branding (handoff 0008, pillar C): the settings page for the
 * certifying official (live preview, server 422 refusals surfaced VERBATIM,
 * multipart logo upload) and the app shell's consumption of GET /branding
 * (display name, logo, chrome-only custom-property overrides).
 */

import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";

const AGENCY_BRANDING = {
  display_name: "Rivertown Transit",
  primary: "#1a5fb4",
  accent: "#0b57d0",
  has_logo: false,
};

// The exact plain-language refusal services/api branding.py produces —
// the UI must show it word for word.
const CONTRAST_REFUSAL =
  "That color doesn't have enough contrast to be readable: '#ffff00' " +
  "measures 1.07:1 against the app's page background (#ffffff), and " +
  "readable text needs at least 4.5:1 (WCAG 2.1 AA). Please choose a " +
  "darker or more saturated color.";

describe("/settings/branding", () => {
  it("is role-gated in the UI: other roles get a plain not-allowed note and no form", async () => {
    signInAs("viewer");
    mockApi({});
    renderApp("/settings/branding");

    expect(
      await screen.findByText(
        /Only a certifying official can change the agency's branding/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("loads current branding into the form and live-previews color edits without saving", async () => {
    signInAs("certifying_official");
    mockApi({ "GET /branding": { status: 200, body: AGENCY_BRANDING } });
    renderApp("/settings/branding");

    const nameInput = await screen.findByLabelText("Agency display name");
    await waitFor(() => expect(nameInput).toHaveValue("Rivertown Transit"));

    // Editing the accent hex updates the LIVE PREVIEW immediately (no save).
    const accentHex = screen.getByLabelText(
      "Accent brand color (hex value)",
    ) as HTMLInputElement;
    expect(accentHex.value).toBe("#0b57d0");
    fireEvent.change(accentHex, { target: { value: "#8250df" } });
    const sampleLink = screen.getByText("Sample link");
    expect(sampleLink).toHaveStyle({ color: "#8250df" });
    // Nothing was PUT: the preview is client-side; the server stays the gate.

    // The preview states the chart rule: brand colors are chrome only.
    expect(
      screen.getByText(
        "Charts keep their own validated palette: brand colors change the chrome, never the data encodings.",
      ),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("saves the display name via PUT /settings/agency_display_name and the header re-brands immediately", async () => {
    const user = userEvent.setup();
    signInAs("certifying_official");
    const calls = mockApi({
      "GET /branding": { status: 200, body: AGENCY_BRANDING },
      "PUT /settings/agency_display_name": (call) => ({
        status: 200,
        body: {
          setting_key: "agency_display_name",
          setting_value: (call.body as { value: string }).value,
          value_type: "text",
          description: "Agency display name",
          updated_by: "test.user",
          updated_at: "2026-07-11T12:00:00Z",
          audit_event_id: 41,
        },
      }),
    });
    renderApp("/settings/branding");

    const nameInput = await screen.findByLabelText("Agency display name");
    await waitFor(() => expect(nameInput).toHaveValue("Rivertown Transit"));
    await user.clear(nameInput);
    await user.type(nameInput, "Metro Transit Authority");
    await user.click(
      screen.getByRole("button", { name: "Save display name" }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Display name saved. The header now shows “Metro Transit Authority”.",
    );
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.path).toBe("/settings/agency_display_name");
    expect(put?.body).toEqual({ value: "Metro Transit Authority" });

    // The app shell consumed the change: the header shows the new name.
    const header = screen.getByRole("banner");
    expect(within(header).getByText("Metro Transit Authority")).toBeInTheDocument();
  });

  it("surfaces the server's contrast refusal VERBATIM when a brand color is rejected (422)", async () => {
    const user = userEvent.setup();
    signInAs("certifying_official");
    mockApi({
      "GET /branding": { status: 200, body: AGENCY_BRANDING },
      "PUT /settings/brand_color_primary": {
        status: 422,
        body: { detail: CONTRAST_REFUSAL },
      },
    });
    renderApp("/settings/branding");

    const primaryHex = await screen.findByLabelText(
      "Primary brand color (hex value)",
    );
    fireEvent.change(primaryHex, { target: { value: "#ffff00" } });
    await user.click(
      screen.getByRole("button", { name: "Save primary brand color" }),
    );

    // Word for word — the UI never rewrites or softens the refusal.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      CONTRAST_REFUSAL,
    );
    await expectNoAxeViolations();
  });

  it("uploads the logo as multipart form data to POST /branding/logo and the header shows it", async () => {
    const user = userEvent.setup();
    signInAs("certifying_official");
    const calls = mockApi({
      "GET /branding": { status: 200, body: AGENCY_BRANDING },
      "POST /branding/logo": {
        status: 200,
        body: { content_type: "image/svg+xml", bytes: 512, audit_event_id: 42 },
      },
    });
    renderApp("/settings/branding");

    const fileInput = await screen.findByLabelText("Logo file");
    const file = new File(["<svg xmlns='http://www.w3.org/2000/svg'/>"], "logo.svg", {
      type: "image/svg+xml",
    });
    await user.upload(fileInput, file);
    await user.click(screen.getByRole("button", { name: "Upload logo" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Logo uploaded (512 bytes). It now appears in the header.",
    );

    // The request was multipart with the file under the "file" field, and
    // no JSON content type was forced onto it.
    const post = calls.find((c) => c.method === "POST");
    expect(post).toBeDefined();
    expect(post!.path).toBe("/branding/logo");
    expect(post!.body).toBeInstanceOf(FormData);
    expect((post!.body as FormData).get("file")).toBeInstanceOf(File);
    expect(post!.headers["Content-Type"]).toBeUndefined();

    // The shell consumed has_logo: the header now renders the logo image.
    const header = screen.getByRole("banner");
    expect(header.querySelector("img.brand-logo")).not.toBeNull();
  });
});

describe("app shell branding consumption", () => {
  it("brands the chrome from GET /branding on load: display name, logo, and --brand-* custom properties (never chart tokens)", async () => {
    signInAs("viewer");
    mockApi({
      "GET /branding": {
        status: 200,
        body: {
          display_name: "Rivertown Transit",
          primary: "#7a2048",
          accent: "#1a5fb4",
          has_logo: true,
        },
      },
      "GET /metrics/values": { status: 200, body: [] },
    });
    renderApp("/metrics");

    const header = await screen.findByRole("banner");
    expect(
      await within(header).findByText("Rivertown Transit"),
    ).toBeInTheDocument();
    const logo = header.querySelector("img.brand-logo") as HTMLImageElement;
    expect(logo).not.toBeNull();
    expect(logo.src).toContain("/branding/logo");

    // Chrome-only custom properties on the root — the chart tokens
    // (--series-*) are untouched by branding.
    const rootStyle = document.documentElement.style;
    await waitFor(() =>
      expect(rootStyle.getPropertyValue("--brand-primary")).toBe("#7a2048"),
    );
    expect(rootStyle.getPropertyValue("--brand-accent")).toBe("#1a5fb4");
    expect(rootStyle.getPropertyValue("--series-1")).toBe("");
    expect(rootStyle.getPropertyValue("--series-2")).toBe("");

    await expectNoAxeViolations();
  });

  it("keeps the default name when branding cannot load — chrome never blocks the app", async () => {
    signInAs("viewer");
    mockApi({
      "GET /branding": { status: 503, body: { detail: "unavailable" } },
      "GET /metrics/values": { status: 200, body: [] },
    });
    renderApp("/metrics");

    expect(
      await screen.findByRole("heading", { name: "Computed metric values" }),
    ).toBeInTheDocument();
    const header = screen.getByRole("banner");
    expect(within(header).getByText("Headway")).toBeInTheDocument();
  });
});
