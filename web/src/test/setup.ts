import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { clearSession } from "../auth/session";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  clearSession(); // module-state session must not leak between tests
});
