import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { clearSession } from "../auth/session";
import { clearBranding } from "../branding";
import { clearToasts } from "../toasts";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  clearSession(); // module-state session must not leak between tests
  clearBranding(); // module-state branding must not leak between tests
  clearToasts(); // module-state toast stack must not leak between tests
  // Theme + brand chrome must not leak between tests either: the toggle
  // persists to localStorage and stamps <html>, and the shell sets the
  // --brand-* / --chrome-* custom properties on <html>.
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-chrome");
  document.documentElement.style.removeProperty("--brand-primary");
  document.documentElement.style.removeProperty("--brand-accent");
  document.documentElement.style.removeProperty("--chrome-header-bg");
  document.documentElement.style.removeProperty("--chrome-header-text");
  document.documentElement.style.removeProperty("--chrome-active-accent");
});
