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

const ROLE_RANK: Record<Role, number> = {
  viewer: 0,
  data_steward: 1,
  report_preparer: 2,
  certifying_official: 3,
};

export function isKnownRole(role: string): role is Role {
  return role in ROLE_RANK;
}

/** Mirrors the API: resolving a DQ issue requires data_steward or above. */
export function canResolveDqIssues(session: Session | null): boolean {
  return session !== null && ROLE_RANK[session.role] >= ROLE_RANK.data_steward;
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
 * Mirrors the API (handoff 0010): recording or correcting a safety event
 * requires data_steward or above.
 */
export function canEnterSafetyEvents(session: Session | null): boolean {
  return session !== null && ROLE_RANK[session.role] >= ROLE_RANK.data_steward;
}

/**
 * Mirrors the API (handoff 0012): creating sampling plans, drawing period
 * samples, and recording measurements require data_steward or above.
 * Reading plans stays open to every signed-in role.
 */
export function canManageSampling(session: Session | null): boolean {
  return session !== null && ROLE_RANK[session.role] >= ROLE_RANK.data_steward;
}

/**
 * Mirrors the API (handoff 0012): generating the §83 estimate requires
 * report_preparer or above (services/api routers/sampling.py).
 */
export function canRunSamplingEstimate(session: Session | null): boolean {
  return (
    session !== null && ROLE_RANK[session.role] >= ROLE_RANK.report_preparer
  );
}
