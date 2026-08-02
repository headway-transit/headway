/**
 * In-memory session store (module state).
 *
 * SECURITY NOTE — deliberate walking-skeleton choice: the bearer token lives
 * only in JS memory, never in localStorage/sessionStorage (no persistence for
 * an XSS payload to steal at rest). A page reload signs the user out. The
 * hardening increment is a server-set httpOnly, Secure, SameSite cookie
 * session, which removes the token from JS reach entirely (tracked in
 * web/README.md).
 *
 * Role checks here are UX ONLY (what to render). Authorization is enforced
 * server-side on every request — hiding a button is never security.
 */

import { useSyncExternalStore } from "react";
import type { Role } from "../api/types";

export interface Session {
  token: string;
  username: string;
  role: Role;
}

let current: Session | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const fn of listeners) fn();
}

export function getSession(): Session | null {
  return current;
}

export function setSession(session: Session): void {
  current = session;
  emit();
}

export function clearSession(): void {
  current = null;
  emit();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** React hook: re-renders when the session changes. */
export function useSession(): Session | null {
  return useSyncExternalStore(subscribe, getSession, getSession);
}

/**
 * THE LADDER, mirroring services/api authz.py exactly. `auditor` is
 * deliberately ABSENT (handoff 0046): every helper below asks
 * `rank(caller) >= rank(required)`, so a rung would hand a read-only role
 * every capability at or below it by arithmetic. Off the ladder, it fails
 * every one of them by construction — the same shape as the server, so the
 * UI hides exactly what the API refuses.
 */
const ROLE_RANK: Record<string, number> = {
  viewer: 0,
  data_steward: 1,
  report_preparer: 2,
  certifying_official: 3,
};

/** Roles that live BESIDE the ladder: broad read, zero write. */
const READ_ONLY_ROLES = new Set<string>(["auditor"]);

const KNOWN_ROLES = new Set<string>([
  ...Object.keys(ROLE_RANK),
  ...READ_ONLY_ROLES,
]);

export function isKnownRole(role: string): role is Role {
  return KNOWN_ROLES.has(role);
}

/**
 * Rank comparison that is honest about off-ladder roles: an auditor (or any
 * role this build does not recognise) satisfies NOTHING. Deny-by-default in
 * the UI too, so a screen never offers a control the server will refuse.
 */
function atLeast(session: Session | null, minimum: string): boolean {
  if (session === null) return false;
  if (READ_ONLY_ROLES.has(session.role)) return false;
  const rank = ROLE_RANK[session.role];
  return rank !== undefined && rank >= ROLE_RANK[minimum];
}

/** Mirrors the API: resolving a DQ issue requires data_steward or above. */
export function canResolveDqIssues(session: Session | null): boolean {
  return atLeast(session, "data_steward");
}

/** Mirrors the API: certification requires EXACTLY certifying_official. */
export function canCertify(session: Session | null): boolean {
  return session !== null && session.role === "certifying_official";
}

/**
 * Recording a statistician attestation (handoff 0019, design A). The
 * handoff names certifying_official as the candidate authorized role (or a
 * new attestation-manager permission if the backend mints one); the
 * smallest honest fit in today's four-role model is certifying_official —
 * the official accountable for what the attestation unlocks. UX only; the
 * API enforces the real rule, and this helper is reconciled against the
 * backend's choice when its routes land.
 */
export function canEnterAttestations(session: Session | null): boolean {
  return canCertify(session);
}

/**
 * Mirrors the API (handoff 0026): POST /calc/runs — asking the server to
 * compute figures — is data_steward or above (report_preparer and
 * certifying_official included via the escalating hierarchy; the recorded
 * decision: computing figures is stewardship, separation of duties bites at
 * certification, not computation). UX only; the API enforces the role.
 */
export function canComputeFigures(session: Session | null): boolean {
  return atLeast(session, "data_steward");
}

/**
 * Mirrors the API (handoff 0025): GET /sources/status is data_steward or
 * above. The admin HUB is presented to the certifying official only, but a
 * steward may open /admin/sources directly — same rule as the API.
 */
export function canViewSourceStatus(session: Session | null): boolean {
  return atLeast(session, "data_steward");
}

/**
 * Mirrors the API (handoff 0010): recording or correcting a safety event
 * requires data_steward or above.
 */
export function canEnterSafetyEvents(session: Session | null): boolean {
  return atLeast(session, "data_steward");
}

/**
 * Mirrors the API (handoff 0012): creating sampling plans, drawing period
 * samples, and recording measurements require data_steward or above.
 * Reading plans stays open to every signed-in role.
 */
export function canManageSampling(session: Session | null): boolean {
  return atLeast(session, "data_steward");
}

/**
 * Mirrors the API (handoff 0012): generating the §83 estimate requires
 * report_preparer or above (services/api routers/sampling.py).
 */
export function canRunSamplingEstimate(session: Session | null): boolean {
  return atLeast(session, "report_preparer");
}
