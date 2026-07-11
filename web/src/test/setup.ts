import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { clearSession } from "../auth/session";
import { clearBranding } from "../branding";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  clearSession(); // module-state session must not leak between tests
  clearBranding(); // module-state branding must not leak between tests
  // Theme + brand chrome must not leak between tests either: the toggle
  // persists to localStorage and stamps <html>, and the shell sets the
  // --brand-* custom properties on <html>.
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.removeProperty("--brand-primary");
  document.documentElement.style.removeProperty("--brand-accent");
});
