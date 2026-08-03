/**
 * The raw-record inspector (handoff 0035): the lineage leaf, opened.
 *
 * What these tests hold to: the leaf must be openable from BOTH renderings,
 * the label must show what the record is, the integrity verdict must be
 * unmissable when it fails, the preview must state its cap before its data,
 * a withheld payload must explain itself, and the fingerprint must still be
 * on screen — in the footnote, not as the whole answer.
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
import { lineageTree } from "./fixtures";

const RAW_ID = "sha256:aaaa1111";
/** The client percent-encodes the id into the path; the mock keys match. */
const RAW_PATH = `/raw/records/${encodeURIComponent(RAW_ID)}`;

const label = {
  record_id: RAW_ID,
  source: "gtfs_rt",
  simulated: false,
  connector: "headway-gtfs-rt",
  connector_version: "0.1.0",
  content_type: "application/x-protobuf",
  payload_encoding: "base64",
  fetched_at: "2026-07-30T23:26:07Z",
  landed_at: "2026-07-30T23:26:07Z",
  parse_status: "ok",
  parse_error: null,
  stored_bytes: {
    location: "ingest_envelope_stream",
    object_key: null,
    size_bytes: null,
    status: "measured_on_open",
    note: "This record's bytes rode inline in the ingest envelope on the message broker rather than being written to the object store.",
  },
  content_address: {
    algorithm: "sha-256",
    digest: RAW_ID,
    note: "This record's id is the SHA-256 hash of the bytes exactly as they were received.",
  },
  sensitivity: {
    classification: "internal",
    label: "Agency operational data",
    minimum_role: "viewer",
    reason: "Agency operational data (docs/data-classification.md).",
    preview_allowed: true,
    refusal: null,
  },
  decoder: {
    kind: "gtfs_realtime",
    note: "A GTFS-Realtime feed message.",
  },
  immutability_note: "Raw records are never edited.",
};

const withheldLabel = {
  ...label,
  source: "dr_simulated",
  connector: "headway-dr",
  content_type: "text/csv",
  payload_encoding: "object_ref",
  stored_bytes: { ...label.stored_bytes, location: "object_store", size_bytes: 5130, status: "available" },
  decoder: { kind: "delimited_text", note: "A comma-separated file." },
  sensitivity: {
    classification: "rider_location",
    label: "Rider locations — restricted",
    minimum_role: "data_steward",
    reason: "Its rows carry pickup and dropoff coordinates.",
    preview_allowed: false,
    refusal:
      "Your account cannot open the contents of this raw record. Its rows carry pickup and dropoff coordinates, which are rider home and destination addresses.",
  },
};

const matchVerdict = {
  record_id: RAW_ID,
  verified_at: "2026-07-30T23:26:19Z",
  result: "match",
  algorithm: "sha-256",
  expected_digest: RAW_ID,
  actual_digest: RAW_ID,
  size_bytes: 67246,
  read_from: "ingest_envelope_stream",
  reason: null,
  headline: "Verified: the stored bytes are unaltered.",
  detail:
    "Headway re-read all 67,246 bytes and re-computed their SHA-256. It matches this record's id exactly.",
  dq_issue_id: null,
};

const mismatchVerdict = {
  ...matchVerdict,
  result: "mismatch",
  actual_digest: "sha256:tampered0000",
  headline:
    "MISMATCH: the stored bytes are NOT the bytes this record was created from.",
  detail:
    "Treat every figure that cites this record as unproven until someone explains the difference.",
  dq_issue_id: "11111111-2222-3333-4444-555555555555",
};

