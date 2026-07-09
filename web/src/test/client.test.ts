import { describe, expect, it, vi } from "vitest";
import {
  ApiError,
  listMetricValues,
  setUnauthorizedHandler,
} from "../api/client";
import { getSession } from "../auth/session";
import { mockApi, signInAs } from "./helpers";

describe("api client", () => {
  it("clears the session and invokes the login redirect on a 401", async () => {
    signInAs("viewer");
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    mockApi({
      "GET /metrics/values": {
        status: 401,
        body: { detail: "Your session has expired. Please sign in again." },
      },
    });

    await expect(listMetricValues()).rejects.toMatchObject({
      status: 401,
      message: "Your session has expired. Please sign in again.",
    });
    expect(getSession()).toBeNull();
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    setUnauthorizedHandler(null);
  });

  it("surfaces a 422 validation error's messages verbatim", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": {
        status: 422,
        body: {
          detail: [
            {
              loc: ["query", "period_start"],
              msg: "Input should be a valid date",
              type: "date_parsing",
            },
          ],
        },
      },
    });

    await expect(listMetricValues()).rejects.toMatchObject({
      status: 422,
      message: "Input should be a valid date",
    });
  });

  it("reports a network failure in plain language", async () => {
    signInAs("viewer");
    vi.stubGlobal("fetch", () => Promise.reject(new TypeError("boom")));

    await expect(listMetricValues()).rejects.toMatchObject({
      status: 0,
      message:
        "Headway could not reach the server. Check your connection and try again.",
    });
  });

  it("attaches the bearer token and encodes query filters", async () => {
    signInAs("viewer");
    const calls = mockApi({
      "GET /metrics/values": { status: 200, body: [] },
    });

    await listMetricValues({ metric: "vrm", period_start: "2026-03-01" });
    expect(calls[0].url).toBe(
      "/metrics/values?metric=vrm&period_start=2026-03-01",
    );
    expect(calls[0].headers["Authorization"]).toBe("Bearer test-token");
  });

  it("is an ApiError instance callers can branch on", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 500, body: { detail: "boom" } },
    });
    await expect(listMetricValues()).rejects.toBeInstanceOf(ApiError);
  });
});
