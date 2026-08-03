/**
 * In-memory session store (module state).
 *
 * SECURITY NOTE — WHERE THE TOKEN LIVES, AND WHY IT MOVED.
 *
 * It used to live only in JS memory, so nothing persisted for an XSS payload
 * to steal at rest. The accepted cost, written here, was "a page reload signs
 * the user out". On a desktop that is an occasional annoyance. On a phone it
 * is unusable: pull-to-refresh is a gesture people make by accident, and being
 * signed out for it makes the app feel broken (reported from the field
 * 2026-08-03).
 *
 * It is now in sessionStorage, which survives a reload and dies with the tab.
 * That is a real trade and worth stating plainly: an XSS payload could now
 * read the token. Three things bound what that buys an attacker, and two of
 * them did not exist when the original note was written:
 *
 *   1. The token expires in 30 minutes (auth.DEFAULT_TOKEN_TTL_SECONDS).
 *   2. Every authenticated request re-reads the account from the database
 *      (auth._live_account), so a stolen token stops working the moment the
 *      account is deactivated or demoted — it no longer runs to expiry.
 *   3. sessionStorage is already how this app carries auth material through
 *      the OIDC redirect: migration 0043 keeps the browser_token there, and
 *      that token is the ONLY thing binding a callback to the browser that
 *      started it.
 *
 * An XSS on this origin can already call the API as the user for as long as
 * the page is open, so the honest description of what persistence adds is
 * "and after they navigate away", not "and now they have your session".
 *
 * THE HARDENING INCREMENT IS UNCHANGED: a server-set httpOnly, Secure,
 * SameSite cookie removes the token from JS reach entirely. This is not that.
 * It is the smaller change that makes the product usable on a phone today,
 * and it does not make the cookie work any harder later (tracked in
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

/** One key, versioned, so a shape change cannot be read as a valid session. */
const STORAGE_KEY = "headway-session-v1";

/**
 * Read a stored session, refusing anything that is not exactly the shape we
 * wrote. A half-valid session is worse than none: it would render a signed-in
 * shell whose every request 401s, and the user would have no way to tell that
 * from an outage.
 */
function restore(): Session | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (
      typeof value !== "object" ||
      value === null ||
      typeof (value as Session).token !== "string" ||
      typeof (value as Session).username !== "string" ||
      typeof (value as Session).role !== "string" ||
      !(value as Session).token
    ) {
      window.sessionStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return value as Session;
  } catch {
    // Storage blocked (private mode, embedded webview) or unparseable. Signed
    // out is the safe reading, and the app still works — it just forgets on
    // reload, exactly as it always did.
    return null;
  }
}

function persist(session: Session | null): void {
  try {
    if (session === null) window.sessionStorage.removeItem(STORAGE_KEY);
    else window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Never fatal. A browser that refuses storage still gets a working
    // session for as long as the page is open.
  }
}

let current: Session | null = restore();
const listeners = new Set<() => void>();

function emit() {
  for (const fn of listeners) fn();
}

export function getSession(): Session | null {
  return current;
}

export function setSession(session: Session): void {
  current = session;
  persist(session);
  emit();
}

export function clearSession(): void {
  current = null;
  // Signing out must clear the stored copy too, or the next reload signs the
  // user straight back in — the exact opposite of what they asked for.
  persist(null);
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

/**
 * Is this a role that only ever READS the record? Deliberately NOT a rank
 * question: `atLeast` denies every read-only role by construction, so asking
 * it "is this an auditor?" can only ever answer no. Membership of
 * READ_ONLY_ROLES is the honest test, and it stays correct for the next
 * read-only role someone puts beside the ladder rather than on it.
 *
 * UX only, like everything else here. It decides which room a reader lands
 * in and which links they are offered — never what the server allows.
 */
export function canReviewOnly(session: Session | null): boolean {
  return session !== null && READ_ONLY_ROLES.has(session.role);
}

/**
 * Where a role lands: after signing in (local or single sign-on) and when
 * "/" is opened directly. ONE definition, read by all three call sites, so
 * they cannot drift apart and leave a role landing in two different rooms
 * depending on how it signed in.
 *
 * /today answers "what should I do now?" — a control room for people who
 * act. A reader's question is "what was filed, and does it hold up?", which
 * is a different surface (handoff 0047), so a read-only role lands on
 * /review. Every other role is untouched.
 */
export function landingPathFor(session: Session | null): string {
  return canReviewOnly(session) ? "/review" : "/today";
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
