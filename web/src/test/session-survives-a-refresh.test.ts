/**
 * A page reload must not sign the user out.
 *
 * Reported from the field 2026-08-03, from a phone: an accidental
 * pull-to-refresh dropped the session and sent the user back to sign-in. On a
 * desktop the old in-memory-only store was an occasional annoyance; on a
 * phone, refresh is a gesture people make by accident and being logged out for
 * it makes the app feel broken.
 *
 * What is asserted here is the whole trade, not just the happy path: it
 * survives a reload, it does NOT survive a sign-out, it does not survive the
 * tab closing (sessionStorage, never localStorage), and a corrupted or
 * half-shaped stored value is refused rather than half-restored — a signed-in
 * shell whose every request 401s is worse than a sign-in screen, because the
 * user cannot tell it from an outage.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const SESSION = {
  token: "a-token",
  username: "vera",
  role: "viewer" as const,
};
const KEY = "headway-session-v1";

/** Re-import the module so its top-level restore() runs again — that is what
 *  a page reload actually does. */
async function reload() {
  vi.resetModules();
  return await import("../auth/session");
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  vi.resetModules();
});

describe("the session across a reload", () => {
  it("survives one", async () => {
    const before = await reload();
    before.setSession(SESSION);
    expect(before.getSession()).toEqual(SESSION);

    const after = await reload();
    expect(after.getSession()).toEqual(SESSION);
  });

  it("does not survive signing out", async () => {
    const before = await reload();
    before.setSession(SESSION);
    before.clearSession();

    // The stored copy has to go too, or the next reload signs the user
    // straight back in — the exact opposite of what they asked for.
    expect(window.sessionStorage.getItem(KEY)).toBeNull();
    const after = await reload();
    expect(after.getSession()).toBeNull();
  });

  it("is in sessionStorage, never localStorage", async () => {
    const store = await reload();
    store.setSession(SESSION);

    expect(window.sessionStorage.getItem(KEY)).toBeTruthy();
    expect(window.localStorage.getItem(KEY)).toBeNull();
    // localStorage would outlive the tab AND every other tab, which is a
    // different and much longer-lived exposure than the one accepted here.
    expect(window.localStorage.length).toBe(0);
  });
});

describe("a stored value that is not a session", () => {
  it.each([
    ["not json at all", "{{{"],
    ["a bare string", '"a-token"'],
    ["null", "null"],
    ["missing the role", JSON.stringify({ token: "t", username: "vera" })],
    ["an empty token", JSON.stringify({ ...SESSION, token: "" })],
    ["a numeric token", JSON.stringify({ ...SESSION, token: 12 })],
  ])("is refused rather than half-restored: %s", async (_label, raw) => {
    window.sessionStorage.setItem(KEY, raw);
    const store = await reload();
    expect(store.getSession()).toBeNull();
  });

  it("is cleared out, so a bad value cannot linger across reloads", async () => {
    window.sessionStorage.setItem(KEY, JSON.stringify({ token: 12 }));
    await reload();
    expect(window.sessionStorage.getItem(KEY)).toBeNull();
  });
});

describe("when the browser refuses storage", () => {
  it("still signs in, and simply forgets on reload", async () => {
    // Private mode and some embedded webviews throw on access rather than
    // returning null. The app must work; it just loses the improvement.
    const boom = () => {
      throw new Error("storage disabled");
    };
    const spies = [
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(boom),
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(boom),
      vi.spyOn(Storage.prototype, "removeItem").mockImplementation(boom),
    ];
    try {
      const store = await reload();
      expect(store.getSession()).toBeNull();
      expect(() => store.setSession(SESSION)).not.toThrow();
      expect(store.getSession()).toEqual(SESSION);
      expect(() => store.clearSession()).not.toThrow();
    } finally {
      for (const spy of spies) spy.mockRestore();
    }
  });
});
