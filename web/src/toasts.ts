/**
 * Action-confirmation toast store (handoff 0017, design point 4): the
 * shell-wide pattern for create / supersede / certify confirmations. The
 * shell (Layout) renders the one toast region — a PERSISTENT aria-live
 * polite container, so screen readers reliably announce messages added to
 * it — and views push plain-language confirmations here instead of each
 * rendering its own live region.
 *
 * Lifetime is DETERMINISTIC, never a timer: a toast stays until the user
 * dismisses it or navigates to another page (the shell clears the stack on
 * route change), and at most the three newest confirmations are kept. No
 * auto-hide — a confirmation that vanishes on its own schedule is a WCAG
 * 2.2.1 (timing-adjustable) trap and untestable besides.
 *
 * Same module-state store discipline as src/branding.ts / auth/session.ts.
 */

import { useSyncExternalStore } from "react";

export interface Toast {
  id: number;
  message: string;
}

const MAX_TOASTS = 3;

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  for (const fn of listeners) fn();
}

export function getToasts(): Toast[] {
  return toasts;
}

/** Push one confirmation. Newest last; only the newest three are kept. */
export function pushToast(message: string): void {
  toasts = [...toasts, { id: nextId++, message }].slice(-MAX_TOASTS);
  emit();
}

export function dismissToast(id: number): void {
  toasts = toasts.filter((toast) => toast.id !== id);
  emit();
}

/** Route-change + test hygiene: confirmations belong to the page they
 *  confirmed on. */
export function clearToasts(): void {
  if (toasts.length === 0) return;
  toasts = [];
  emit();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** React hook: re-renders when the toast stack changes. */
export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, getToasts, getToasts);
}