const gtfsPreview = {
  record_id: RAW_ID,
  content_type: "application/x-protobuf",
  size_bytes: 67246,
  read_from: "ingest_envelope_stream",
  decoder: "gtfs_realtime",
  decoder_note: "A GTFS-Realtime feed message.",
  truncated: true,
  truncation_note:
    "Showing the first 25 of 599 entities in this feed message. The remaining entities are in the bytes you can download; nothing was dropped from the record.",
  caps: { max_entities: 25, max_stop_time_updates_per_entity: 3, max_bytes_read: 4194304 },
  gtfs_realtime: {
    decoded: true,
    decode_error: null,
    gtfs_realtime_version: "2.0",
    incrementality: "FULL_DATASET",
    header_timestamp: 1785453964,
    header_timestamp_utc: "2026-07-30T23:26:04Z",
    entity_count: 599,
    entity_kinds: { vehicle: 599, trip_update: 0, alert: 0, other: 0 },
    entities: [
      {
        entity_id: "y1221",
        is_deleted: null,
        kind: "vehicle_position",
        vehicle_id: "y1221",
        vehicle_label: "1221",
        trip_id: "77139759",
        route_id: "28",
        direction_id: 0,
        latitude: 42.336429595947266,
        longitude: -71.0899887084961,
        bearing: 45,
        speed: null,
        timestamp: 1785453953,
        timestamp_utc: "2026-07-30T23:25:53Z",
        current_status: "STOPPED_AT",
        stop_id: "17865",
        occupancy_status: "MANY_SEATS_AVAILABLE",
      },
      {
        entity_id: "ynk230",
        is_deleted: null,
        kind: "vehicle_position",
        vehicle_id: "ynk230",
        vehicle_label: "230",
        trip_id: "BL-40770992",
        route_id: "Shuttle-Generic",
        direction_id: null,
        latitude: 42.36253356933594,
        longitude: -71.08747863769531,
        bearing: null,
        speed: null,
        timestamp: 1785453953,
        timestamp_utc: "2026-07-30T23:25:53Z",
        current_status: "IN_TRANSIT_TO",
        stop_id: null,
        occupancy_status: null,
      },
      {
        // A vehicle reporting a position with no trip assignment — ordinary
        // in a real feed, and the case that proves absent renders absent.
        entity_id: "y1970",
        is_deleted: null,
        kind: "vehicle_position",
        vehicle_id: "y1970",
        vehicle_label: "1970",
        trip_id: null,
        route_id: null,
        direction_id: null,
        latitude: 42.3601,
        longitude: -71.0589,
        bearing: null,
        speed: null,
        timestamp: 1785453900,
        timestamp_utc: "2026-07-30T23:25:00Z",
        current_status: null,
        stop_id: null,
        occupancy_status: null,
      },
    ],
  },
  delimited: null,
  text: null,
  undecoded: null,
  download_note:
    "Download gives you the exact bytes Headway received — the same bytes whose SHA-256 is sha256:aaaa1111.",
};

const zipPreview = {
  ...gtfsPreview,
  content_type: "application/zip",
  decoder: "none",
  decoder_note: "Headway has no reader for application/zip yet.",
  truncation_note:
    "Nothing of the contents is shown: Headway has no reader for application/zip yet.",
  gtfs_realtime: null,
  undecoded: {
    content_type: "application/zip",
    reason:
      "Headway decodes GTFS-Realtime feeds and text files today. For anything else it hands over the exact bytes instead.",
  },
};

function mockLineageWith(handlers: Record<string, unknown> = {}) {
  return mockApi({
    "GET /metrics/values/mv-vrm-1/lineage": { status: 200, body: lineageTree },
    ...(handlers as Record<string, never>),
  });
}

async function openTextViewLeaf() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Text view" }));
  const opener = (
    await screen.findAllByRole("button", {
      name: `Open the raw source record ${RAW_ID}`,
    })
  )[0];
  await user.click(opener);
  return user;
}

describe("raw-record inspector (handoff 0035)", () => {
  it("the lineage leaf no longer calls itself the end of the trail", async () => {
    signInAs("viewer");
    mockLineageWith();
    renderApp("/metrics/mv-vrm-1/lineage");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Text view" }));

    expect(
      screen.getAllByText("raw source record, exactly as Headway received it"),
    ).toHaveLength(2);
    expect(
      screen.queryByText(/the end of the trail/),
    ).not.toBeInTheDocument();
    // Every leaf offers the way in.
    expect(
      screen.getAllByRole("button", { name: /^Open the raw source record/ }),
    ).toHaveLength(2);
  });

  it("opening a leaf shows the label, with the fingerprint demoted to a footnote", async () => {
    signInAs("viewer");
    mockLineageWith({ [`GET ${RAW_PATH}`]: { status: 200, body: label } });
    renderApp("/metrics/mv-vrm-1/lineage");
    await openTextViewLeaf();

    expect(await screen.findByText("gtfs_rt")).toBeInTheDocument();
    expect(
      screen.getByText("headway-gtfs-rt (version 0.1.0)"),
    ).toBeInTheDocument();
    expect(screen.getByText("2026-07-30 23:26:07 UTC")).toBeInTheDocument();
    expect(screen.getByText("application/x-protobuf")).toBeInTheDocument();
    expect(screen.getByText("Read successfully")).toBeInTheDocument();
    // The size is honestly absent until the payload is opened.
    expect(
      screen.getByText("measured when you open the contents"),
    ).toBeInTheDocument();
    // The hash is still on screen — as the footnote it should always have been.
    expect(screen.getByText("Fingerprint (SHA-256)")).toBeInTheDocument();
    expect(screen.getAllByText(RAW_ID).length).toBeGreaterThan(0);

    await expectNoAxeViolations();
  });

  it("a record that could not be read on arrival says so with the parser's own reason", async () => {
    signInAs("viewer");
    mockLineageWith({
      [`GET ${RAW_PATH}`]: {
        status: 200,
        body: {
          ...label,
          parse_status: "malformed",
          parse_error:
            "gtfs-realtime FeedMessage parse failed: proto: cannot parse invalid wire-format data",
        },
      },
    });
    renderApp("/metrics/mv-vrm-1/lineage");
    await openTextViewLeaf();

    expect(await screen.findByText("Could not be read")).toBeInTheDocument();
    expect(
      screen.getByText(/cannot parse invalid wire-format data/),
    ).toBeInTheDocument();
  });

  it("a passing integrity check is a status with both fingerprints shown", async () => {
    signInAs("viewer");
    mockLineageWith({
      [`GET ${RAW_PATH}`]: { status: 200, body: label },
      [`POST ${RAW_PATH}/verify`]: { status: 200, body: matchVerdict },
    });
    renderApp("/metrics/mv-vrm-1/lineage");
    const user = await openTextViewLeaf();

    await user.click(
      await screen.findByRole("button", { name: "Verify integrity" }),
    );
    const verdict = await screen.findByRole("status");
    expect(within(verdict).getByText("Integrity verified")).toBeInTheDocument();
    expect(
      within(verdict).getByText(/the stored bytes are unaltered/),
    ).toBeInTheDocument();
    expect(
      within(verdict).getByText(
        "This record's id (the fingerprint of the bytes as received)",
      ),
    ).toBeInTheDocument();
    expect(
      within(verdict).getByText("The fingerprint of the bytes stored right now"),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("a MISMATCH is loud: an alert, both digests, and the finding it raised", async () => {
    signInAs("data_steward");
    mockLineageWith({
      [`GET ${RAW_PATH}`]: { status: 200, body: label },
      // The API answers 409 on purpose so a caller checking only the status
      // cannot mistake a failure for a pass; the client reads the body anyway.
      [`POST ${RAW_PATH}/verify`]: {
        status: 409,
        body: mismatchVerdict,
      },
    });
    renderApp("/metrics/mv-vrm-1/lineage");
    const user = await openTextViewLeaf();

    await user.click(
      await screen.findByRole("button", { name: "Verify integrity" }),
    );
    const alert = await screen.findByRole("alert");
    expect(
      within(alert).getByText("INTEGRITY CHECK FAILED"),
    ).toBeInTheDocument();
    expect(
      within(alert).getByText(/are NOT the bytes this record was created from/),
    ).toBeInTheDocument();
    expect(within(alert).getByText("sha256:tampered0000")).toBeInTheDocument();
    expect(
      within(alert).getByText(
        `Data-quality finding raised: ${mismatchVerdict.dq_issue_id}`,
      ),
    ).toBeInTheDocument();
    expect(
      within(alert).getByRole("link", { name: "Open the finding" }),
    ).toHaveAttribute("href", `/dq/issues/${mismatchVerdict.dq_issue_id}`);
    // Loudness is not carried by colour: the class is there AND the words are.
    expect(alert).toHaveClass("raw-record-verdict-fail");

    await expectNoAxeViolations();
  });

  it("unreadable bytes report the server's own sentence, not a fabricated verdict", async () => {
    signInAs("viewer");
    mockLineageWith({
      [`GET ${RAW_PATH}`]: { status: 200, body: label },
      [`POST ${RAW_PATH}/verify`]: {
        status: 410,
        body: {
          ...matchVerdict,
          result: "unavailable",
          actual_digest: null,
          reason: "not_retained",
          headline: "Headway could not read this record's bytes.",
          detail:
            "The broker no longer retains that message. The record's identity and its place in the trail are unaffected.",
        },
      },
    });
    renderApp("/metrics/mv-vrm-1/lineage");
    const user = await openTextViewLeaf();
    await user.click(
      await screen.findByRole("button", { name: "Verify integrity" }),
    );

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Could not be checked")).toBeInTheDocument();
    expect(
      within(alert).getByText(/no longer retains that message/),
    ).toBeInTheDocument();
    expect(within(alert).getByText("not reported")).toBeInTheDocument();
  });

  it("the preview decodes a feed message to its real vehicles, cap stated first", async () => {
    signInAs("viewer");
    mockLineageWith({
      [`GET ${RAW_PATH}`]: { status: 200, body: label },
      [`GET ${RAW_PATH}/payload`]: { status: 200, body: gtfsPreview },
    });
    renderApp("/metrics/mv-vrm-1/lineage");
    const user = await openTextViewLeaf();

    const inspect = await screen.findByRole("button", { name: "Look inside" });
    expect(inspect).toHaveAttribute("aria-expanded", "false");
    await user.click(inspect);

    expect(
      await screen.findByText(/Showing the first 25 of 599 entities/),
    ).toBeInTheDocument();
    const table = screen.getByRole("table", {
      name: "Vehicles and updates in this message",
    });
    // The steward's own bus, at that minute, at those coordinates.
    expect(within(table).getByText("1221")).toBeInTheDocument();
    expect(within(table).getByText("28")).toBeInTheDocument();
    expect(within(table).getByText("77139759")).toBeInTheDocument();
    expect(within(table).getByText("42.33643, -71.08999")).toBeInTheDocument();
    expect(
      within(table).getAllByText("2026-07-30 23:25:53 UTC"),
    ).toHaveLength(2);
    expect(within(table).getByText("STOPPED_AT")).toBeInTheDocument();
    // An absent value is stated absent, never rendered as a zero.
    expect(within(table).getAllByText("not reported").length).toBeGreaterThan(0);
    expect(screen.getByText("599")).toBeInTheDocument();

    expect(inspect).toHaveAttribute("aria-expanded", "true");
    await expectNoAxeViolations();
  });

  it("an undecodable type states what it is and offers the bytes", async () => {
    signInAs("viewer");
    mockLineageWith({
      [`GET ${RAW_PATH}`]: { status: 200, body: label },
      [`GET ${RAW_PATH}/payload`]: { status: 200, body: zipPreview },
    });
    renderApp("/metrics/mv-vrm-1/lineage");
    const user = await openTextViewLeaf();
    await user.click(await screen.findByRole("button", { name: "Look inside" }));

    expect(
      await screen.findByText("Headway cannot show this file's contents"),
    ).toBeInTheDocument();
    expect(screen.getByText(/hands over the exact bytes/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Download the exact bytes" }),
    ).toBeInTheDocument();
  });

  it("a withheld payload explains itself and still offers the integrity check", async () => {
    signInAs("viewer");
    const calls = mockLineageWith({
      [`GET ${RAW_PATH}`]: { status: 200, body: withheldLabel },
    });
    renderApp("/metrics/mv-vrm-1/lineage");
    const user = await openTextViewLeaf();

    expect(await screen.findByText("Contents withheld")).toBeInTheDocument();
    expect(
      screen.getByText(/rider home and destination addresses/),
    ).toBeInTheDocument();
    // The window is closed; the chain of custody is not broken.
    expect(
      screen.getByRole("button", { name: "Verify integrity" }),
    ).toBeEnabled();
    // aria-disabled, NOT the native attribute (handoff 0047, design point
    // 3): the control stays in the tab order and carries the server's own
    // refusal as its description, so a keyboard or screen-reader reviewer
    // meets the withholding instead of a silence they would record as
    // missing data. The click is refused rather than swallowed — nothing is
    // asked of the server.
    const inspect = screen.getByRole("button", { name: "Look inside" });
    expect(inspect).toHaveAttribute("aria-disabled", "true");
    expect(inspect).toHaveAccessibleDescription(
      /rider home and destination addresses/,
    );
    await user.click(inspect);
    expect(inspect).toHaveAttribute("aria-expanded", "false");
    expect(calls.some((c) => c.path === `${RAW_PATH}/payload`)).toBe(false);
    expect(
      screen.queryByRole("button", { name: "Download the exact bytes" }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("the graph view reaches the SAME inspector (view parity)", async () => {
    signInAs("viewer");
    mockLineageWith({
      [`GET ${RAW_PATH}`]: { status: 200, body: label },
    });
    renderApp("/metrics/mv-vrm-1/lineage");
    const user = userEvent.setup();

    const graph = await screen.findByRole("group", { name: /Lineage graph/ });
    await user.click(within(graph).getByRole("button", { name: /2 raw records/ }));
    const rawNode = within(graph).getByRole("button", {
      name: `Open the raw source record ${RAW_ID}`,
    });
    await user.click(rawNode);

    const panel = screen.getByRole("region", {
      name: `Open the raw source record ${RAW_ID}`,
    });
    expect(await within(panel).findByText("gtfs_rt")).toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: "Verify integrity" }),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("the graph raw node is reachable and activatable by keyboard alone", async () => {
    signInAs("viewer");
    mockLineageWith({
      [`GET ${RAW_PATH}`]: { status: 200, body: label },
    });
    renderApp("/metrics/mv-vrm-1/lineage");
    const user = userEvent.setup();

    const graph = await screen.findByRole("group", { name: /Lineage graph/ });
    const rawGroup = within(graph).getByRole("button", { name: /2 raw records/ });
    rawGroup.focus();
    await user.keyboard("{Enter}");
    await user.keyboard("{ArrowDown}");
    const rawNode = within(graph).getByRole("button", {
      name: `Open the raw source record ${RAW_ID}`,
    });
    expect(rawNode).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(
      await screen.findByRole("region", {
        name: `Open the raw source record ${RAW_ID}`,
      }),
    ).toBeInTheDocument();
  });

  it("a refused label surfaces the server's message verbatim", async () => {
    signInAs("viewer");
    mockLineageWith({
      [`GET ${RAW_PATH}`]: {
        status: 404,
        body: { detail: "No raw record with that id exists in this Headway installation." },
      },
    });
    renderApp("/metrics/mv-vrm-1/lineage");
    await openTextViewLeaf();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No raw record with that id exists in this Headway installation.",
    );
  });
});
